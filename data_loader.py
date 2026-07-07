"""
Carga y transforma los datos del Excel de Seguimiento OCs.
Lee desde Graph API (OneDrive) y procesa con Pandas.
"""
import io
import logging
import os
import threading
from datetime import datetime, date
from zoneinfo import ZoneInfo
import pandas as pd

_TZ_CL = ZoneInfo("America/Santiago")
import numpy as np
from config import Config
from graph_client import download_excel_bytes, get_file_last_modified

log = logging.getLogger(__name__)

# ── Cache en memoria ──────────────────────────────────────────────
_lock      = threading.Lock()
_cache: dict = {
    "df":           None,
    "updated_at":   None,
    "file_modified": None,
    "error":        None,
    "loading":      False,
}


def get_cache() -> dict:
    return _cache


def _is_demo_mode() -> bool:
    local = os.getenv("LOCAL_EXCEL_PATH", "")
    if local and os.path.exists(local):
        return False
    return os.getenv("AZURE_CLIENT_ID", "demo") in ("demo", "", "YOUR_CLIENT_ID")


def refresh_data(force: bool = False) -> bool:
    """
    Descarga y procesa el Excel. Guarda resultado en cache.
    En modo demo (sin credenciales Azure) carga datos de muestra.
    Retorna True si se actualizó correctamente.
    """
    with _lock:
        if _cache["loading"]:
            return False
        _cache["loading"] = True

    try:
        if _is_demo_mode():
            log.info("MODO DEMO: cargando datos de muestra (sin credenciales Azure)")
            df = _load_demo_data()
        else:
            # Intentar primero leer desde ruta local si existe
            local_path = os.getenv("LOCAL_EXCEL_PATH", "")
            if local_path and os.path.exists(local_path):
                log.info(f"Leyendo Excel local: {local_path}")
                import shutil, tempfile
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    shutil.copy2(local_path, tmp_path)
                    df = _parse_excel(open(tmp_path, "rb"))
                finally:
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
            else:
                log.info("Iniciando descarga del Excel desde OneDrive...")
                excel_bytes   = download_excel_bytes()
                modified_iso  = get_file_last_modified()
                df            = _parse_excel(io.BytesIO(excel_bytes))
                try:
                    file_modified = (
                        pd.Timestamp(modified_iso, tz="UTC")
                        .tz_convert(_TZ_CL)
                        .strftime("%d-%b-%Y %H:%M")
                    ) if modified_iso else None
                except Exception:
                    file_modified = modified_iso
                with _lock:
                    _cache["file_modified"] = file_modified

        with _lock:
            _cache["df"]         = df
            _cache["updated_at"] = datetime.now(_TZ_CL)
            _cache["error"]      = None
        log.info(f"Datos cargados: {len(df):,} filas")
        return True

    except Exception as e:
        log.error(f"Error cargando Excel: {e}", exc_info=True)
        with _lock:
            _cache["error"]      = str(e)
            _cache["updated_at"] = datetime.now(_TZ_CL)
        return False
    finally:
        with _lock:
            _cache["loading"] = False


