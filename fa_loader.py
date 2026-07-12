"""
fa_loader.py — SPOT ESSENCE Forecast Accuracy
Maneja los archivos reales del proceso S&OP:
  • "Base Forecast Acuraccy.xlsx"  → hoja "Forecast Cliente": forecast cliente-SKU-mes (FEB-JUL 2026)
  • "(NN) S&OP <MES> <AÑO> - CIERRE.xlsx" → hoja "S&OP": venta real unidades hasta último mes cerrado

Estructura de ambos archivos:
  Fila 0: vacía / meta
  Fila 1: totales agregados
  Fila 2: ENCABEZADOS REALES (Razón Social, SKU, DESCRIPCIÓN, …, columnas datetime)
  Fila 3+: datos
"""
import logging
import os
import re
from datetime import datetime
from typing import Optional

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
    """Normaliza un valor a string limpio (strip + upper)."""
    if v is None:
        return ''
    s = str(v).strip()
    if s.lower() in ('nan', 'none', ''):
        return ''
    return s


def _norm_sku(v) -> str:
    """Normaliza SKU: strip, sin .0 de float."""
    s = _norm_str(v)
    if s.endswith('.0'):
        s = s[:-2]
    return s


def _norm_cliente(v) -> str:
    """Normaliza nombre de cliente para merge (upper + strip)."""
    return _norm_str(v).upper()


# ══════════════════════════════════════════════════════════════════
#  DETECCIÓN DE ARCHIVOS
# ══════════════════════════════════════════════════════════════════

_KW_FORECAST = {'forecast', 'base forecast'}
_KW_SOP      = {'s&op', 'sop', 'cierre'}


def _find_files(folder: str) -> tuple[Optional[str], Optional[str]]:
    """Retorna (path_forecast, path_sop)."""
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Carpeta no encontrada: {folder}")

    files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(('.xlsx', '.xls')) and not f.startswith('~$')
    ]
    if not files:
        raise FileNotFoundError(f"No se encontraron archivos Excel en: {folder}")

    path_forecast = path_sop = None
    for p in files:
        name = os.path.basename(p).lower()
        if any(kw in name for kw in _KW_FORECAST):
            path_forecast = p
        elif any(kw in name for kw in _KW_SOP):
            path_sop = p

    if path_forecast is None or path_sop is None:
        # Fallback: hay exactamente 2 archivos
        if len(files) == 2:
            # El "forecast" suele tener menos columnas / ser más pequeño
            path_forecast, path_sop = sorted(files)

    return path_forecast, path_sop


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
#  LECTURA DE ARCHIVOS
# ══════════════════════════════════════════════════════════════════

def _map_id_cols(header_row: pd.Series) -> dict:
    """
    Detecta índices de columnas identificadoras a partir de la fila de encabezados.
    Retorna dict nombre→índice.
    """
    id_map = {}
    for idx, val in enumerate(header_row):
        if not isinstance(val, str):
            continue
        v = val.strip().upper()
        # Razón Social / cliente
        if 'RAZ' in v and ('SOCIAL' in v or 'N SOCIAL' in v):
            id_map['cliente'] = idx
        elif 'SKU' == v:
            id_map['sku'] = idx
        elif 'DESCRIP' in v:
            id_map['descripcion'] = idx
        elif 'RANKING' in v:
            id_map['ranking'] = idx
        elif 'CATEGOR' in v:
            id_map['categoria'] = idx
        elif 'MARCA' in v:
            id_map['marca'] = idx
        elif 'CLASIFICACI' in v:
            id_map['clasificacion'] = idx
        elif 'AROMA' in v:
            id_map['aroma'] = idx
    return id_map


