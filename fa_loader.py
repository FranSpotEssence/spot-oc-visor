"""
fa_loader.py — SPOT ESSENCE Forecast Accuracy
Maneja los archivos reales del proceso S&OP:
  • "Base Forecast Acuraccy.xlsx"  → hoja "Forecast Cliente": forecast cliente-SKU-mes
  • "(NN) S&OP <MES> <AÑO> - CIERRE.xlsx" → hoja "S&OP": venta real unidades hasta último mes

Estructura de ambos archivos:
  Fila 0: vacía / meta
  Fila 1: totales agregados
  Fila 2: ENCABEZADOS REALES (Razón Social, SKU, DESCRIPCIÓN, …, columnas datetime)
  Fila 3+: datos

Origen de datos:
  1. OneDrive del usuario (Config.FA_ONEDRIVE_FOLDER) — siempre se intenta primero
  2. Carpeta local de respaldo (Config.FA_DATA_FOLDER) — si OneDrive no está disponible
"""
import io
import logging
import os
import re
import requests
from datetime import datetime
from typing import Optional, Union

import pandas as pd

from config import Config
from fa_calculator import (
    compute_fa_series,
    fa_from_df,
    fa_chip_class,
    fa_semaforo,
    fa_heatmap_color,
)

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ── Caché en memoria ──────────────────────────────────────────────
_fa_cache: Optional[dict] = None

# ── Meses en español ──────────────────────────────────────────────
_MESES_ES = {
    'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4,
    'MAYO': 5, 'JUNIO': 6, 'JULIO': 7, 'AGOSTO': 8,
    'SEPTIEMBRE': 9, 'OCTUBRE': 10, 'NOVIEMBRE': 11, 'DICIEMBRE': 12,
}
_MESES_LABEL = {
    1: 'ENE', 2: 'FEB', 3: 'MAR', 4: 'ABR',
    5: 'MAY', 6: 'JUN', 7: 'JUL', 8: 'AGO',
    9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DIC',
}


def _mes_label(ts: pd.Timestamp) -> str:
    return f"{_MESES_LABEL[ts.month]} {ts.year}"


def _mes_key(ts: pd.Timestamp) -> str:
    return ts.strftime('%Y-%m')


def _norm_str(v) -> str:
    if v is None:
        return ''
    s = str(v).strip()
    return '' if s.lower() in ('nan', 'none', '') else s


def _norm_sku(v) -> str:
    s = _norm_str(v)
    return s[:-2] if s.endswith('.0') else s


# ── Keywords de detección ─────────────────────────────────────────
_KW_FORECAST = {'forecast', 'base forecast'}
_KW_SOP      = {'s&op', 'sop', 'cierre'}

# ── Clientes habilitados en el visor de Forecast Accuracy ──────────
CLIENTES_VISIBLES = {
    'CENCOSUD RETAIL S.A.',
    'ENEX',
    'KEYLOGISTICS CHILE S A',
    'EASY RETAIL S.A. .-',
    'SODIMAC S.A.',
    'WALMART CHILE S.A.',
    'HIPERMERCADOS TOTTUS SA',
}


def _extract_ultimo_mes(filename: str) -> Optional[pd.Timestamp]:
    """
    Extrae el último mes cerrado del nombre del archivo S&OP.
    Ej: "(05) S&OP MAYO 2026 - CIERRE.xlsx" → Timestamp(2026, 5, 1)
    """
    name = os.path.basename(filename).upper()
    for mes_str, mes_num in _MESES_ES.items():
        if mes_str in name:
            m = re.search(r'\b(20\d{2})\b', name)
            if m:
                return pd.Timestamp(int(m.group(1)), mes_num, 1)
    return None


# ══════════════════════════════════════════════════════════════════
#  DESCARGA DESDE SHAREPOINT (link compartido)
# ══════════════════════════════════════════════════════════════════

