"""
Cálculo de KPIs y semáforos para el dashboard ejecutivo SPOT.
"""
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
from config import Config

_TZ_CL = ZoneInfo("America/Santiago")

log = logging.getLogger(__name__)

_MES_LARGO_KPI = {1:"ENERO",2:"FEBRERO",3:"MARZO",4:"ABRIL",5:"MAYO",6:"JUNIO",
                  7:"JULIO",8:"AGOSTO",9:"SEPTIEMBRE",10:"OCTUBRE",11:"NOVIEMBRE",12:"DICIEMBRE"}


def semaforo_fr(fr: float) -> str:
    if fr >= Config.FR_GREEN:  return "green"
    if fr >= Config.FR_YELLOW: return "yellow"
    if fr >= Config.FR_ORANGE: return "orange"
    return "red"


def semaforo_count(count: int, verde: int, amarillo: int, naranja: int) -> str:
    if count <= verde:   return "green"
    if count <= amarillo: return "yellow"
    if count <= naranja:  return "orange"
    return "red"


def fr_chip_class(fr: float) -> str:
    if fr >= Config.FR_GREEN:  return "c-green"
    if fr >= Config.FR_YELLOW: return "c-yellow"
    if fr >= Config.FR_ORANGE: return "c-orange"
    return "c-red"


# Clientes clave para el cálculo de Venta Perdida MTD
_CLIENTES_VENTA_PERDIDA = [
    "sodimac", "walmart", "jumbo", "easy", "tottus",
    "aramco", "shell", "bestias",
]

def _venta_perdida_mtd(df_mes: pd.DataFrame) -> float:
    """BO valorizado MTD — solo OCs cerradas de los clientes clave."""
    if df_mes.empty or "cliente" not in df_mes.columns:
        return 0.0
    df_cerradas = df_mes[df_mes["estado"] == "CERRADA"] if "estado" in df_mes.columns else df_mes
    if df_cerradas.empty:
        return 0.0
    clientes_lower = df_cerradas["cliente"].str.lower().fillna("")
    mask = clientes_lower.apply(
        lambda c: any(kw in c for kw in _CLIENTES_VENTA_PERDIDA)
    )
    return float(df_cerradas.loc[mask, "bo_valorizado"].sum()) if "bo_valorizado" in df_cerradas.columns else 0.0