def _read_forecast(path: str) -> pd.DataFrame:
    """
    Lee "Base Forecast Acuraccy.xlsx", hoja 'Forecast Cliente'.
    Retorna DataFrame largo: cliente_key, cliente, sku, descripcion, mes_ts, mes_key, mes_label, forecast
    """
    df_raw = pd.read_excel(path, sheet_name='Forecast Cliente', header=None, dtype=object)

    header_row = df_raw.iloc[2]  # fila real de encabezados
    id_map = _map_id_cols(header_row)

    # Columnas de fecha = forecast por mes
    date_cols = {}  # col_idx → pd.Timestamp
    for idx, val in enumerate(header_row):
        if isinstance(val, datetime):
            date_cols[idx] = pd.Timestamp(val).replace(day=1)

    df_data = df_raw.iloc[3:].reset_index(drop=True)

    # Construir base
    def _col(field):
        return df_data.iloc[:, id_map[field]] if field in id_map else pd.Series([''] * len(df_data))

    df_base = pd.DataFrame({
        'cliente':     _col('cliente').apply(_norm_str),
        'sku':         _col('sku').apply(_norm_sku),
        'descripcion': _col('descripcion').apply(_norm_str),
        'ranking':     _col('ranking').apply(_norm_str) if 'ranking' in id_map else '',
        'categoria':   _col('categoria').apply(_norm_str) if 'categoria' in id_map else '',
        'marca':       _col('marca').apply(_norm_str) if 'marca' in id_map else '',
    })

    # Filtrar filas válidas (sku presente)
    mask = df_base['sku'].notna() & (df_base['sku'] != '') & (df_base['sku'] != 'NAN')
    df_base = df_base[mask].copy()
    df_base['cliente_key'] = df_base['cliente'].str.upper().str.strip()

    # Melt: un row por (cliente, sku, mes)
    parts = []
    for col_idx, mes_ts in date_cols.items():
        vals = pd.to_numeric(df_data.iloc[:, col_idx].values, errors='coerce').astype(float)
        tmp = df_base.copy()
        tmp['mes_ts']   = mes_ts
        tmp['mes_key']  = _mes_key(mes_ts)
        tmp['mes_label'] = _mes_label(mes_ts)
        tmp['forecast'] = vals[mask.values]
        tmp['forecast'] = tmp['forecast'].fillna(0)
        parts.append(tmp)

    df_fc = pd.concat(parts, ignore_index=True)
    log.info("Forecast leído: %d filas, %d meses, %d SKUs únicos, %d clientes",
             len(df_fc), len(date_cols), df_fc['sku'].nunique(), df_fc['cliente'].nunique())
    return df_fc


def _read_venta_real(path: str, ultimo_mes: Optional[pd.Timestamp]) -> pd.DataFrame:
    """
    Lee el archivo S&OP, hoja 'S&OP'.
    Solo toma las columnas de UNIDADES (primer bloque de fechas, antes de 'Precio venta')
    y filtra los meses ≤ ultimo_mes.
    Retorna DataFrame largo: cliente_key, cliente, sku, mes_ts, mes_key, mes_label, venta_real
    """
    df_raw = pd.read_excel(path, sheet_name='S&OP', header=None, dtype=object)

    header_row = df_raw.iloc[2]
    id_map = _map_id_cols(header_row)

    # Encontrar columna 'Precio venta' para separar sección UN vs $
    precio_venta_idx = None
    for idx, val in enumerate(header_row):
        if isinstance(val, str) and 'PRECIO' in val.strip().upper():
            precio_venta_idx = idx
            break

    # Columnas de fecha de UNIDADES (solo antes de Precio venta y ≤ ultimo_mes)
    date_cols = {}
    for idx, val in enumerate(header_row):
        if precio_venta_idx is not None and idx >= precio_venta_idx:
            break
        if isinstance(val, datetime):
            ts = pd.Timestamp(val).replace(day=1)
            if ultimo_mes is None or ts <= ultimo_mes:
                date_cols[idx] = ts

    df_data = df_raw.iloc[3:].reset_index(drop=True)

    def _col(field):
        return df_data.iloc[:, id_map[field]] if field in id_map else pd.Series([''] * len(df_data))

    df_base = pd.DataFrame({
        'cliente':     _col('cliente').apply(_norm_str),
        'sku':         _col('sku').apply(_norm_sku),
        'descripcion': _col('descripcion').apply(_norm_str) if 'descripcion' in id_map else '',
        'ranking':     _col('ranking').apply(_norm_str) if 'ranking' in id_map else '',
        'categoria':   _col('categoria').apply(_norm_str) if 'categoria' in id_map else '',
    })

    mask = df_base['sku'].notna() & (df_base['sku'] != '') & (df_base['sku'] != 'NAN')
    df_base = df_base[mask].copy()
    df_base['cliente_key'] = df_base['cliente'].str.upper().str.strip()

    parts = []
    for col_idx, mes_ts in date_cols.items():
        vals = pd.to_numeric(df_data.iloc[:, col_idx].values, errors='coerce').astype(float)
        tmp = df_base.copy()
        tmp['mes_ts']    = mes_ts
        tmp['mes_key']   = _mes_key(mes_ts)
        tmp['mes_label'] = _mes_label(mes_ts)
        tmp['venta_real'] = vals[mask.values]
        tmp['venta_real'] = tmp['venta_real'].fillna(0)
        parts.append(tmp)

    df_vr = pd.concat(parts, ignore_index=True)
    log.info("Venta real leída: %d filas, %d meses, %d SKUs únicos, %d clientes",
             len(df_vr), len(date_cols), df_vr['sku'].nunique(), df_vr['cliente'].nunique())
    return df_vr