def _download_fa_from_sharepoint() -> tuple[bytes, str, bytes, str]:
    """
    Lista la carpeta SharePoint via share-link y descarga los 2 archivos FA.
    Retorna (forecast_bytes, forecast_name, sop_bytes, sop_name).
    """
    from graph_client import _encode_share_url, download_file_content

    token   = _get_graph_token()
    headers = {"Authorization": f"Bearer {token}"}
    share_id = _encode_share_url(Config.FA_SHAREPOINT_FOLDER_URL)

    # Listar archivos en la carpeta compartida
    url  = f"{GRAPH_BASE}/shares/{share_id}/driveItem/children"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    items = [
        it for it in resp.json().get("value", [])
        if it.get("name", "").lower().endswith(".xlsx")
        and not it["name"].startswith("~$")
    ]

    if not items:
        raise FileNotFoundError("No se encontraron archivos .xlsx en la carpeta SharePoint FA")

    # Identificar forecast y S&OP
    fc_item = sop_item = None
    for item in items:
        name = item["name"].lower()
        if any(kw in name for kw in _KW_FORECAST):
            fc_item = item
        elif any(kw in name for kw in _KW_SOP):
            sop_item = item

    # Fallback: orden alfabético
    if (fc_item is None or sop_item is None) and len(items) >= 2:
        sorted_items = sorted(items, key=lambda x: x["name"])
        if fc_item is None:
            fc_item = sorted_items[0]
        if sop_item is None:
            sop_item = next((x for x in sorted_items if x is not fc_item), sorted_items[-1])

    if fc_item is None:
        raise FileNotFoundError("No se encontró el archivo de Forecast en SharePoint")
    if sop_item is None:
        raise FileNotFoundError("No se encontró el archivo S&OP en SharePoint")

    log.info("FA SharePoint: forecast=%s | sop=%s", fc_item["name"], sop_item["name"])
    return (
        download_file_content(fc_item), fc_item["name"],
        download_file_content(sop_item), sop_item["name"],
    )


def _get_graph_token() -> str:
    from graph_client import _get_token
    return _get_token()


# ══════════════════════════════════════════════════════════════════
#  DETECCIÓN DE ARCHIVOS LOCALES
# ══════════════════════════════════════════════════════════════════

def _find_local_files(folder: str) -> tuple[Optional[str], Optional[str]]:
    """Retorna (path_forecast, path_sop) desde carpeta local."""
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Carpeta local no encontrada: {folder}")

    files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith('~$')
    ]
    if not files:
        raise FileNotFoundError(f"No hay archivos Excel en: {folder}")

    fc_path = sop_path = None
    for p in files:
        name = os.path.basename(p).lower()
        if any(kw in name for kw in _KW_FORECAST):
            fc_path = p
        elif any(kw in name for kw in _KW_SOP):
            sop_path = p

    if (fc_path is None or sop_path is None) and len(files) >= 2:
        sorted_files = sorted(files)
        if fc_path is None:
            fc_path = sorted_files[0]
        if sop_path is None:
            sop_path = next((x for x in sorted_files if x != fc_path), sorted_files[-1])

    return fc_path, sop_path


# ══════════════════════════════════════════════════════════════════
#  LECTURA DE ARCHIVOS (acepta ruta str o BytesIO)
# ══════════════════════════════════════════════════════════════════

def _map_id_cols(header_row: pd.Series) -> dict:
    id_map = {}
    for idx, val in enumerate(header_row):
        if not isinstance(val, str):
            continue
        v = val.strip().upper()
        if 'RAZ' in v and ('SOCIAL' in v or 'N SOCIAL' in v):
            id_map['cliente'] = idx
        elif v == 'SKU':
            id_map['sku'] = idx
        elif 'DESCRIP' in v:
            id_map['descripcion'] = idx
        elif 'RANKING' in v:
            id_map['ranking'] = idx
        elif 'CATEGOR' in v:
            id_map['categoria'] = idx
        elif 'MARCA' in v:
            id_map['marca'] = idx
    return id_map