def compute_kpis(df: pd.DataFrame) -> dict:
    """Calcula todos los KPIs del dashboard a partir del DataFrame completo."""
    if df is None or df.empty:
        return _empty_kpis()

    today     = pd.Timestamp(datetime.now(_TZ_CL).date())
    mes_ini   = today.replace(day=1)
    mes_fin   = (mes_ini + pd.offsets.MonthEnd(1))

    # ── Filtros ───────────────────────────────────────────────────
    df_mes  = df[df["fecha_despacho"].between(mes_ini, mes_fin)] if "fecha_despacho" in df.columns else df
    df_pend = df[df["estado"] != "CERRADA"] if "estado" in df.columns else df

    # 1. Fill Rate Mes Actual (acumulado mes, todas las líneas)
    sol_mes  = df_mes["un_solicitadas"].sum()
    asig_mes = df_mes["un_asignadas"].sum()
    fr_mes   = round((asig_mes / sol_mes * 100), 1) if sol_mes > 0 else 0.0

    # 2. OC en Curso — cantidad de OCs pendientes distintas
    oc_en_curso = df_pend["oc"].nunique() if "oc" in df_pend.columns else 0

    # 3. Fill Rate de OC en Curso (todas las pendientes)
    sol_pend  = df_pend["un_solicitadas"].sum()
    asig_pend = df_pend["un_asignadas"].sum()
    fr_en_curso = round((asig_pend / sol_pend * 100), 1) if sol_pend > 0 else 0.0

    # 3b. Fill Rate OCs pendientes con despacho en el mes actual
    df_pend_mes = df_pend[df_pend["fecha_despacho"].between(mes_ini, mes_fin)] if "fecha_despacho" in df_pend.columns else pd.DataFrame()
    sol_pm  = df_pend_mes["un_solicitadas"].sum() if not df_pend_mes.empty else 0
    asig_pm = df_pend_mes["un_asignadas"].sum()   if not df_pend_mes.empty else 0
    fr_pend_mes = round((asig_pm / sol_pm * 100), 1) if sol_pm > 0 else 0.0
    oc_pend_mes = df_pend_mes["oc"].nunique() if not df_pend_mes.empty and "oc" in df_pend_mes.columns else 0

    # 4. Valorizado de OC en Curso (suma valor_total)
    val_en_curso = _safe_sum(df_pend, "valor_total")

    # 4b. Pendiente de Facturar — valor_total OCs pendientes de clientes clave
    if not df_pend.empty and "cliente" in df_pend.columns:
        _mask_clave = df_pend["cliente"].str.lower().fillna("").apply(
            lambda c: any(kw in c for kw in _CLIENTES_VENTA_PERDIDA)
        )
        pend_facturar = float(df_pend.loc[_mask_clave, "valor_total"].sum()) if "valor_total" in df_pend.columns else 0.0
    else:
        pend_facturar = 0.0

    # 5. Back Order Valorizado de OC en Curso
    bo_val_en_curso = _safe_sum(df_pend, "bo_valorizado")

    # 6. Venta Perdida MTD (BO clientes clave, mes en curso)
    venta_perdida_mtd = _venta_perdida_mtd(df_mes)

    # ── BO por producto (panel derecho) ──────────────────────────
    bo_por_producto = _bo_por_producto(df_pend)

    # ── FR por cliente (para gráfico) ────────────────────────────
    fr_por_cliente = _fr_por_cliente(df_mes)

    return {
        "fr_mes":       fr_mes,
        "fr_mes_color": semaforo_fr(fr_mes),
        "fr_mes_label": _fr_label(fr_mes),

        "fr_pend_mes":       fr_pend_mes,
        "fr_pend_mes_color": semaforo_fr(fr_pend_mes),
        "fr_pend_mes_label": _fr_label(fr_pend_mes),
        "oc_pend_mes":       oc_pend_mes,
        "sol_pend_mes":      int(sol_pm),
        "asig_pend_mes":     int(asig_pm),

        "venta_perdida_mtd": round(venta_perdida_mtd, 0),

        "pend_facturar":        round(pend_facturar, 0),

        "oc_en_curso":          oc_en_curso,
        "fr_en_curso":          fr_en_curso,
        "fr_en_curso_color":    semaforo_fr(fr_en_curso),
        "val_en_curso":         round(val_en_curso, 0),
        "bo_val_en_curso":      round(bo_val_en_curso, 0),

        "bo_por_producto": bo_por_producto,
        "fr_por_cliente":  fr_por_cliente,

        "mes_label": _MES_LARGO_KPI[today.month] + " " + str(today.year),
        "sol_mes":   int(sol_mes),
        "asig_mes":  int(asig_mes),
    }


def _fr_label(fr: float) -> str:
    if fr >= Config.FR_GREEN:  return "ÓPTIMO"
    if fr >= Config.FR_YELLOW: return "ATENCIÓN"
    if fr >= Config.FR_ORANGE: return "RIESGO"
    return "CRÍTICO"


def _safe_sum(df: pd.DataFrame, col: str) -> float:
    return float(df[col].sum()) if col in df.columns else 0.0


def _bo_por_producto(df: pd.DataFrame) -> list:
    """Acumula BO de OCs pendientes por producto, de mayor a menor."""
    if df.empty or "producto" not in df.columns:
        return []

    df_bo = df[df["bo_un"] > 0].copy()
    if df_bo.empty:
        return []

    grp = df_bo.groupby("producto").agg(
        bo_un=("bo_un", "sum"),
        un_sol=("un_solicitadas", "sum"),
        un_asig=("un_asignadas", "sum"),
        n_ocs=("oc", "nunique"),
    ).reset_index()

    grp["fr"] = np.where(
        grp["un_sol"] > 0,
        (grp["un_asig"] / grp["un_sol"] * 100).round(1),
        100.0,
    )

    grp = grp.sort_values("bo_un", ascending=False).head(12)

    return [
        {
            "producto": row["producto"],
            "bo_un":    int(row["bo_un"]),
            "fr":       row["fr"],
            "fr_color": fr_chip_class(row["fr"]),
            "semaforo": semaforo_fr(row["fr"]),
            "n_ocs":    int(row["n_ocs"]),
        }
        for _, row in grp.iterrows()
    ]