# ══════════════════════════════════════════════════════════════════
#  PROCESAMIENTO
# ══════════════════════════════════════════════════════════════════

def _process(path_forecast: str, path_sop: str) -> dict:
    ultimo_mes = _extract_ultimo_mes(path_sop)
    log.info("Último mes cerrado: %s", ultimo_mes)

    df_fc = _read_forecast(path_forecast)
    df_vr = _read_venta_real(path_sop, ultimo_mes)

    # Agregar por (cliente_key, sku, mes_key) antes del merge
    agg_fc = df_fc.groupby(['cliente_key', 'sku', 'mes_key', 'mes_ts', 'mes_label']).agg(
        forecast    = ('forecast', 'sum'),
        descripcion = ('descripcion', 'first'),
        cliente     = ('cliente', 'first'),
        ranking     = ('ranking', 'first'),
        categoria   = ('categoria', 'first'),
        marca       = ('marca', 'first'),
    ).reset_index()

    agg_vr = df_vr.groupby(['cliente_key', 'sku', 'mes_key']).agg(
        venta_real = ('venta_real', 'sum'),
    ).reset_index()

    # Merge por (cliente_key, sku, mes_key)
    df = pd.merge(agg_fc, agg_vr, on=['cliente_key', 'sku', 'mes_key'], how='inner')

    if df.empty:
        fc_meses = sorted(df_fc['mes_key'].unique())
        vr_meses = sorted(df_vr['mes_key'].unique())
        return {
            'error': (
                f"No hay meses en común entre Forecast ({fc_meses}) "
                f"y Venta Real ({vr_meses}). "
                f"Verifica que el archivo S&OP corresponda al período del Forecast."
            ),
            **_empty_result(path_forecast, path_sop),
        }

    # Normalizar nombre de cliente: usar cliente_key (uppercase) como nombre canónico
    df['cliente'] = df['cliente_key']

    # FA fila a fila
    df['fa']        = compute_fa_series(df, 'forecast', 'venta_real')
    df['error_abs'] = (df['venta_real'] - df['forecast']).abs()
    df['mes_ts']    = pd.to_datetime(df['mes_ts'])
    df = df.sort_values('mes_ts').reset_index(drop=True)

    meses_ordered = sorted(df['mes_key'].unique())
    mes_labels    = df.drop_duplicates('mes_key').set_index('mes_key')['mes_label'].to_dict()
    clientes      = sorted(df['cliente'].unique())
    skus          = sorted(df['sku'].unique())

    log.info("FA procesada: %d filas, %d meses, %d SKUs, %d clientes",
             len(df), len(meses_ordered), len(skus), len(clientes))

    return {
        'kpis':              _build_kpis(df, meses_ordered, mes_labels),
        'trend':             _build_trend(df, meses_ordered, mes_labels),
        'sku_table':         _build_sku_table(df, meses_ordered),
        'cliente_sku_table': _build_cliente_sku_table(df),
        'ranking':           _build_ranking(df),
        'heatmap':           _build_heatmap(df, clientes, meses_ordered, mes_labels),
        'clientes':          clientes,
        'meses':             [{'key': k, 'label': mes_labels[k]} for k in meses_ordered],
        'skus':              skus,
        'archivo_forecast':  os.path.basename(path_forecast),
        'archivo_venta':     os.path.basename(path_sop),
        'ultimo_mes':        _mes_label(ultimo_mes) if ultimo_mes else '—',
        'updated_at':        datetime.now().strftime('%d-%b-%Y %H:%M'),
        'error':             None,
    }