def _read_forecast(src: Union[str, io.BytesIO]) -> pd.DataFrame:
    """
    Lee hoja 'Forecast Cliente'.
    Fila 2 (0-indexada) = encabezados reales con columnas datetime = meses de forecast.
    Retorna DataFrame largo: cliente_key, cliente, sku, descripcion, mes_ts, mes_key, mes_label, forecast
    """
    df_raw = pd.read_excel(src, sheet_name='Forecast Cliente', header=None, dtype=object)
    header_row = df_raw.iloc[2]
    id_map = _map_id_cols(header_row)

    date_cols = {}
    for idx, val in enumerate(header_row):
        if isinstance(val, datetime):
            date_cols[idx] = pd.Timestamp(val).replace(day=1)

    df_data = df_raw.iloc[3:].reset_index(drop=True)

    def _col(field):
        if field not in id_map:
            return pd.Series([''] * len(df_data), dtype=object)
        return df_data.iloc[:, id_map[field]]

    df_base = pd.DataFrame({
        'cliente':     _col('cliente').apply(_norm_str),
        'sku':         _col('sku').apply(_norm_sku),
        'descripcion': _col('descripcion').apply(_norm_str),
        'ranking':     _col('ranking').apply(_norm_str),
        'categoria':   _col('categoria').apply(_norm_str),
        'marca':       _col('marca').apply(_norm_str),
    })
    mask = df_base['sku'].notna() & (df_base['sku'] != '') & (df_base['sku'].str.upper() != 'NAN')
    df_base = df_base[mask].copy()
    df_base['cliente_key'] = df_base['cliente'].str.upper().str.strip()

    parts = []
    mask_vals = mask.values
    for col_idx, mes_ts in date_cols.items():
        vals = pd.to_numeric(df_data.iloc[:, col_idx].values, errors='coerce').astype(float)
        tmp = df_base.copy()
        tmp['mes_ts']    = mes_ts
        tmp['mes_key']   = _mes_key(mes_ts)
        tmp['mes_label'] = _mes_label(mes_ts)
        tmp['forecast']  = vals[mask_vals]
        tmp['forecast']  = tmp['forecast'].fillna(0)
        parts.append(tmp)

    df_fc = pd.concat(parts, ignore_index=True)
    log.info("Forecast: %d filas, %d meses, %d SKUs, %d clientes",
             len(df_fc), len(date_cols), df_fc['sku'].nunique(), df_fc['cliente_key'].nunique())
    return df_fc


def _read_venta_real(src: Union[str, io.BytesIO], ultimo_mes: Optional[pd.Timestamp]) -> pd.DataFrame:
    """
    Lee hoja 'S&OP'. Toma solo columnas de UNIDADES (antes de 'Precio venta') ≤ ultimo_mes.
    Retorna DataFrame largo: cliente_key, cliente, sku, mes_ts, mes_key, mes_label, venta_real
    """
    df_raw = pd.read_excel(src, sheet_name='S&OP', header=None, dtype=object)
    header_row = df_raw.iloc[2]
    id_map = _map_id_cols(header_row)

    # Separador Precio venta
    precio_idx = next(
        (idx for idx, val in enumerate(header_row)
         if isinstance(val, str) and 'PRECIO' in val.strip().upper()),
        None
    )

    # Columnas de UNIDADES (antes de Precio venta y ≤ ultimo_mes)
    date_cols = {}
    for idx, val in enumerate(header_row):
        if precio_idx is not None and idx >= precio_idx:
            break
        if isinstance(val, datetime):
            ts = pd.Timestamp(val).replace(day=1)
            if ultimo_mes is None or ts <= ultimo_mes:
                date_cols[idx] = ts

    df_data = df_raw.iloc[3:].reset_index(drop=True)

    def _col(field):
        if field not in id_map:
            return pd.Series([''] * len(df_data), dtype=object)
        return df_data.iloc[:, id_map[field]]

    df_base = pd.DataFrame({
        'cliente':     _col('cliente').apply(_norm_str),
        'sku':         _col('sku').apply(_norm_sku),
        'descripcion': _col('descripcion').apply(_norm_str),
        'ranking':     _col('ranking').apply(_norm_str),
        'categoria':   _col('categoria').apply(_norm_str),
    })
    mask = df_base['sku'].notna() & (df_base['sku'] != '') & (df_base['sku'].str.upper() != 'NAN')
    df_base = df_base[mask].copy()
    df_base['cliente_key'] = df_base['cliente'].str.upper().str.strip()

    parts = []
    mask_vals = mask.values
    for col_idx, mes_ts in date_cols.items():
        vals = pd.to_numeric(df_data.iloc[:, col_idx].values, errors='coerce').astype(float)
        tmp = df_base.copy()
        tmp['mes_ts']     = mes_ts
        tmp['mes_key']    = _mes_key(mes_ts)
        tmp['mes_label']  = _mes_label(mes_ts)
        tmp['venta_real'] = vals[mask_vals]
        tmp['venta_real'] = tmp['venta_real'].fillna(0)
        parts.append(tmp)

    df_vr = pd.concat(parts, ignore_index=True)
    log.info("Venta real: %d filas, %d meses, %d SKUs, %d clientes",
             len(df_vr), len(date_cols), df_vr['sku'].nunique(), df_vr['cliente_key'].nunique())
    return df_vr