def _fr_por_cliente(df: pd.DataFrame) -> list:
    if df.empty or "cliente" not in df.columns:
        return []

    grp = df.groupby("cliente").agg(
        un_sol=("un_solicitadas", "sum"),
        un_asig=("un_asignadas", "sum"),
    ).reset_index()

    grp["fr"] = np.where(
        grp["un_sol"] > 0,
        (grp["un_asig"] / grp["un_sol"] * 100).round(1),
        100.0,
    )
    grp.sort_values("fr", inplace=True)

    return [
        {"cliente": row["cliente"], "fr": row["fr"], "color": semaforo_fr(row["fr"])}
        for _, row in grp.iterrows()
    ]


def compute_oc_detail(df: pd.DataFrame, oc_id: str, cliente: str = "") -> dict:
    """Detalle SKU para el drill-down de una OC."""
    if df is None or df.empty:
        return {}

    mask   = df["oc"].astype(str) == str(oc_id)
    df_oc  = df[mask].copy()
    if cliente:
        df_oc = df_oc[df_oc["cliente"] == cliente]

    if df_oc.empty:
        return {"error": f"OC {oc_id} no encontrada"}

    row0   = df_oc.iloc[0]
    sol    = int(df_oc["un_solicitadas"].sum())
    asig   = int(df_oc["un_asignadas"].sum())
    bo     = int(df_oc["bo_un"].sum())
    fr     = round(asig / sol * 100, 1) if sol > 0 else 100.0
    boval  = df_oc["bo_valorizado"].sum()

    skus = []
    for _, r in df_oc.iterrows():
        s_sol  = int(r.get("un_solicitadas", 0))
        s_asig = int(r.get("un_asignadas", 0))
        s_bo   = int(r.get("bo_un", 0))
        s_fr   = round(s_asig / s_sol * 100, 1) if s_sol > 0 else 100.0

        comentario_raw = str(r.get("comentarios", "") or "").strip()
        if comentario_raw in ("nan", "None", ""):
            comentario_raw = ""

        if s_fr >= 100:
            motivo = "Completado"
        elif s_bo > 0:
            motivo = comentario_raw
        else:
            motivo = comentario_raw

        skus.append({
            "ean_spot":  str(r.get("ean_spot", "")).replace(".0", ""),
            "producto":  str(r.get("producto", "")),
            "categoria": str(r.get("categoria", "")),
            "marca":     str(r.get("marca", "")),
            "sol":       s_sol,
            "asig":      s_asig,
            "bo":        s_bo,
            "fr":        s_fr,
            "fr_color":  fr_chip_class(s_fr),
            "stock":     int(r.get("stock", 0)) if not pd.isna(r.get("stock", 0)) else 0,
            "motivo":    motivo,
            "comentario": str(r.get("comentarios", "")) if str(r.get("comentarios", "")) not in ["nan",""] else "",
        })

    fecha_d = row0.get("fecha_despacho")
    fecha_str = fecha_d.strftime("%d-%b-%Y") if pd.notna(fecha_d) else "—"

    return {
        "oc":             oc_id,
        "cliente":        str(row0.get("cliente", "")),
        "estado":         str(row0.get("estado", "")),
        "fecha_despacho": fecha_str,
        "es_vencida":     bool(row0.get("es_vencida", False)),
        "un_sol":         sol,
        "un_asig":        asig,
        "bo_un":          bo,
        "bo_valorizado":  round(float(boval), 0),
        "fr":             fr,
        "fr_color":       fr_chip_class(fr),
        "semaforo":       semaforo_fr(fr),
        "skus":           skus,
    }


def _empty_kpis() -> dict:
    return {
        "pend_facturar": 0,
        "fr_mes": 0, "fr_mes_color": "red", "fr_mes_label": "SIN DATOS",
        "fr_pend_mes": 0, "fr_pend_mes_color": "red", "fr_pend_mes_label": "SIN DATOS",
        "oc_pend_mes": 0, "sol_pend_mes": 0, "asig_pend_mes": 0,
        "oc_en_curso": 0,
        "fr_en_curso": 0, "fr_en_curso_color": "red",
        "val_en_curso": 0, "bo_val_en_curso": 0,
        "bo_por_producto": [], "fr_por_cliente": [],
        "mes_label": "", "sol_mes": 0, "asig_mes": 0,
    }