def _empty_result(pf='', ps=''):
    return {
        'kpis': {}, 'trend': [], 'sku_table': [], 'cliente_sku_table': [],
        'ranking': {}, 'heatmap': {}, 'clientes': [], 'meses': [], 'skus': [],
        'archivo_forecast': os.path.basename(pf) if pf else '—',
        'archivo_venta': os.path.basename(ps) if ps else '—',
        'ultimo_mes': '—', 'updated_at': None,
    }


# ══════════════════════════════════════════════════════════════════
#  BUILDERS
# ══════════════════════════════════════════════════════════════════

def _build_kpis(df: pd.DataFrame, meses: list, labels: dict) -> dict:
    if not meses:
        return {}
    ultimo  = meses[-1]
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

    fa_total = fa_from_df(df, 'forecast', 'venta_real') if not df.empty else None

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
        desc     = grp['descripcion'].mode()[0] if not grp['descripcion'].empty else ''
        rank     = grp['ranking'].mode()[0] if 'ranking' in grp.columns and not grp['ranking'].empty else ''
        cat      = grp['categoria'].mode()[0] if 'categoria' in grp.columns and not grp['categoria'].empty else ''

        trend_vals = []
        for mes_key in ultimos:
            dg = grp[grp['mes_key'] == mes_key]
            trend_vals.append(fa_from_df(dg, 'forecast', 'venta_real') if not dg.empty else None)

        rows.append({
            'sku':         str(sku),
            'descripcion': str(desc),
            'ranking':     str(rank),
            'categoria':   str(cat),
            'forecast':    round(float(grp['forecast'].sum()), 0),
            'venta':       round(float(grp['venta_real'].sum()), 0),
            'fa':          fa_total,
            'fa_color':    fa_chip_class(fa_total),
            'trend':       trend_vals,
        })
    rows.sort(key=lambda r: (r['fa'] or 0))
    return rows


def _build_cliente_sku_table(df: pd.DataFrame) -> list:
    rows = []
    for (cliente, sku, mes_key), grp in df.groupby(['cliente', 'sku', 'mes_key'], sort=False):
        fa   = fa_from_df(grp, 'forecast', 'venta_real')
        desc = grp['descripcion'].mode()[0] if not grp['descripcion'].empty else ''
        ml   = grp['mes_label'].iloc[0] if 'mes_label' in grp.columns else ''
        rows.append({
            'cliente':     str(cliente),
            'sku':         str(sku),
            'descripcion': str(desc),
            'mes':         str(mes_key),
            'mes_label':   str(ml),
            'forecast':    round(float(grp['forecast'].sum()), 0),
            'venta':       round(float(grp['venta_real'].sum()), 0),
            'fa':          fa,
            'fa_color':    fa_chip_class(fa),
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
        sku_fa.append({
            'sku': str(sku), 'descripcion': str(desc),
            'clientes': clis, 'fa': fa, 'fa_color': fa_chip_class(fa),
        })

    sku_fa.sort(key=lambda x: (x['fa'] or 0))
    return {
        'peores':  sku_fa[:top_n],
        'mejores': list(reversed(sku_fa[-top_n:])),
    }


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
    return {
        'meses':  [mes_labels.get(k, k) for k in meses_ordered],
        'matrix': matrix,
    }


# ══════════════════════════════════════════════════════════════════
#  INTERFAZ PÚBLICA
# ══════════════════════════════════════════════════════════════════

def get_fa_data(force: bool = False) -> dict:
    """Retorna datos FA procesados (desde caché si disponible)."""
    global _fa_cache
    if _fa_cache is not None and not force:
        return _fa_cache

    folder = Config.FA_DATA_FOLDER
    if not folder:
        err = {'error': 'FA_DATA_FOLDER no está configurada.', **_empty_result()}
        return err

    try:
        path_fc, path_sop = _find_files(folder)
        if path_fc is None:
            raise FileNotFoundError('No se encontró el archivo de Forecast en la carpeta.')
        if path_sop is None:
            raise FileNotFoundError('No se encontró el archivo S&OP en la carpeta.')

        result = _process(path_fc, path_sop)
        _fa_cache = result
        return result

    except Exception as e:
        log.exception("Error cargando FA data: %s", e)
        err = {'error': str(e), **_empty_result()}
        _fa_cache = err
        return err


def refresh_fa_data() -> dict:
    """Fuerza recarga desde disco. Llamada por el botón 'Actualizar información'."""
    global _fa_cache
    _fa_cache = None
    return get_fa_data(force=True)


def clear_fa_cache():
    global _fa_cache
    _fa_cache = None