# ══════════════════════════════════════════════════════════════════
#  PROCESAMIENTO PRINCIPAL
# ══════════════════════════════════════════════════════════════════

def _build_result(df_fc: pd.DataFrame, df_vr: pd.DataFrame,
                  ultimo_mes: Optional[pd.Timestamp],
                  fc_name: str, sop_name: str) -> dict:
    """Merge, calcula FA y construye todas las agregaciones."""

    agg_fc = df_fc.groupby(['cliente_key', 'sku', 'mes_key', 'mes_ts', 'mes_label']).agg(
        forecast    = ('forecast',    'sum'),
        descripcion = ('descripcion', 'first'),
        cliente     = ('cliente',     'first'),
        ranking     = ('ranking',     'first'),
        categoria   = ('categoria',   'first'),
        marca       = ('marca',       'first'),
    ).reset_index()

    agg_vr = df_vr.groupby(['cliente_key', 'sku', 'mes_key']).agg(
        venta_real = ('venta_real', 'sum'),
    ).reset_index()

    df = pd.merge(agg_fc, agg_vr, on=['cliente_key', 'sku', 'mes_key'], how='inner')

    if df.empty:
        fc_meses = sorted(df_fc['mes_key'].unique().tolist())
        vr_meses = sorted(df_vr['mes_key'].unique().tolist())
        return {
            'error': (
                f"Sin meses en común entre Forecast ({fc_meses}) "
                f"y Venta Real ({vr_meses})."
            ),
            **_empty_result(fc_name, sop_name),
        }

    # Normalizar cliente (usar cliente_key = uppercase)
    df['cliente'] = df['cliente_key']

    # Filtro de ranking: solo códigos A y B (se excluyen Z, I&O, C, E, N, etc.)
    df = df[df['ranking'].isin(['A', 'B'])].copy()
    if df.empty:
        return {
            'error': "Sin datos con ranking A o B para calcular Forecast Accuracy.",
            **_empty_result(fc_name, sop_name),
        }

    # Filtro de clientes visibles en el visor
    df = df[df['cliente'].isin(CLIENTES_VISIBLES)].copy()
    if df.empty:
        return {
            'error': "Sin datos para los clientes habilitados en el visor de Forecast Accuracy.",
            **_empty_result(fc_name, sop_name),
        }

    # FA
    df['fa']        = compute_fa_series(df, 'forecast', 'venta_real')
    df['error_abs'] = (df['venta_real'] - df['forecast']).abs()
    df['mes_ts']    = pd.to_datetime(df['mes_ts'])
    df = df.sort_values('mes_ts').reset_index(drop=True)

    meses_ordered = sorted(df['mes_key'].unique().tolist())
    mes_labels    = df.drop_duplicates('mes_key').set_index('mes_key')['mes_label'].to_dict()
    clientes      = sorted(df['cliente'].unique().tolist())
    skus          = sorted(df['sku'].unique().tolist())

    log.info("FA result: %d filas, %d meses, %d SKUs, %d clientes",
             len(df), len(meses_ordered), len(skus), len(clientes))

    return {
        'kpis':              _build_kpis(df, meses_ordered, mes_labels),
        'trend':             _build_trend(df, meses_ordered, mes_labels),
        'sku_table':         _build_sku_table(df, meses_ordered),
        'cliente_sku_table': _build_cliente_sku_table(df),
        'cliente_table':     _build_cliente_table(df),
        'cliente_sku_detail':_build_cliente_sku_detail(df),
        'ranking':           _build_ranking(df),
        'heatmap':           _build_heatmap(df, clientes, meses_ordered, mes_labels),
        'raw':               _build_raw(df),
        'clientes':          clientes,
        'meses':             [{'key': k, 'label': mes_labels[k]} for k in meses_ordered],
        'skus':              skus,
        'archivo_forecast':  fc_name,
        'archivo_venta':     sop_name,
        'ultimo_mes':        _mes_label(ultimo_mes) if ultimo_mes else '—',
        'updated_at':        datetime.now().strftime('%d-%b-%Y %H:%M'),
        'error':             None,
    }