def _load_demo_data() -> pd.DataFrame:
    """Genera un DataFrame de muestra con datos realistas de SPOT ESSENCE."""
    today = pd.Timestamp(date.today())
    # cols: oc, cliente, estado, fecha_despacho, un_sol, un_asig, bo_un, bo_val, comentarios, producto, categoria, marca, stock, valor_total, valor_facturado
    rows = [
        # oc, cliente, estado, fecha_despacho, un_sol, un_asig, bo_un, bo_val, comentarios, producto, categoria, marca, stock, valor_total, valor_facturado, motivo_bo, categoria_arbol
        ("6508802200","Walmart Chile","BACK ORDER", today - pd.Timedelta(days=1), 1200, 864,336, 336*4200,"Sin stock aromas cítricos","Aromatizador Auto Cítrico 8ml","AROMATIZADORES","SPOT",  0, 1200*4200, 864*4200, "Sin stock",             "Quiebre de stock"),
        ("6508802200","Walmart Chile","BACK ORDER", today - pd.Timedelta(days=1),  400, 264,136, 136*3800,"Sin stock aromas cítricos","Home Spray Lavanda 250ml",     "HOME SPRAY",   "SPOT", 12,  400*3800, 264*3800, "Sin stock",             "Quiebre de stock"),
        ("6508802200","Walmart Chile","BACK ORDER", today - pd.Timedelta(days=1),  300, 300,  0,       0,"",                          "Difusor Varillas 150ml Berries","DIFUSORES",    "SPOT", 45,  300*3600, 300*3600, "",                      ""),
        ("6508799341","Sodimac",      "BACK ORDER", today + pd.Timedelta(days=2),  400, 200,200, 200*3500,"Asignación parcial",        "Difusor Auto Menta 5ml",       "AROMATIZADORES","SPOT",  0,  400*3500, 200*3500, "Stock insuficiente",    "Quiebre de stock"),
        ("6508799341","Sodimac",      "BACK ORDER", today + pd.Timedelta(days=2),  400, 400,  0,       0,"",                          "Home Spray Coco 250ml",        "HOME SPRAY",   "SPOT", 80,  400*3800, 400*3800, "",                      ""),
        ("6508801554","Ripley",       "PENDIENTE",  today + pd.Timedelta(days=3),  200, 128, 72,  72*4100,"Faltan varillas 200ml",     "Difusor Varillas 200ml Flores","DIFUSORES",    "SPOT",  5,  200*4100, 128*4100, "Pendiente de compra",   "Retraso de compra"),
        ("6508801554","Ripley",       "PENDIENTE",  today + pd.Timedelta(days=3),  400, 400,  0,       0,"",                          "Aromatizador Auto Lavanda",    "AROMATIZADORES","SPOT",120,  400*3900, 400*3900, "",                      ""),
        ("6508800112","Paris",        "PENDIENTE",  today + pd.Timedelta(days=4),  400, 364, 36,  36*3900,"",                          "Home Spray Vainilla 200ml",    "HOME SPRAY",   "SPOT",  8,  400*3900, 364*3900, "Stock insuficiente",    "Quiebre de stock"),
        ("6508802118","Easy",         "PENDIENTE",  today + pd.Timedelta(days=6),  120, 108, 12,  12*3600,"Falta home spray ámbar",    "Home Spray Ámbar 250ml",       "HOME SPRAY",   "SPOT",  3,  120*3600, 108*3600, "Sin stock",             "Quiebre de stock"),
        ("6508802118","Easy",         "PENDIENTE",  today + pd.Timedelta(days=6),  120, 120,  0,       0,"",                          "Difusor Varillas 150ml Cítrico","DIFUSORES",    "SPOT", 30,  120*3400, 120*3400, "",                      ""),
        ("6508803001","Falabella",    "PENDIENTE",  today + pd.Timedelta(days=6),  250, 245,  5,   5*5200,"Casi completo",             "Kit Aromatizador Premium",     "KITS",         "SPOT", 12,  250*5200, 245*5200, "Pendiente asignación",  "Retraso de compra"),
        ("6508790011","Lider",        "CERRADA",    today - pd.Timedelta(days=10), 600, 600,  0,       0,"",                          "Home Spray Varios",            "HOME SPRAY",   "SPOT",  0,  600*3500, 600*3500, "",                      ""),
    ]
    cols = ["oc","cliente","estado","fecha_despacho","un_solicitadas","un_asignadas",
            "bo_un","bo_valorizado","comentarios","producto","categoria","marca","stock",
            "valor_total","valor_facturado","motivo_bo","categoria_arbol"]
    hist_rows = _generate_hist_rows(today)
    all_rows  = rows + hist_rows
    cols = ["oc","cliente","estado","fecha_despacho","un_solicitadas","un_asignadas",
            "bo_un","bo_valorizado","comentarios","producto","categoria","marca","stock",
            "valor_total","valor_facturado","motivo_bo","categoria_arbol"]
    df = pd.DataFrame(all_rows, columns=cols)
    df["fill_rate"] = np.where(df["un_solicitadas"]>0,
                               (df["un_asignadas"]/df["un_solicitadas"]*100).round(1), 100.0)
    today_ts = pd.Timestamp(date.today())
    df["es_vencida"]  = (df["fecha_despacho"] < today_ts) & (df["estado"] != "CERRADA")
    df["dias_vencer"] = (df["fecha_despacho"] - today_ts).dt.days
    df["es_proxima"]  = df["dias_vencer"].between(0, Config.DAYS_ALERT_UPCOMING) & (df["estado"]!="CERRADA")
    df["fecha_emision"] = today_ts - pd.Timedelta(days=15)
    mask_bo = (df["estado"]!="CERRADA") & (df["bo_un"]>0)
    df.loc[mask_bo,"estado"] = "BACK ORDER"
    return df


