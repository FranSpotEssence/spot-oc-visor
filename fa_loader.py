"""
fa_loader.py — SPOT ESSENCE Forecast Accuracy
Lee, combina y procesa los archivos de Forecast y Venta Real.
Estructura modular: lectura → merge → cálculo → agregación → caché.
"""
import io
import logging
import os
from datetime import datetime
from typing import Optional

import numpy as np
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


# ══════════════════════════════════════════════════════════════════
#  DETECCIÓN Y LECTURA DE ARCHIVOS
# ══════════════════════════════════════════════════════════════════

_KW_FORECAST = {"forecast", "fcst", "pronostico", "pronóstico", "proyeccion"}
_KW_VENTA    = {"venta", "real", "actual", "sales", "revenue"}


def _find_files(folder: str) -> tuple[Optional[str], Optional[str]]:
    """
    Detecta los archivos de forecast y venta en la carpeta.
    Retorna (path_forecast, path_venta).
    Usa keywords en el nombre del archivo para identificar cuál es cuál.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Carpeta no encontrada: {folder}")

    files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith((".xlsx", ".xls", ".csv")) and not f.startswith("~$")
    ]

    if len(files) == 0:
        raise FileNotFoundError(f"No se encontraron archivos Excel/CSV en: {folder}")

    # Intentar detectar por nombre
    path_forecast = path_venta = None
    for p in files:
        name_lower = os.path.basename(p).lower()
        if any(kw in name_lower for kw in _KW_FORECAST):
            path_forecast = p
        elif any(kw in name_lower for kw in _KW_VENTA):
            path_venta = p

    # Fallback: si no se detectó por nombre, usar orden alfabético
    if path_forecast is None and path_venta is None:
        files_sorted = sorted(files)
        if len(files_sorted) >= 2:
            path_forecast, path_venta = files_sorted[0], files_sorted[1]
        elif len(files_sorted) == 1:
            path_forecast = files_sorted[0]
    elif path_forecast is None and path_venta is not None:
        others = [p for p in files if p != path_venta]
        path_forecast = others[0] if others else None
    elif path_venta is None and path_forecast is not None:
        others = [p for p in files if p != path_forecast]
        path_venta = others[0] if others else None

    return path_forecast, path_venta


def _read_file(path: str) -> pd.DataFrame:
    """Lee un archivo Excel o CSV y retorna un DataFrame."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path, encoding="utf-8-sig")
    else:
        return pd.read_excel(path, engine="openpyxl")


# ══════════════════════════════════════════════════════════════════
#  NORMALIZACIÓN Y DETECCIÓN DE COLUMNAS
# ══════════════════════════════════════════════════════════════════

_COL_KEYWORDS = {
    "mes":         {"mes", "month", "fecha", "periodo", "period", "date"},
    "cliente":     {"cliente", "client", "customer", "cuenta", "canal", "canal_venta"},
    "sku":         {"sku", "cod", "codigo", "código", "ean", "item", "producto_cod", "ref"},
    "descripcion": {"descripcion", "descripción", "nombre", "producto", "name", "desc", "detalle"},
    "forecast":    {"forecast", "fcst", "pronostico", "pronóstico", "proyeccion", "proyección"},
    "venta":       {"venta", "real", "actual", "sales", "venta_real", "revenue", "despacho"},
}

# Columnas configurables vía env vars (ej: FA_COL_MES=periodo)
_COL_ENV = {
    "mes":         os.getenv("FA_COL_MES",         ""),
    "cliente":     os.getenv("FA_COL_CLIENTE",      ""),
    "sku":         os.getenv("FA_COL_SKU",          ""),
    "descripcion": os.getenv("FA_COL_DESCRIPCION",  ""),
    "forecast":    os.getenv("FA_COL_FORECAST",     ""),
    "venta":       os.getenv("FA_COL_VENTA",        ""),
}