def _empty_result(fc_name='—', sop_name='—'):
    return {
        'kpis': {}, 'trend': [], 'sku_table': [], 'cliente_sku_table': [],
        'ranking': {}, 'heatmap': {}, 'clientes': [], 'meses': [], 'skus': [],
        'archivo_forecast': fc_name, 'archivo_venta': sop_name,
        'ultimo_mes': '—', 'updated_at': None,
    }


# ══════════════════════════════════════════════════════════════════
#  BUILDERS
# ══════════════════════════════════════════════════════════════════

def _build_kpis(df: pd.DataFrame, meses: list, labels: dict) -> dict:
    if not meses:
        return {}
    ultimo   = meses[-1]
    anterior = meses[-2] if len(meses) >= 2 else None

    df_ult = df[df['mes_key'] == ultimo]
    fa_ult = fa_from_df(df_ult, 'forecast', 'venta_real') if not df_ult.empty else None

    fa_ant = None
    if anterior:
        df_ant = df[df['mes_key'] == anterior]
        fa_ant = fa_from_df(df_ant, 'forecast', 'venta_real') if not df_ant.empty else None

    variacion = round(fa_ult - fa_ant, 1) if (fa_ult is not None and fa_ant is not None) else None
    tendencia = ('up' if variacion and variacion > 0 else
                 'down' if variacion and variacion < 0 else 'flat')
    fa_total  = fa_from_df(df, 'forecast', 'venta_real') if not df.empty else None

    return {
        'fa_ultimo_mes': fa_ult,
        'mes_label':     labels.get(ultimo, ultimo),
        'fa_mes_ant':    fa_ant,
        'mes_ant_label': labels.get(anterior, '') if anterior else None,
        'variacion':     variacion,
        'tendencia':     tendencia,
        'fa_total':      fa_total,
        'n_meses':       len(meses),
        'color':         fa_semaforo(fa_ult) if fa_ult is not None else 'red',
    }


def _build_trend(df: pd.DataFrame, meses: list, labels: dict) -> list:
    rows = []
    for mes_key in meses:
        dg = df[df['mes_key'] == mes_key]
        if dg.empty:
            continue
        fa = fa_from_df(dg, 'forecast', 'venta_real')
        rows.append({
            'mes':      mes_key,
            'label':    labels.get(mes_key, mes_key),
            'fa':       fa,
            'color':    fa_semaforo(fa),
            'forecast': float(dg['forecast'].sum()),
            'venta':    float(dg['venta_real'].sum()),
        })
    return rows