def _generate_hist_rows(today: pd.Timestamp) -> list:
    """Genera 12 meses de OCs históricas (CERRADA) con datos realistas."""
    rng = np.random.default_rng(42)

    clientes_cfg = [
        ("Walmart Chile", 88, 8),
        ("Sodimac",       85, 10),
        ("Ripley",        92, 6),
        ("Paris",         95, 4),
        ("Easy",          78, 12),
        ("Falabella",     97, 3),
    ]
    productos = [
        ("Aromatizador Auto Cítrico 8ml",  "AROMATIZADORES", 4200),
        ("Home Spray Lavanda 250ml",        "HOME SPRAY",     3800),
        ("Difusor Auto Menta 5ml",          "AROMATIZADORES", 3500),
        ("Difusor Varillas 200ml Flores",   "DIFUSORES",      4100),
        ("Home Spray Vainilla 200ml",       "HOME SPRAY",     3900),
        ("Home Spray Ámbar 250ml",          "HOME SPRAY",     3600),
        ("Kit Aromatizador Premium",        "KITS",           5200),
        ("Difusor Varillas 150ml Berries",  "DIFUSORES",      3600),
    ]
    motivos   = ["Sin stock", "Sin stock", "Stock insuficiente", "Pendiente de compra", "Pendiente asignación", ""]
    cat_arbol = ["Quiebre de stock", "Quiebre de stock", "Quiebre de stock", "Retraso de compra", "Retraso de compra", "Problema logístico", ""]

    rows, oc_idx = [], 6508600000

    for m in range(12, 0, -1):
        m_start = (today - pd.DateOffset(months=m)).replace(day=1)
        last_d  = (m_start + pd.offsets.MonthEnd(1)).day

        for cli, base_fr, var_fr in clientes_cfg:
            n_ocs = int(rng.integers(2, 5))
            for _ in range(n_ocs):
                oc_idx += 1
                oc_id   = str(oc_idx)
                day     = int(rng.integers(3, last_d - 2))
                fecha_d = m_start.replace(day=day)
                oc_fr   = float(np.clip(base_fr + int(rng.integers(-var_fr, var_fr + 1)), 60, 100))

                n_skus  = int(rng.integers(2, 5))
                pidxs   = rng.choice(len(productos), size=n_skus, replace=False)

                for pi in pidxs:
                    prod, cat, precio = productos[pi]
                    un_sol  = int(rng.integers(2, 8)) * 100
                    sku_fr  = float(np.clip(oc_fr + int(rng.integers(-8, 9)), 60, 100))
                    un_asig = round(un_sol * sku_fr / 100)
                    bo_un   = un_sol - un_asig
                    bo_val  = bo_un * precio
                    motivo  = motivos[int(rng.integers(0, len(motivos)))]    if bo_un > 0 else ""
                    cat_a   = cat_arbol[int(rng.integers(0, len(cat_arbol)))] if bo_un > 0 else ""

                    rows.append((
                        oc_id, cli, "CERRADA", fecha_d,
                        un_sol, un_asig, bo_un, bo_val,
                        motivo, prod, cat, "SPOT", 0,
                        un_sol * precio, un_asig * precio, motivo, cat_a
                    ))
    return rows