def _normalize(s: str) -> str:
    """Normaliza nombre de columna para comparación."""
    import unicodedata
    s = unicodedata.normalize("NFD", str(s).lower().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace(" ", "_")


def _detect_col(df: pd.DataFrame, field: str) -> Optional[str]:
    """Detecta qué columna del DataFrame corresponde al campo dado."""
    # 1. Env var explícita
    if _COL_ENV.get(field):
        explicit = _COL_ENV[field]
        if explicit in df.columns:
            return explicit

    # 2. Búsqueda por keywords normalizados
    keywords = _COL_KEYWORDS.get(field, set())
    for col in df.columns:
        norm = _normalize(col)
        if norm in keywords or any(kw in norm for kw in keywords):
            return col

    return None


def _map_columns(df: pd.DataFrame, fields: list[str]) -> dict[str, str]:
    """Mapea los campos requeridos a nombres de columna reales del DataFrame."""
    mapping = {}
    missing = []
    for field in fields:
        col = _detect_col(df, field)
        if col:
            mapping[field] = col
        else:
            missing.append(field)
    if missing:
        log.warning("Columnas no detectadas: %s. Columnas disponibles: %s", missing, list(df.columns))
    return mapping


# ══════════════════════════════════════════════════════════════════
#  NORMALIZACIÓN DE MES
# ══════════════════════════════════════════════════════════════════

_MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "ene": 1, "feb": 2, "mar": 3, "abr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}
_MESES_LABEL = {
    1: "ENE", 2: "FEB", 3: "MAR", 4: "ABR",
    5: "MAY", 6: "JUN", 7: "JUL", 8: "AGO",
    9: "SEP", 10: "OCT", 11: "NOV", 12: "DIC",
}


def _parse_mes(val) -> Optional[pd.Timestamp]:
    """Intenta convertir cualquier valor de mes a Timestamp (primer día del mes)."""
    if pd.isna(val) or val is None:
        return None
    # Ya es Timestamp
    if isinstance(val, (pd.Timestamp, datetime)):
        ts = pd.Timestamp(val)
        return ts.replace(day=1)
    s = str(val).strip().lower()
    # Formato "2026-01" o "2026-1"
    if len(s) >= 6 and "-" in s:
        parts = s.split("-")
        if len(parts) == 2:
            try:
                y, m = int(parts[0]), int(parts[1])
                if 2000 <= y <= 2099 and 1 <= m <= 12:
                    return pd.Timestamp(year=y, month=m, day=1)
            except ValueError:
                pass
    # Formato "01/2026" o "1/2026"
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            try:
                a, b = int(parts[0]), int(parts[1])
                if 2000 <= b <= 2099 and 1 <= a <= 12:
                    return pd.Timestamp(year=b, month=a, day=1)
                if 2000 <= a <= 2099 and 1 <= b <= 12:
                    return pd.Timestamp(year=a, month=b, day=1)
            except ValueError:
                pass
    # Formato "Enero 2026" o "enero-2026"
    for sep in [" ", "-", "_"]:
        parts = s.split(sep)
        if len(parts) >= 2:
            for p in parts:
                if p in _MESES_ES:
                    m = _MESES_ES[p]
                    for q in parts:
                        try:
                            y = int(q)
                            if 2000 <= y <= 2099:
                                return pd.Timestamp(year=y, month=m, day=1)
                        except ValueError:
                            pass
    # Último recurso: pandas
    try:
        return pd.to_datetime(val, dayfirst=True).replace(day=1)
    except Exception:
        return None


def _mes_label(ts: pd.Timestamp) -> str:
    return f"{_MESES_LABEL[ts.month]} {ts.year}"


def _mes_key(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m")


# ══════════════════════════════════════════════════════════════════
#  PROCESAMIENTO PRINCIPAL
# ══════════════════════════════════════════════════════════════════

def _process(df_forecast: pd.DataFrame, df_venta: pd.DataFrame,
             file_forecast: str, file_venta: str) -> dict:
    """
    Combina forecast y venta, calcula FA, genera todas las agregaciones.
    """
    COL_F = "forecast"
    COL_V = "venta"

    # ── Mapear columnas en cada archivo ──────────────────────────
    fields_common  = ["mes", "cliente", "sku", "descripcion"]
    fields_only_f  = ["forecast"]
    fields_only_v  = ["venta"]

    map_f = _map_columns(df_forecast, fields_common + fields_only_f)
    map_v = _map_columns(df_venta,    fields_common + fields_only_v)

    required_f = {"mes", "sku", COL_F}
    required_v = {"mes", "sku", COL_V}
    if not required_f.issubset(map_f):
        raise ValueError(f"Archivo Forecast: no se encontraron columnas {required_f - set(map_f)}. "
                         f"Columnas disponibles: {list(df_forecast.columns)}")
    if not required_v.issubset(map_v):
        raise ValueError(f"Archivo Venta: no se encontraron columnas {required_v - set(map_v)}. "
                         f"Columnas disponibles: {list(df_venta.columns)}")

    # ── Seleccionar y renombrar columnas ─────────────────────────
    def _extract(df, mapping, num_col):
        cols = {k: v for k, v in mapping.items() if k in df.columns or v in df.columns}
        rename = {v: k for k, v in cols.items()}
        sel = list(set(cols.values()))
        out = df[sel].copy().rename(columns=rename)
        # Normalizar mes
        out["mes_ts"] = out["mes"].apply(_parse_mes)
        out = out.dropna(subset=["mes_ts", "sku"])
        out["mes_ts"] = pd.to_datetime(out["mes_ts"])
        # Normalizar numérico
        out[num_col] = pd.to_numeric(out[num_col], errors="coerce").fillna(0)
        # Normalizar claves
        out["sku"]    = out["sku"].astype(str).str.strip()
        if "cliente" in out.columns:
            out["cliente"] = out["cliente"].astype(str).str.strip()
        if "descripcion" in out.columns:
            out["descripcion"] = out["descripcion"].astype(str).str.strip()
        return out

    df_f = _extract(df_forecast, map_f, "forecast")
    df_v = _extract(df_venta,    map_v, "venta")

    # ── Determinar columnas de merge ─────────────────────────────
    merge_on = ["mes_ts", "sku"]
    if "cliente" in df_f.columns and "cliente" in df_v.columns:
        merge_on.append("cliente")

    # ── Merge ────────────────────────────────────────────────────
    df = pd.merge(df_f, df_v, on=merge_on, how="outer", suffixes=("", "_v"))
    df["forecast"] = df["forecast"].fillna(0)
    df["venta"]    = df["venta"].fillna(0)

    # Consolidar descripcion y cliente (puede venir de uno u otro archivo)
    for col in ["descripcion", "cliente"]:
        left  = col
        right = col + "_v"
        if left not in df.columns and right in df.columns:
            df.rename(columns={right: left}, inplace=True)
        elif left in df.columns and right in df.columns:
            df[left] = df[left].fillna(df[right])
            df.drop(columns=[right], inplace=True)

    if "cliente" not in df.columns:
        df["cliente"] = "Sin Cliente"
    if "descripcion" not in df.columns:
        df["descripcion"] = ""

    df["cliente"]     = df["cliente"].fillna("Sin Cliente").astype(str).str.strip()
    df["descripcion"] = df["descripcion"].fillna("").astype(str).str.strip()

    # ── Calcular FA fila a fila ───────────────────────────────────
    df["fa"] = compute_fa_series(df, "forecast", "venta")
    df["error_abs"] = (df["venta"] - df["forecast"]).abs()

    # ── Columnas de presentación ──────────────────────────────────
    df["mes_key"]   = df["mes_ts"].apply(_mes_key)
    df["mes_label"] = df["mes_ts"].apply(_mes_label)

    # ── Ordenar por mes ───────────────────────────────────────────
    df.sort_values("mes_ts", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # ── Meses disponibles (ordenados) ────────────────────────────
    meses_df = (df[["mes_ts", "mes_key", "mes_label"]]
                .drop_duplicates("mes_key")
                .sort_values("mes_ts"))
    meses_ordered = meses_df["mes_key"].tolist()
    meses_labels  = dict(zip(meses_df["mes_key"], meses_df["mes_label"]))

    clientes = sorted(df["cliente"].unique().tolist())
    skus     = sorted(df["sku"].unique().tolist())

    # ════════════════════════════════════════════════════════════
    # 1. KPIs
    # ════════════════════════════════════════════════════════════
    kpis = _build_kpis(df, meses_ordered, meses_labels)

    # ════════════════════════════════════════════════════════════
    # 2. Tendencia mensual
    # ════════════════════════════════════════════════════════════
    trend = _build_trend(df, meses_ordered, meses_labels)

    # ════════════════════════════════════════════════════════════
    # 3. Tabla SKU
    # ════════════════════════════════════════════════════════════
    sku_table = _build_sku_table(df, meses_ordered)

    # ════════════════════════════════════════════════════════════
    # 4. Tabla Cliente-SKU
    # ════════════════════════════════════════════════════════════
    cliente_sku_table = _build_cliente_sku_table(df)

    # ════════════════════════════════════════════════════════════
    # 5. Ranking
    # ════════════════════════════════════════════════════════════
    ranking = _build_ranking(df)

    # ════════════════════════════════════════════════════════════
    # 6. Heatmap
    # ════════════════════════════════════════════════════════════
    heatmap = _build_heatmap(df, clientes, meses_ordered, meses_labels)

    return {
        "kpis":              kpis,
        "trend":             trend,
        "sku_table":         sku_table,
        "cliente_sku_table": cliente_sku_table,
        "ranking":           ranking,
        "heatmap":           heatmap,
        "clientes":          clientes,
        "meses":             [{"key": k, "label": meses_labels[k]} for k in meses_ordered],
        "skus":              skus,
        "archivo_forecast":  os.path.basename(file_forecast),
        "archivo_venta":     os.path.basename(file_venta) if file_venta else "—",
        "updated_at":        datetime.now().strftime("%d-%b-%Y %H:%M"),
        "error":             None,
    }


def _build_kpis(df, meses, labels):
    if not meses:
        return {}
    ultimo = meses[-1]
    anterior = meses[-2] if len(meses) >= 2 else None

    df_ult = df[df["mes_key"] == ultimo]
    fa_ult = fa_from_df(df_ult, "forecast", "venta") if not df_ult.empty else None

    fa_ant = None
    if anterior:
        df_ant = df[df["mes_key"] == anterior]
        fa_ant = fa_from_df(df_ant, "forecast", "venta") if not df_ant.empty else None

    variacion = round(fa_ult - fa_ant, 1) if (fa_ult is not None and fa_ant is not None) else None
    tendencia = ("up" if variacion and variacion > 0 else
                 "down" if variacion and variacion < 0 else "flat")

    # FA total histórico (todos los meses)
    fa_total = fa_from_df(df, "forecast", "venta") if not df.empty else None

    return {
        "fa_ultimo_mes":   fa_ult,
        "mes_label":       labels.get(ultimo, ultimo),
        "fa_mes_ant":      fa_ant,
        "mes_ant_label":   labels.get(anterior, "") if anterior else None,
        "variacion":       variacion,
        "tendencia":       tendencia,
        "fa_total":        fa_total,
        "n_meses":         len(meses),
        "color":           fa_semaforo(fa_ult) if fa_ult is not None else "red",
    }


def _build_trend(df, meses, labels):
    rows = []
    for mes_key in meses:
        dg = df[df["mes_key"] == mes_key]
        if dg.empty:
            continue
        fa = fa_from_df(dg, "forecast", "venta")
        rows.append({
            "mes":     mes_key,
            "label":   labels.get(mes_key, mes_key),
            "fa":      fa,
            "color":   fa_semaforo(fa),
            "forecast": float(dg["forecast"].sum()),
            "venta":    float(dg["venta"].sum()),
        })
    return rows


def _build_sku_table(df, meses_ordered):
    """Agrupa por SKU con FA total y tendencia por los últimos meses."""
    N_TREND = 6  # últimos N meses para sparkline
    ultimos_meses = meses_ordered[-N_TREND:]

    rows = []
    for sku, grp in df.groupby("sku", sort=True):
        fa_total = fa_from_df(grp, "forecast", "venta")
        desc     = grp["descripcion"].mode()[0] if not grp["descripcion"].empty else ""
        total_f  = float(grp["forecast"].sum())
        total_v  = float(grp["venta"].sum())

        # Tendencia: FA por mes (solo últimos N_TREND meses)
        trend_vals = []
        for mes_key in ultimos_meses:
            dg = grp[grp["mes_key"] == mes_key]
            if not dg.empty:
                trend_vals.append(fa_from_df(dg, "forecast", "venta"))
            else:
                trend_vals.append(None)

        rows.append({
            "sku":         str(sku),
            "descripcion": str(desc),
            "forecast":    round(total_f, 0),
            "venta":       round(total_v, 0),
            "fa":          fa_total,
            "fa_color":    fa_chip_class(fa_total),
            "trend":       trend_vals,
        })
    rows.sort(key=lambda r: r["fa"])
    return rows


def _build_cliente_sku_table(df):
    rows = []
    group_cols = ["cliente", "sku", "mes_key", "mes_label"]
    for _, grp_row in df.groupby(["cliente", "sku", "mes_key"], sort=False):
        fa = fa_from_df(grp_row, "forecast", "venta")
        desc = grp_row["descripcion"].mode()[0] if not grp_row["descripcion"].empty else ""
        ml   = grp_row["mes_label"].iloc[0] if "mes_label" in grp_row.columns else ""
        rows.append({
            "cliente":     str(grp_row["cliente"].iloc[0]),
            "sku":         str(grp_row["sku"].iloc[0]),
            "descripcion": str(desc),
            "mes":         str(grp_row["mes_key"].iloc[0]),
            "mes_label":   ml,
            "forecast":    round(float(grp_row["forecast"].sum()), 0),
            "venta":       round(float(grp_row["venta"].sum()), 0),
            "fa":          fa,
            "fa_color":    fa_chip_class(fa),
        })
    rows.sort(key=lambda r: (r["cliente"], r["mes"], r["sku"]))
    return rows


def _build_ranking(df, top_n: int = 10):
    """Top mejores y peores FA por SKU (usando el último mes disponible)."""
    if df.empty:
        return {"mejores": [], "peores": []}

    ultimo_mes = df["mes_key"].max()
    df_ult = df[df["mes_key"] == ultimo_mes]
    if df_ult.empty:
        df_ult = df

    sku_fa = []
    for sku, grp in df_ult.groupby("sku"):
        fa   = fa_from_df(grp, "forecast", "venta")
        desc = grp["descripcion"].mode()[0] if not grp["descripcion"].empty else ""
        clientes = ", ".join(sorted(grp["cliente"].unique()[:3]))
        sku_fa.append({"sku": str(sku), "descripcion": str(desc),
                       "clientes": clientes, "fa": fa, "fa_color": fa_chip_class(fa)})

    sku_fa.sort(key=lambda x: x["fa"])
    return {
        "peores":  sku_fa[:top_n],
        "mejores": list(reversed(sku_fa[-top_n:])),
    }


def _build_heatmap(df, clientes, meses_ordered, meses_labels):
    """Matriz cliente × mes con FA ponderada."""
    matrix = []
    for cliente in clientes:
        row_vals = []
        for mes_key in meses_ordered:
            dg = df[(df["cliente"] == cliente) & (df["mes_key"] == mes_key)]
            if dg.empty:
                row_vals.append(None)
            else:
                row_vals.append(fa_from_df(dg, "forecast", "venta"))
        matrix.append({
            "cliente": cliente,
            "values":  row_vals,
            "colors":  [fa_heatmap_color(v) if v is not None else "#f5f5f5" for v in row_vals],
        })
    return {
        "meses":  [meses_labels.get(k, k) for k in meses_ordered],
        "matrix": matrix,
    }


# ══════════════════════════════════════════════════════════════════
#  INTERFAZ PÚBLICA
# ══════════════════════════════════════════════════════════════════

def get_fa_data(force: bool = False) -> dict:
    """
    Retorna los datos FA procesados (desde caché si disponible).
    Forzar recarga con force=True (botón "Actualizar información").
    """
    global _fa_cache
    if _fa_cache is not None and not force:
        return _fa_cache

    folder = Config.FA_DATA_FOLDER
    if not folder:
        return {"error": "FA_DATA_FOLDER no está configurada.", "kpis": {}, "trend": [],
                "sku_table": [], "cliente_sku_table": [], "ranking": {}, "heatmap": {},
                "clientes": [], "meses": [], "skus": [], "updated_at": None}

    try:
        path_forecast, path_venta = _find_files(folder)
        if path_forecast is None:
            raise FileNotFoundError("No se encontró el archivo de Forecast en la carpeta.")

        df_f = _read_file(path_forecast)
        df_v = _read_file(path_venta) if path_venta else df_f.copy()

        result = _process(df_f, df_v, path_forecast, path_venta or path_forecast)
        _fa_cache = result
        log.info("FA data cargada: %d filas, %d meses, carpeta: %s",
                 len(df_f) + len(df_v), len(result.get("meses", [])), folder)
        return result

    except Exception as e:
        log.exception("Error cargando FA data: %s", e)
        err = {"error": str(e), "kpis": {}, "trend": [], "sku_table": [],
               "cliente_sku_table": [], "ranking": {}, "heatmap": {},
               "clientes": [], "meses": [], "skus": [], "updated_at": None}
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