def _build_sku_table(df: pd.DataFrame, meses_ordered: list) -> list:
    N_TREND = 6
    ultimos = meses_ordered[-N_TREND:]
    rows = []
    for sku, grp in df.groupby('sku', sort=True):
        fa_total = fa_from_df(grp, 'forecast', 'venta_real')
        desc  = grp['descripcion'].mode()[0] if not grp['descripcion'].empty else ''
        rank  = grp['ranking'].mode()[0]  if 'ranking'  in grp.columns else ''
        cat   = grp['categoria'].mode()[0] if 'categoria' in grp.columns else ''
        trend = []
        for mes_key in ultimos:
            dg = grp[grp['mes_key'] == mes_key]
            trend.append(fa_from_df(dg, 'forecast', 'venta_real') if not dg.empty else None)
        rows.append({
            'sku': str(sku), 'descripcion': str(desc), 'ranking': str(rank), 'categoria': str(cat),
            'n_clientes': int(grp['cliente'].nunique()),
            'forecast': round(float(grp['forecast'].sum()), 0),
            'venta':    round(float(grp['venta_real'].sum()), 0),
            'fa':       fa_total,
            'fa_color': fa_chip_class(fa_total),
            'trend':    trend,
        })
    rows.sort(key=lambda r: (r['fa'] or 0))
    return rows


def _build_cliente_table(df: pd.DataFrame) -> list:
    """Resumen agregado por cliente (suma todos los SKU y meses)."""
    rows = []
    for cliente, grp in df.groupby('cliente', sort=True):
        fa = fa_from_df(grp, 'forecast', 'venta_real')
        rows.append({
            'cliente':   str(cliente),
            'n_skus':    int(grp['sku'].nunique()),
            'forecast':  round(float(grp['forecast'].sum()), 0),
            'venta':     round(float(grp['venta_real'].sum()), 0),
            'fa':        fa,
            'fa_color':  fa_chip_class(fa),
        })
    rows.sort(key=lambda r: (r['fa'] or 0))
    return rows


def _build_cliente_sku_detail(df: pd.DataFrame) -> list:
    """Detalle agregado por par Cliente-SKU (suma todos los meses) — usado para las tablas expandibles."""
    rows = []
    for (cliente, sku), grp in df.groupby(['cliente', 'sku'], sort=False):
        fa   = fa_from_df(grp, 'forecast', 'venta_real')
        desc = grp['descripcion'].mode()[0] if not grp['descripcion'].empty else ''
        rows.append({
            'cliente':     str(cliente),
            'sku':         str(sku),
            'descripcion': str(desc),
            'n_meses':     int(grp['mes_key'].nunique()),
            'forecast':    round(float(grp['forecast'].sum()), 0),
            'venta':       round(float(grp['venta_real'].sum()), 0),
            'fa':          fa,
            'fa_color':    fa_chip_class(fa),
        })
    rows.sort(key=lambda r: (r['cliente'], r['sku']))
    return rows


def _build_cliente_sku_table(df: pd.DataFrame) -> list:
    rows = []
    for (cliente, sku, mes_key), grp in df.groupby(['cliente', 'sku', 'mes_key'], sort=False):
        fa   = fa_from_df(grp, 'forecast', 'venta_real')
        desc = grp['descripcion'].mode()[0] if not grp['descripcion'].empty else ''
        ml   = grp['mes_label'].iloc[0] if 'mes_label' in grp.columns else ''
        rows.append({
            'cliente': str(cliente), 'sku': str(sku), 'descripcion': str(desc),
            'mes': str(mes_key), 'mes_label': str(ml),
            'forecast': round(float(grp['forecast'].sum()), 0),
            'venta':    round(float(grp['venta_real'].sum()), 0),
            'fa':       fa, 'fa_color': fa_chip_class(fa),
        })
    rows.sort(key=lambda r: (r['cliente'], r['mes'], r['sku']))
    return rows


def _build_ranking(df: pd.DataFrame, top_n: int = 10) -> dict:
    if df.empty:
        return {'mejores': [], 'peores': []}
    ultimo_mes = df['mes_key'].max()
    df_ult = df[df['mes_key'] == ultimo_mes]
    if df_ult.empty:
        df_ult = df
    sku_fa = []
    for sku, grp in df_ult.groupby('sku'):
        fa   = fa_from_df(grp, 'forecast', 'venta_real')
        desc = grp['descripcion'].mode()[0] if not grp['descripcion'].empty else ''
        clis = ', '.join(sorted(grp['cliente'].unique().tolist())[:3])
        sku_fa.append({'sku': str(sku), 'descripcion': str(desc),
                       'clientes': clis, 'fa': fa, 'fa_color': fa_chip_class(fa)})
    sku_fa.sort(key=lambda x: (x['fa'] or 0))
    return {'peores': sku_fa[:top_n], 'mejores': list(reversed(sku_fa[-top_n:]))}