def _parse_excel(buf: io.BytesIO) -> pd.DataFrame:
    """Lee el Excel y normaliza los datos."""
    df = pd.read_excel(
        buf,
        sheet_name=Config.SHEET_NAME,
        header=Config.HEADER_ROW,
        engine="openpyxl",
    )

    # Renombrar columnas según mapa
    rename = {k: v for k, v in Config.COL_MAP.items() if k in df.columns}
    df.rename(columns=rename, inplace=True)

    # Eliminar filas completamente vacías
    df.dropna(how="all", inplace=True)

    # ── Fechas ────────────────────────────────────────────────────
    for col in ["fecha_emision", "fecha_despacho"]:
        if col in df.columns:
            df[col] = _convert_date(df[col])

    # ── Numéricos ─────────────────────────────────────────────────
    num_cols = [
        "un_solicitadas", "un_asignadas", "bo_un", "bo_valorizado",
        "valor_total", "valor_facturado", "precio_oc", "precio_lp",
        "diff_precio", "stock",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # ── Fill Rate por línea ───────────────────────────────────────
    df["fill_rate"] = np.where(
        df["un_solicitadas"] > 0,
        (df["un_asignadas"] / df["un_solicitadas"] * 100).round(1),
        100.0,
    )

    # ── Estado limpio ─────────────────────────────────────────────
    if "estado" in df.columns:
        df["estado"] = df["estado"].astype(str).str.strip().str.upper()
        # Normalizar variantes
        df["estado"] = df["estado"].replace({
            "NAN": "PENDIENTE", "NONE": "PENDIENTE", "": "PENDIENTE",
        })
        # Inferir BACK ORDER si no está cerrada y tiene BO
        mask_bo = (df["estado"] != "CERRADA") & (df["bo_un"] > 0)
        df.loc[mask_bo & ~df["estado"].isin(["BACK ORDER", "BACK_ORDER"]), "estado"] = "BACK ORDER"

    # ── Texto limpio ──────────────────────────────────────────────
    for col in ["cliente", "producto", "comentarios", "marca", "categoria"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            df[col] = df[col].replace({"nan": "", "None": ""})

    # Normalizar capitalización de cliente para evitar duplicados por casing
    if "cliente" in df.columns:
        df["cliente"] = df["cliente"].str.title()

    # ── OC como string ───────────────────────────────────────────
    if "oc" in df.columns:
        df["oc"] = df["oc"].astype(str).str.strip().str.replace(".0", "", regex=False)

    # ── Flags útiles ─────────────────────────────────────────────
    today = pd.Timestamp(date.today())
    if "fecha_despacho" in df.columns:
        df["es_vencida"]  = (df["fecha_despacho"] < today) & (df["estado"] != "CERRADA")
        df["dias_vencer"] = (df["fecha_despacho"] - today).dt.days
        df["es_proxima"]  = (
            df["dias_vencer"].between(0, Config.DAYS_ALERT_UPCOMING) &
            (df["estado"] != "CERRADA")
        )

    return df


def _convert_date(series: pd.Series) -> pd.Series:
    """
    Convierte columna que puede contener:
    - números seriales de Excel (ej: 46071)
    - strings de fecha
    - ya sea datetime
    """
    def _parse(val):
        if pd.isna(val):
            return pd.NaT
        if isinstance(val, (datetime, date)):
            return pd.Timestamp(val)
        if isinstance(val, (int, float)):
            try:
                return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(val))
            except Exception:
                return pd.NaT
        try:
            return pd.to_datetime(val, dayfirst=True)
        except Exception:
            return pd.NaT

    return series.apply(_parse)


# ── Helpers de consulta ───────────────────────────────────────────

def get_df() -> pd.DataFrame | None:
    return _cache.get("df")


def _prev_business_day(today: pd.Timestamp) -> pd.Timestamp:
    """Retorna el día hábil anterior a today (lunes→viernes, otro→ayer)."""
    offset = 3 if today.weekday() == 0 else 1  # lunes → retrocede 3 días
    return today - pd.Timedelta(days=offset)


def get_pending_df() -> pd.DataFrame:
    """
    Retorna OCs pendientes (no cerradas) con fecha de despacho
    >= 1 día hábil anterior al día actual, ordenadas por urgencia.
    """
    df = get_df()
    if df is None or df.empty:
        return pd.DataFrame()

    today    = pd.Timestamp(date.today())
    cutoff   = _prev_business_day(today)

    mask = (df["estado"] != "CERRADA") & (
        df["fecha_despacho"].isna() | (df["fecha_despacho"] >= cutoff)
    )
    pending = df[mask].copy()

    return _aggregate_by_oc(pending)


def _aggregate_by_oc(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa líneas SKU por (OC, cliente, fecha_despacho) — cada combinación es un despacho único."""
    if df.empty:
        return df

    # Normalizar fecha_despacho para el agrupador (NaT → centinela)
    df = df.copy()
    df["_fd_key"] = df["fecha_despacho"].fillna(pd.Timestamp("2099-12-31"))

    agg_dict = dict(
        fecha_despacho=("fecha_despacho", "first"),
        estado=("estado", lambda x: _worst_estado(x)),
        un_solicitadas=("un_solicitadas", "sum"),
        un_asignadas=("un_asignadas", "sum"),
        bo_un=("bo_un", "sum"),
        bo_valorizado=("bo_valorizado", "sum"),
        comentarios=("comentarios", "first"),
        es_vencida=("es_vencida", "any"),
        es_proxima=("es_proxima", "any"),
        dias_vencer=("dias_vencer", "min"),
        n_skus=("producto", "count"),
    )
    if "valor_total" in df.columns:
        agg_dict["valor_total"] = ("valor_total", "sum")
    if "valor_facturado" in df.columns:
        agg_dict["valor_facturado"] = ("valor_facturado", "sum")

    agg = df.groupby(["oc", "cliente", "_fd_key"], as_index=False).agg(**agg_dict)
    agg.drop(columns=["_fd_key"], inplace=True)

    agg["fill_rate"] = np.where(
        agg["un_solicitadas"] > 0,
        (agg["un_asignadas"] / agg["un_solicitadas"] * 100).round(1),
        100.0,
    )

    # Ordenar: vencidas primero, luego por cliente+fecha (para agrupar despachos del mismo cliente), luego menor FR
    agg["_sort_venc"]    = agg["es_vencida"].astype(int) * -1
    agg["_sort_fecha"]   = agg["fecha_despacho"].fillna(pd.Timestamp("2099-12-31"))
    agg["_sort_cliente"] = agg["cliente"].str.lower().fillna("")
    agg.sort_values(["_sort_venc", "_sort_cliente", "_sort_fecha", "fill_rate"], inplace=True)
    agg.drop(columns=["_sort_venc", "_sort_fecha", "_sort_cliente"], inplace=True)
    agg.reset_index(drop=True, inplace=True)

    return agg


def _worst_estado(estados):
    priority = {"BACK ORDER": 0, "VENCIDA": 1, "PENDIENTE": 2, "CERRADA": 9}
    return min(estados, key=lambda s: priority.get(str(s).upper(), 5))


def get_week_closed_df() -> pd.DataFrame:
    """
    Retorna OCs CERRADAS cuya fecha de despacho cae en la semana actual (lun–dom).
    Se usan para mostrarlas al final del tablero principal.
    """
    df = get_df()
    if df is None or df.empty:
        return pd.DataFrame()

    today  = pd.Timestamp(date.today())
    dow    = today.weekday()                          # 0=lun … 6=dom
    lunes  = today - pd.Timedelta(days=dow)
    domingo = lunes + pd.Timedelta(days=6)

    mask = (
        (df["estado"] == "CERRADA") &
        (df["fecha_despacho"] >= lunes) &
        (df["fecha_despacho"] <= domingo)
    )
    closed = df[mask].copy()
    # Forzar flags en False para que _pending_to_json no las marque como vencidas
    for flag in ("es_vencida", "es_proxima"):
        if flag not in closed.columns:
            closed[flag] = False
        else:
            closed[flag] = False

    agg = _aggregate_by_oc(closed)
    if not agg.empty and "cliente" in agg.columns:
        agg["_sc"] = agg["cliente"].str.lower().fillna("")
        agg["_sf"] = agg["fecha_despacho"].fillna(pd.Timestamp("2099-12-31"))
        agg.sort_values(["_sc", "_sf"], inplace=True)
        agg.drop(columns=["_sc", "_sf"], inplace=True)
        agg.reset_index(drop=True, inplace=True)
    return agg


def get_bo_detail_df() -> pd.DataFrame:
    """
    Retorna líneas individuales (SKU) con BO > 0, sin cerradas,
    con fecha de despacho >= 1 día hábil anterior.
    Ordenadas: fecha ASC · bo_valorizado DESC · bo_un DESC.
    """
    df = get_df()
    if df is None or df.empty:
        return pd.DataFrame()

    today  = pd.Timestamp(date.today())
    cutoff = _prev_business_day(today)

    mask = (
        (df["estado"] != "CERRADA") &
        (df["bo_un"] > 0) &
        (df["fecha_despacho"].isna() | (df["fecha_despacho"] >= cutoff))
    )
    bo = df[mask].copy()

    bo["fill_rate"] = np.where(
        bo["un_solicitadas"] > 0,
        (bo["un_asignadas"] / bo["un_solicitadas"] * 100).round(1),
        100.0,
    )
    if "motivo_bo" not in bo.columns:
        bo["motivo_bo"] = ""

    bo["_fd"] = bo["fecha_despacho"].fillna(pd.Timestamp("2099-12-31"))
    bo.sort_values(["_fd", "bo_valorizado", "bo_un"], ascending=[True, False, False], inplace=True)
    bo.drop(columns=["_fd"], inplace=True)
    bo.reset_index(drop=True, inplace=True)
    return bo