def _build_raw(df: pd.DataFrame) -> list:
    """
    Datos a nivel cliente-SKU-mes (post filtro ranking A/B) para que el frontend
    pueda recalcular todos los indicadores según el rango de meses seleccionado.
    """
    out = df[['cliente', 'sku', 'descripcion', 'mes_key', 'mes_label', 'forecast', 'venta_real']].copy()
    out = out.rename(columns={'venta_real': 'venta'})
    out['forecast'] = out['forecast'].round(2)
    out['venta']    = out['venta'].round(2)
    return out.to_dict('records')


def _build_heatmap(df: pd.DataFrame, clientes: list, meses_ordered: list, mes_labels: dict) -> dict:
    matrix = []
    for cliente in clientes:
        row_vals = []
        for mes_key in meses_ordered:
            dg = df[(df['cliente'] == cliente) & (df['mes_key'] == mes_key)]
            row_vals.append(fa_from_df(dg, 'forecast', 'venta_real') if not dg.empty else None)
        matrix.append({
            'cliente': cliente,
            'values':  row_vals,
            'colors':  [fa_heatmap_color(v) if v is not None else '#f5f5f5' for v in row_vals],
        })
    return {'meses': [mes_labels.get(k, k) for k in meses_ordered], 'matrix': matrix}


# ══════════════════════════════════════════════════════════════════
#  INTERFAZ PÚBLICA
# ══════════════════════════════════════════════════════════════════

def get_fa_data(force: bool = False) -> dict:
    """Retorna datos FA procesados (desde caché si disponible)."""
    global _fa_cache
    if _fa_cache is not None and not force:
        return _fa_cache

    # 1 — Intentar SharePoint via link compartido
    try:
        fc_bytes, fc_name, sop_bytes, sop_name = _download_fa_from_sharepoint()
        ultimo_mes = _extract_ultimo_mes(sop_name)
        df_fc = _read_forecast(io.BytesIO(fc_bytes))
        df_vr = _read_venta_real(io.BytesIO(sop_bytes), ultimo_mes)
        result = _build_result(df_fc, df_vr, ultimo_mes, fc_name, sop_name)
        result['source'] = 'sharepoint'
        _fa_cache = result
        log.info("FA cargada desde SharePoint")
        return result
    except Exception as e_sp:
        log.warning("SharePoint no disponible para FA (%s); intentando carpeta local…", e_sp)

    # 2 — Fallback: carpeta local
    folder = Config.FA_DATA_FOLDER
    if not folder or not os.path.isdir(folder):
        err = {
            'error': f"No se pudo acceder a SharePoint ({e_sp}) y la carpeta local no está disponible.",
            **_empty_result(),
        }
        _fa_cache = err
        return err

    try:
        fc_path, sop_path = _find_local_files(folder)
        ultimo_mes = _extract_ultimo_mes(sop_path)
        df_fc = _read_forecast(fc_path)
        df_vr = _read_venta_real(sop_path, ultimo_mes)
        result = _build_result(df_fc, df_vr, ultimo_mes,
                               os.path.basename(fc_path), os.path.basename(sop_path))
        result['source'] = 'local'
        _fa_cache = result
        log.info("FA cargada desde carpeta local")
        return result
    except Exception as e_local:
        log.exception("Error cargando FA local: %s", e_local)
        err = {'error': str(e_local), **_empty_result()}
        _fa_cache = err
        return err


def refresh_fa_data() -> dict:
    """Fuerza recarga. Llamada por el botón 'Actualizar información'."""
    global _fa_cache
    _fa_cache = None
    return get_fa_data(force=True)


def clear_fa_cache():
    global _fa_cache
    _fa_cache = None
