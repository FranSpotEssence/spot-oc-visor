"""
SPOT ESSENCE — Supply Chain Intelligence Platform
Backend principal: Flask + Microsoft Graph API + APScheduler
"""
import logging
import os
from datetime import datetime, date
from functools import wraps

import pandas as pd
from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config
from data_loader import refresh_data, get_df, get_pending_df, get_week_closed_df, get_cache, get_bo_detail_df
from kpi_calculator import compute_kpis, compute_oc_detail, fr_chip_class, semaforo_fr
from spotia import build_context, build_light_context, ask_spotia

# ── Helpers de fecha en español ──────────────────────────────────
_MESES_LARGO = {1:"ENERO",2:"FEBRERO",3:"MARZO",4:"ABRIL",5:"MAYO",6:"JUNIO",
                7:"JULIO",8:"AGOSTO",9:"SEPTIEMBRE",10:"OCTUBRE",11:"NOVIEMBRE",12:"DICIEMBRE"}
_MESES_CORTO = {1:"ENE",2:"FEB",3:"MAR",4:"ABR",5:"MAY",6:"JUN",
                7:"JUL",8:"AGO",9:"SEP",10:"OCT",11:"NOV",12:"DIC"}

def _mes_largo(ts) -> str:
    """'JULIO 2026'"""
    return f"{_MESES_LARGO[ts.month]} {ts.year}"

def _mes_corto(ts) -> str:
    """'JUL 2026'"""
    return f"{_MESES_CORTO[ts.month]} {ts.year}"

def _dia_mes_corto(ts) -> str:
    """'15 JUL'"""
    return f"{ts.day:02d} {_MESES_CORTO[ts.month]}"

_NAN_STRS = {"nan", "none", "null", "n/a", "na", "nd"}

def _s(val) -> str:
    """Convierte un valor a string limpio; retorna '' si es NaN/None/vacío."""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    return "" if s.lower() in _NAN_STRS else s

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ── App ──────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = Config.SECRET_KEY
app.config["TEMPLATES_AUTO_RELOAD"] = True
CORS(app)

def _refresh_all_data():
    """Refresca el Excel principal y limpia el cache de Tracking PT (recarga el .xlsx más reciente de la carpeta)."""
    global _tracking_pt_cache
    refresh_data()
    _tracking_pt_cache = None


# ── Scheduler (refresh automático) ───────────────────────────────
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    func=_refresh_all_data,
    trigger="interval",
    minutes=Config.REFRESH_INTERVAL,
    id="refresh_excel",
    replace_existing=True,
)
scheduler.start()

# Carga inicial al arrancar
log.info("Carga inicial de datos...")
refresh_data()


# ── Auth ─────────────────────────────────────────────────────────

def _login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if Config.APP_PASSWORD and not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == Config.APP_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("index"))
        error = "Contraseña incorrecta"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Helpers ──────────────────────────────────────────────────────

def _fmt_date(ts) -> str:
    if pd.isna(ts) or ts is None:
        return "—"
    try:
        return ts.strftime("%d-%b-%Y")
    except Exception:
        return str(ts)


def _pending_to_json(df: pd.DataFrame) -> list:
    """Convierte el DataFrame de OCs pendientes a lista JSON para la tabla."""
    rows = []
    for _, r in df.iterrows():
        fr   = float(r.get("fill_rate", 0))
        venc = bool(r.get("es_vencida", False))
        prox = bool(r.get("es_proxima", False))
        dias = r.get("dias_vencer", None)

        if venc:
            fecha_clase = "f-venc"
            estado_badge = "VENCIDA"
            estado_clase = "e-venc"
        elif prox:
            fecha_clase  = "f-prox"
            estado_badge = "PRÓX. VENCER"
            estado_clase = "e-prox"
        else:
            fecha_clase  = "f-ok"
            estado_badge = str(r.get("estado", "PENDIENTE"))
            estado_clase = "e-pend" if estado_badge != "BACK ORDER" else "e-bo"

        rows.append({
            "oc":              str(r.get("oc", "")),
            "cliente":         str(r.get("cliente", "")),
            "fecha_despacho":  _fmt_date(r.get("fecha_despacho")),
            "fecha_clase":     fecha_clase,
            "dias_vencer":     int(dias) if pd.notna(dias) else None,
            "fill_rate":       fr,
            "fr_chip":         fr_chip_class(fr),
            "estado":          estado_badge,
            "estado_clase":    estado_clase,
            "bo_un":           int(r.get("bo_un", 0)),
            "bo_valorizado":   float(r.get("bo_valorizado", 0) or 0),
            "valor_total":     float(r.get("valor_total", 0) or 0),
            "valor_facturado": float(r.get("valor_facturado", 0) or 0),
            "un_solicitadas":  int(r.get("un_solicitadas", 0)),
            "comentarios":     _s(r.get("comentarios")),
            "n_skus":          int(r.get("n_skus", 0)),
        })
    return rows


# ── Rutas Frontend ────────────────────────────────────────────────

@app.route("/")
@_login_required
def index():
    return render_template("dashboard.html")


# ── API REST ─────────────────────────────────────────────────────

@app.route("/api/status")
@_login_required
def api_status():
    cache = get_cache()
    return jsonify({
        "ok":           cache["df"] is not None,
        "updated_at":   cache["updated_at"].isoformat() if cache.get("updated_at") else None,
        "file_modified": cache.get("file_modified"),
        "error":        cache.get("error"),
        "loading":      cache.get("loading", False),
        "rows":         len(cache["df"]) if cache["df"] is not None else 0,
    })


@app.route("/api/kpis")
@_login_required
def api_kpis():
    df   = get_df()
    kpis = compute_kpis(df)
    cache = get_cache()
    kpis["updated_at"]    = cache["updated_at"].strftime("%d-%b-%Y %H:%M") if cache.get("updated_at") else "—"
    kpis["file_modified"] = cache.get("file_modified", "")
    kpis["error"]         = cache.get("error")
    return jsonify(kpis)


@app.route("/api/orders")
@_login_required
def api_orders():
    """OCs pendientes + OCs cerradas de la semana actual para la tabla principal."""
    pending_rows = _pending_to_json(get_pending_df())
    closed_rows  = _pending_to_json(get_week_closed_df())
    # Cerradas van al final; el frontend también las ordena así
    rows = pending_rows + closed_rows

    # Filtros query params
    cliente = request.args.get("cliente", "").strip().lower()
    estado  = request.args.get("estado", "").strip().upper()
    q       = request.args.get("q", "").strip().lower()

    if cliente:
        rows = [r for r in rows if cliente in r["cliente"].lower()]
    if estado and estado != "TODOS":
        rows = [r for r in rows if estado in r["estado"].upper()]
    if q:
        rows = [r for r in rows if
                q in r["cliente"].lower() or
                q in r["oc"].lower() or
                q in r["comentarios"].lower()]

    return jsonify({"orders": rows, "total": len(rows)})


@app.route("/api/orders/<oc_id>")
@_login_required
def api_order_detail(oc_id: str):
    """Detalle SKU de una OC específica (drill-down)."""
    df      = get_df()
    cliente = request.args.get("cliente", "").strip()
    detail  = compute_oc_detail(df, oc_id, cliente)
    return jsonify(detail)


@app.route("/api/clientes")
@_login_required
def api_clientes():
    """Lista de clientes únicos para el filtro."""
    df = get_df()
    if df is None or "cliente" not in df.columns:
        return jsonify([])
    clientes = sorted(df["cliente"].dropna().unique().tolist())
    return jsonify(clientes)


@app.route("/api/refresh", methods=["POST"])
@_login_required
def api_refresh():
    """Fuerza recarga del Excel desde OneDrive."""
    global _tracking_pt_cache
    log.info("Refresh manual solicitado via API")
    ok = refresh_data(force=True)
    _tracking_pt_cache = None
    cache = get_cache()
    return jsonify({
        "ok":         ok,
        "updated_at": cache["updated_at"].strftime("%d-%b-%Y %H:%M") if cache.get("updated_at") else "—",
        "error":      cache.get("error"),
    })


@app.route("/api/backorder-detail")
@_login_required
def api_backorder_detail():
    """Líneas individuales con BO > 0 para la pestaña Detalle Back Order."""
    df = get_bo_detail_df()

    rows = []
    max_bo_val = float(df["bo_valorizado"].max()) if not df.empty else 1.0

    for _, r in df.iterrows():
        fd = r.get("fecha_despacho")
        fr = float(r.get("fill_rate", 0))
        bv = float(r.get("bo_valorizado", 0) or 0)

        # Nivel de intensidad para formato condicional
        pct = bv / max_bo_val if max_bo_val > 0 else 0
        if pct >= 0.66:   bo_level = "high"
        elif pct >= 0.33: bo_level = "mid"
        else:             bo_level = "low"

        rows.append({
            "oc":             str(r.get("oc", "")),
            "cliente":        str(r.get("cliente", "")),
            "fecha_despacho": _fmt_date(fd),
            "fecha_raw":      fd.strftime("%Y-%m-%d") if pd.notna(fd) else "",
            "es_vencida":     bool(r.get("es_vencida", False)),
            "producto":       str(r.get("producto", "")),
            "un_solicitadas": int(r.get("un_solicitadas", 0)),
            "un_asignadas":   int(r.get("un_asignadas", 0)),
            "bo_un":          int(r.get("bo_un", 0)),
            "fill_rate":      fr,
            "bo_valorizado":  bv,
            "bo_level":       bo_level,
            "comentarios":      _s(r.get("comentarios")),
            "motivo_bo":        _s(r.get("motivo_bo")),
            "categoria_arbol":  _s(r.get("categoria_arbol")),
        })

    # Filtros query params
    cliente    = request.args.get("cliente",    "").strip().lower()
    oc         = request.args.get("oc",         "").strip().lower()
    producto   = request.args.get("producto",   "").strip().lower()
    fecha_from = request.args.get("fecha_from", "").strip()
    fecha_to   = request.args.get("fecha_to",   "").strip()
    q          = request.args.get("q",          "").strip().lower()

    if cliente:
        rows = [r for r in rows if cliente in r["cliente"].lower()]
    if oc:
        rows = [r for r in rows if oc in r["oc"].lower()]
    if producto:
        rows = [r for r in rows if producto in r["producto"].lower()]
    if fecha_from:
        rows = [r for r in rows if r["fecha_raw"] >= fecha_from]
    if fecha_to:
        rows = [r for r in rows if r["fecha_raw"] <= fecha_to]
    if q:
        rows = [r for r in rows if (
            q in r["cliente"].lower() or
            q in r["oc"].lower() or
            q in r["producto"].lower()
        )]

    return jsonify({"rows": rows, "total": len(rows)})


@app.route("/api/fr-historico")
@_login_required
def api_fr_historico():
    import calendar as _cal
    df = get_df()
    if df is None or df.empty:
        return jsonify({"error": "Sin datos"})

    cliente      = request.args.get("cliente", "").strip()
    year         = request.args.get("year",    "").strip()
    months_param = request.args.get("months",  "").strip()  # "5,6,7" multi-select
    month        = request.args.get("month",   "").strip()  # legacy single month

    clientes_list = sorted(df["cliente"].dropna().unique().tolist())
    dfw = df.dropna(subset=["fecha_despacho"]).copy()

    if cliente:
        dfw = dfw[dfw["cliente"] == cliente]

    dfw["_year"]  = dfw["fecha_despacho"].dt.year
    dfw["_month"] = dfw["fecha_despacho"].dt.month
    years_list    = sorted(dfw["_year"].unique().tolist(), reverse=True)

    if year:
        dfw = dfw[dfw["_year"] == int(year)]

    # MTD: mes actual solo hasta hoy; meses cerrados usan datos completos
    from datetime import date as _date, timedelta as _td
    _today = _date.today()
    _today_ts  = pd.Timestamp(_today)
    _is_cur_mo = (dfw["_year"] == _today.year) & (dfw["_month"] == _today.month)
    dfw = dfw[~_is_cur_mo | (dfw["fecha_despacho"] <= _today_ts)]

    # Week key for each row: Monday of its week (YYYY-MM-DD)
    dfw["_wmon_s"] = (
        dfw["fecha_despacho"]
        - pd.to_timedelta(dfw["fecha_despacho"].dt.dayofweek, unit="D")
    ).dt.strftime("%Y-%m-%d")

    # Available months — last 12 rolling months only (after year+client filter)
    _last12 = set()
    _y, _mo = _today.year, _today.month
    for _ in range(12):
        _last12.add((_y, _mo))
        _mo -= 1
        if _mo == 0:
            _mo = 12
            _y -= 1

    avail_set = (dfw.groupby(["_year", "_month"]).size()
                   .reset_index()[["_year", "_month"]].drop_duplicates())
    available_months = sorted([
        {"year": int(r["_year"]), "num": int(r["_month"]),
         "label": f"{_MESES_CORTO[int(r['_month'])]} {int(r['_year'])}"}
        for _, r in avail_set.iterrows()
        if (int(r["_year"]), int(r["_month"])) in _last12
    ], key=lambda x: (x["year"], x["num"]))

    # Available weeks — last 12 rolling weeks (Mon–Dom)
    _cur_monday = _today - _td(days=_today.weekday())
    available_weeks = []
    _wd = _cur_monday
    for _ in range(12):
        _we = _wd + _td(days=6)
        _iso = _wd.isocalendar()
        available_weeks.append({
            "key":         _wd.strftime("%Y-%m-%d"),
            "label":       f"{_dia_mes_corto(_wd)} – {_dia_mes_corto(_we)}",
            "label_short": _dia_mes_corto(_wd),
            "iso_year":    _iso[0],
            "iso_week":    _iso[1],
        })
        _wd -= _td(weeks=1)
    available_weeks.reverse()

    # ── Full trend data (no month filter) — for chart ───────────
    def _monthly_rows(d):
        d = d.copy()
        d["_ym"] = d["fecha_despacho"].dt.to_period("M")
        g = d.groupby("_ym").agg(
            un_sol  =("un_solicitadas",  "sum"),
            un_asig =("un_asignadas",    "sum"),
            bo_un   =("bo_un",           "sum"),
            bo_val  =("bo_valorizado",   "sum"),
            val_tot =("valor_total",     "sum"),
            val_fac =("valor_facturado", "sum"),
        ).reset_index().sort_values("_ym")
        rows = []
        for _, r in g.iterrows():
            sol = float(r["un_sol"])
            fr  = round(float(r["un_asig"]) / sol * 100, 1) if sol > 0 else 0.0
            rows.append({
                "key":    str(r["_ym"]),
                "label":  f"{_MESES_CORTO[r['_ym'].month]} {r['_ym'].year}",
                "year":   r["_ym"].year,
                "month":  r["_ym"].month,
                "fr":     fr,
                "un_sol": int(r["un_sol"]),
                "un_asig":int(r["un_asig"]),
                "bo_un":  int(r["bo_un"]),
                "bo_val": float(r["bo_val"]),
                "val_tot":float(r["val_tot"]),
                "val_fac":float(r["val_fac"]),
            })
        return rows

    monthly_all = _monthly_rows(dfw)[-12:]  # full 12 months for trend chart

    # Weekly all — last 12 weeks for chart (no week filter)
    _all_wkeys = {w["key"] for w in available_weeks}
    _dfw_wa    = dfw[dfw["_wmon_s"].isin(_all_wkeys)]
    _wgrp_all  = _dfw_wa.groupby("_wmon_s").agg(
        un_sol  =("un_solicitadas",  "sum"),
        un_asig =("un_asignadas",    "sum"),
        bo_val  =("bo_valorizado",   "sum"),
        val_tot =("valor_total",     "sum"),
        val_fac =("valor_facturado", "sum"),
    ).reset_index().sort_values("_wmon_s")
    weekly_all_list = []
    for _, _wr in _wgrp_all.iterrows():
        _wk   = _wr["_wmon_s"]
        _wmon = _date.fromisoformat(_wk)
        _wend = _wmon + _td(days=6)
        _wsol = float(_wr["un_sol"])
        _wfr  = round(float(_wr["un_asig"]) / _wsol * 100, 1) if _wsol > 0 else 0.0
        weekly_all_list.append({
            "key":         _wk,
            "label":       f"{_dia_mes_corto(_wmon)} – {_dia_mes_corto(_wend)}",
            "label_short": _dia_mes_corto(_wmon),
            "fr":          _wfr,
            "un_sol":      int(_wr["un_sol"]),
            "un_asig":     int(_wr["un_asig"]),
            "bo_val":      float(_wr["bo_val"]),
            "val_tot":     float(_wr["val_tot"]),
            "val_fac":     float(_wr["val_fac"]),
        })

    # ── Apply month filter — "YYYY-M" pairs ────────────────────
    # months_param format: "2026-6,2025-11" (year-month pairs)
    sel_ym = set()
    if months_param:
        for tok in months_param.split(","):
            tok = tok.strip()
            if "-" in tok:
                parts = tok.split("-")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    sel_ym.add((int(parts[0]), int(parts[1])))
    elif month and month.isdigit():
        # Legacy: single month number, combine with year filter
        mo = int(month)
        for yr in dfw["_year"].unique():
            sel_ym.add((int(yr), mo))

    if sel_ym:
        _pairs = list(zip(dfw["_year"].astype(int), dfw["_month"].astype(int)))
        dfw_m = dfw[[ym in sel_ym for ym in _pairs]]
    else:
        dfw_m = dfw

    monthly = _monthly_rows(dfw_m)  # filtered months (for KPIs, table)

    # ── Week filter ─────────────────────────────────────────────
    weeks_param = request.args.get("weeks", "").strip()
    sel_weeks   = set()
    if weeks_param:
        for tok in weeks_param.split(","):
            sel_weeks.add(tok.strip())

    dfw_w = dfw[dfw["_wmon_s"].isin(sel_weeks)] if sel_weeks else dfw

    _wgrp = dfw_w.groupby("_wmon_s").agg(
        un_sol  =("un_solicitadas",  "sum"),
        un_asig =("un_asignadas",    "sum"),
        bo_val  =("bo_valorizado",   "sum"),
        val_tot =("valor_total",     "sum"),
        val_fac =("valor_facturado", "sum"),
    ).reset_index().sort_values("_wmon_s")

    weekly = []
    for _, _wr in _wgrp.iterrows():
        _wk   = _wr["_wmon_s"]
        _wmon = _date.fromisoformat(_wk)
        _wend = _wmon + _td(days=6)
        _wsol = float(_wr["un_sol"])
        _wfr  = round(float(_wr["un_asig"]) / _wsol * 100, 1) if _wsol > 0 else 0.0
        weekly.append({
            "key":         _wk,
            "label":       f"{_dia_mes_corto(_wmon)} – {_dia_mes_corto(_wend)}",
            "label_short": _dia_mes_corto(_wmon),
            "fr":          _wfr,
            "un_sol":      int(_wr["un_sol"]),
            "un_asig":     int(_wr["un_asig"]),
            "bo_val":      float(_wr["bo_val"]),
            "val_tot":     float(_wr["val_tot"]),
            "val_fac":     float(_wr["val_fac"]),
        })

    # ── By-client aggregation (filtered period) ─────────────────
    cgrp = dfw_m.groupby("cliente").agg(
        un_sol    =("un_solicitadas",  "sum"),
        un_asig   =("un_asignadas",    "sum"),
        bo_val    =("bo_valorizado",   "sum"),
        val_tot   =("valor_total",     "sum"),
        val_fac   =("valor_facturado", "sum"),
        despachos =("oc",              "nunique"),
    ).reset_index()
    by_client = []
    for _, r in cgrp.iterrows():
        sol = float(r["un_sol"])
        fr  = round(float(r["un_asig"]) / sol * 100, 1) if sol > 0 else 0.0
        by_client.append({
            "cliente":   r["cliente"],
            "fr":        fr,
            "val_tot":   float(r["val_tot"]),
            "val_fac":   float(r["val_fac"]),
            "bo_val":    float(r["bo_val"]),
            "despachos": int(r["despachos"]),
        })
    by_client.sort(key=lambda x: x["fr"], reverse=True)

    # ── By-product aggregation (solo cuando hay filtro de cliente) ──
    by_product = []
    if cliente:
        pgrp = dfw_m.groupby("producto").agg(
            un_sol  =("un_solicitadas",  "sum"),
            un_asig =("un_asignadas",    "sum"),
            bo_val  =("bo_valorizado",   "sum"),
            val_tot =("valor_total",     "sum"),
            val_fac =("valor_facturado", "sum"),
        ).reset_index()

        # Detalle por producto: filas de despacho ordenadas más reciente primero
        prod_detail = {}
        for prod, grp in dfw_m.groupby("producto"):
            grp_s = grp.sort_values("fecha_despacho", ascending=False)
            detail_rows = []
            for _, row in grp_s.iterrows():
                u_sol = int(row["un_solicitadas"])
                u_asig= int(row["un_asignadas"])
                fr_row = round(u_asig / u_sol * 100, 1) if u_sol > 0 else 0.0
                detail_rows.append({
                    "oc":         str(row["oc"]),
                    "fecha":      row["fecha_despacho"].strftime("%d/%m/%Y"),
                    "un_sol":     u_sol,
                    "un_asig":    u_asig,
                    "bo_un":      int(row.get("bo_un", 0)),
                    "comentario": (_s(row.get("comentarios")) if fr_row < 100 else ""),
                    "fr":         fr_row,
                })
            prod_detail[prod] = detail_rows

        for _, r in pgrp.iterrows():
            sol = float(r["un_sol"])
            fr  = round(float(r["un_asig"]) / sol * 100, 1) if sol > 0 else 0.0
            by_product.append({
                "producto": r["producto"],
                "fr":       fr,
                "val_sol":  float(r["val_tot"]),
                "val_asig": float(r["val_fac"]),
                "bo_val":   float(r["bo_val"]),
                "rows":     prod_detail.get(r["producto"], []),
            })
        by_product.sort(key=lambda x: x["fr"])  # peor a mejor (ascendente)

    # ── By-client weekly ────────────────────────────────────────
    _cgrp_w = dfw_w.groupby("cliente").agg(
        un_sol   =("un_solicitadas",  "sum"),
        un_asig  =("un_asignadas",    "sum"),
        bo_val   =("bo_valorizado",   "sum"),
        val_tot  =("valor_total",     "sum"),
        val_fac  =("valor_facturado", "sum"),
        despachos=("oc",              "nunique"),
    ).reset_index()
    by_client_w = []
    for _, _r in _cgrp_w.iterrows():
        _s = float(_r["un_sol"])
        _f = round(float(_r["un_asig"]) / _s * 100, 1) if _s > 0 else 0.0
        by_client_w.append({
            "cliente":   _r["cliente"],
            "fr":        _f,
            "val_tot":   float(_r["val_tot"]),
            "val_fac":   float(_r["val_fac"]),
            "bo_val":    float(_r["bo_val"]),
            "despachos": int(_r["despachos"]),
        })
    by_client_w.sort(key=lambda x: x["fr"], reverse=True)

    # ── By-product weekly (solo cuando hay filtro de cliente) ───
    by_product_w = []
    if cliente:
        _pgrp_w = dfw_w.groupby("producto").agg(
            un_sol  =("un_solicitadas",  "sum"),
            un_asig =("un_asignadas",    "sum"),
            bo_val  =("bo_valorizado",   "sum"),
            val_tot =("valor_total",     "sum"),
            val_fac =("valor_facturado", "sum"),
        ).reset_index()
        _prod_detail_w = {}
        for _prod, _grp in dfw_w.groupby("producto"):
            _grp_s = _grp.sort_values("fecha_despacho", ascending=False)
            _drows = []
            for _, _row in _grp_s.iterrows():
                _us = int(_row["un_solicitadas"])
                _ua = int(_row["un_asignadas"])
                _fr_r = round(_ua / _us * 100, 1) if _us > 0 else 0.0
                _drows.append({
                    "oc":         str(_row["oc"]),
                    "fecha":      _row["fecha_despacho"].strftime("%d/%m/%Y"),
                    "un_sol":     _us,
                    "un_asig":    _ua,
                    "bo_un":      int(_row.get("bo_un", 0)),
                    "comentario": (str(_row.get("comentarios", "") or "")
                                   if _fr_r < 100 else ""),
                    "fr":         _fr_r,
                })
            _prod_detail_w[_prod] = _drows
        for _, _r in _pgrp_w.iterrows():
            _s = float(_r["un_sol"])
            _f = round(float(_r["un_asig"]) / _s * 100, 1) if _s > 0 else 0.0
            by_product_w.append({
                "producto": _r["producto"],
                "fr":       _f,
                "val_sol":  float(_r["val_tot"]),
                "val_asig": float(_r["val_fac"]),
                "bo_val":   float(_r["bo_val"]),
                "rows":     _prod_detail_w.get(_r["producto"], []),
            })
        by_product_w.sort(key=lambda x: x["fr"])

    # ── KPIs semanales ──────────────────────────────────────────
    kpis_w = {}
    if weekly:
        _tw_sol = sum(w["un_sol"]  for w in weekly)
        _tw_asig= sum(w["un_asig"] for w in weekly)
        _tw_val = sum(w["val_tot"] for w in weekly)
        _tw_fac = sum(w["val_fac"] for w in weekly)
        _tw_bo  = sum(w["bo_val"]  for w in weekly)
        _tw_fr  = round(_tw_asig / _tw_sol * 100, 1) if _tw_sol > 0 else 0.0

        _w_period = (f"{weekly[0]['label']} – {weekly[-1]['label']}"
                     if len(weekly) > 1 else weekly[0]["label"])

        _first_wkey   = sorted(sel_weeks)[0] if sel_weeks else None
        _prev_fr_w    = None
        _prev_label_w = None
        if _first_wkey:
            _prev_wmon    = _date.fromisoformat(_first_wkey) - _td(weeks=1)
            _prev_wkey    = _prev_wmon.strftime("%Y-%m-%d")
            _prev_wend    = _prev_wmon + _td(days=6)
            _prev_label_w = f"{_dia_mes_corto(_prev_wmon)} – {_dia_mes_corto(_prev_wend)}"
            _prev_entry   = next((w for w in weekly_all_list if w["key"] == _prev_wkey), None)
            if _prev_entry:
                _prev_fr_w = _prev_entry["fr"]
            else:
                _d_pw = dfw[dfw["_wmon_s"] == _prev_wkey]
                if not _d_pw.empty:
                    _ps = float(_d_pw["un_solicitadas"].sum())
                    if _ps > 0:
                        _prev_fr_w = round(float(_d_pw["un_asignadas"].sum()) / _ps * 100, 1)

        _variacion_w  = round(_tw_fr - _prev_fr_w, 1) if _prev_fr_w is not None else None
        _is_cur_week  = _cur_monday.strftime("%Y-%m-%d") in {w["key"] for w in weekly}

        kpis_w = {
            "fr":            _tw_fr,
            "is_cur_week":   _is_cur_week,
            "fr_sem_ant":    _prev_fr_w,
            "label_sem_ant": _prev_label_w,
            "variacion":     _variacion_w,
            "val_tot":       _tw_val,
            "val_fac":       _tw_fac,
            "bo_val":        _tw_bo,
            "bo_pct":        round(_tw_bo / _tw_val * 100, 1) if _tw_val > 0 else 0,
            "label_periodo": _w_period,
        }

    # ── KPIs (aggregated for selected period) ───────────────────
    kpis = {}
    if monthly:
        tot_sol  = sum(m["un_sol"]  for m in monthly)
        tot_asig = sum(m["un_asig"] for m in monthly)
        tot_val  = sum(m["val_tot"] for m in monthly)
        tot_fac  = sum(m["val_fac"] for m in monthly)
        tot_bo   = sum(m["bo_val"]  for m in monthly)
        fr_per   = round(tot_asig / tot_sol * 100, 1) if tot_sol > 0 else 0.0

        period_label = (f"{monthly[0]['label']} – {monthly[-1]['label']}"
                        if len(monthly) > 1 else monthly[0]["label"])

        # FR mes anterior = mes inmediatamente anterior al primer mes seleccionado
        first_yr = monthly[0]["year"]
        first_mo = monthly[0]["month"]
        prev_mo  = first_mo - 1
        prev_yr  = first_yr
        if prev_mo == 0:
            prev_mo = 12
            prev_yr -= 1

        prev_fr    = None
        prev_label = None
        # Search in monthly_all (full 12-month trend) first
        for m in monthly_all:
            if m["year"] == prev_yr and m["month"] == prev_mo:
                prev_fr    = m["fr"]
                prev_label = m["label"]
                break
        # If not there, compute directly from the full (non-month-filtered) dataframe
        if prev_fr is None:
            d_prev = dfw[(dfw["_year"] == prev_yr) & (dfw["_month"] == prev_mo)]
            if not d_prev.empty:
                _sol = float(d_prev["un_solicitadas"].sum())
                if _sol > 0:
                    prev_fr    = round(float(d_prev["un_asignadas"].sum()) / _sol * 100, 1)
                    prev_label = f"{_MESES_CORTO[prev_mo]} {prev_yr}"

        variacion = round(fr_per - prev_fr, 1) if prev_fr is not None else None

        # is_mtd: True si la selección incluye el mes en curso
        is_mtd = any(m["year"] == _today.year and m["month"] == _today.month
                     for m in monthly)

        kpis = {
            "fr_mtd":        fr_per,
            "is_mtd":        is_mtd,
            "fr_mes_ant":    prev_fr,
            "label_mes_ant": prev_label,
            "variacion":     variacion,
            "val_tot":       tot_val,
            "val_fac":       tot_fac,
            "bo_val":        tot_bo,
            "bo_pct":        round(tot_bo / tot_val * 100, 1) if tot_val > 0 else 0,
            "label_mes":     period_label,
        }

    # ── Ranking histórico (based on full trend) ──────────────────
    ranking = {}
    if monthly_all:
        mejor = max(monthly_all, key=lambda x: x["fr"])
        peor  = min(monthly_all, key=lambda x: x["fr"])
        ranking = {"mejor": {"label": mejor["label"], "fr": mejor["fr"]},
                   "peor":  {"label": peor["label"],  "fr": peor["fr"]}}

    return jsonify({
        "clientes":         clientes_list,
        "years":            years_list,
        "available_months": available_months,
        "available_weeks":  available_weeks,
        "monthly_all":      monthly_all,
        "monthly":          monthly,
        "weekly_all":       weekly_all_list,
        "weekly":           weekly,
        "kpis":             kpis,
        "kpis_w":           kpis_w,
        "ranking":          ranking,
        "by_client":        by_client,
        "by_product":       by_product,
        "by_client_w":      by_client_w,
        "by_product_w":     by_product_w,
    })


@app.route("/api/fr-historico/consulta")
@_login_required
def api_fr_consulta():
    """Buscador de OCs con detalle a nivel producto."""
    df = get_df()
    if df is None or df.empty:
        return jsonify({"ocs": [], "detail": [], "clientes": []})

    oc_search   = request.args.get("oc",          "").strip()
    cliente     = request.args.get("cliente",     "").strip()
    fecha_desde = request.args.get("fecha_desde", "").strip()
    fecha_hasta = request.args.get("fecha_hasta", "").strip()

    clientes_list = sorted(df["cliente"].dropna().unique().tolist())
    dfw = df.dropna(subset=["fecha_despacho"]).copy()

    # Aplicar filtros
    if cliente:
        dfw = dfw[dfw["cliente"] == cliente]
    if fecha_desde:
        try:
            dfw = dfw[dfw["fecha_despacho"] >= pd.Timestamp(fecha_desde)]
        except Exception:
            pass
    if fecha_hasta:
        try:
            dfw = dfw[dfw["fecha_despacho"] <= pd.Timestamp(fecha_hasta)]
        except Exception:
            pass
    if oc_search:
        dfw = dfw[dfw["oc"].astype(str).str.contains(oc_search, case=False, na=False)]

    # Agrupar por OC para tabla resumen
    oc_grp = dfw.groupby(["oc", "cliente", "fecha_despacho"]).agg(
        un_sol  =("un_solicitadas",  "sum"),
        un_asig =("un_asignadas",    "sum"),
        val_tot =("valor_total",     "sum"),
        val_fac =("valor_facturado", "sum"),
    ).reset_index()

    # Estado por OC: CERRADA solo si todas las líneas son CERRADA
    estado_por_oc = {}
    if "estado" in dfw.columns:
        for oc_key, grp in dfw.groupby("oc"):
            estados = grp["estado"].str.upper().unique()
            estado_por_oc[str(oc_key)] = "CERRADA" if list(estados) == ["CERRADA"] else "PENDIENTE"

    ocs = []
    for _, r in oc_grp.sort_values("fecha_despacho", ascending=False).iterrows():
        sol = float(r["un_sol"])
        fr  = round(float(r["un_asig"]) / sol * 100, 1) if sol > 0 else 0.0
        oc_key = str(r["oc"])
        ocs.append({
            "oc":      oc_key,
            "cliente": r["cliente"],
            "fecha":   r["fecha_despacho"].strftime("%d/%m/%Y"),
            "val_tot": float(r["val_tot"]),
            "val_fac": float(r["val_fac"]),
            "fr":      fr,
            "pendiente": estado_por_oc.get(oc_key, "CERRADA") != "CERRADA",
        })

    # Detalle por producto cuando hay OC exacta
    detail = []
    if oc_search:
        dfw_oc = dfw[dfw["oc"].astype(str).str.lower() == oc_search.lower()]
        for _, r in dfw_oc.sort_values("fecha_despacho").iterrows():
            us = int(r["un_solicitadas"])
            ua = int(r["un_asignadas"])
            fr_r = round(ua / us * 100, 1) if us > 0 else 0.0
            detail.append({
                "producto":   r["producto"],
                "un_sol":     us,
                "un_asig":    ua,
                "bo_un":      int(r.get("bo_un", 0)),
                "val_tot":    float(r["valor_total"]),
                "val_fac":    float(r["valor_facturado"]),
                "bo_val":     float(r.get("bo_valorizado", 0)),
                "fr":         fr_r,
                "comentario": (_s(r.get("comentarios")) if fr_r < 100 else ""),
            })

    return jsonify({"ocs": ocs[:200], "detail": detail, "clientes": clientes_list})


@app.route("/api/fr-historico/consulta/<path:oc_key>")
@_login_required
def api_fr_consulta_oc(oc_key):
    """Detalle a nivel producto para una OC específica."""
    df = get_df()
    if df is None or df.empty:
        return jsonify({"detail": [], "oc": oc_key})

    dfw    = df.dropna(subset=["fecha_despacho"]).copy()
    cliente_filter = request.args.get("cliente", "").strip()
    dfw_oc = dfw[dfw["oc"].astype(str) == oc_key]
    if cliente_filter:
        dfw_oc = dfw_oc[dfw_oc["cliente"] == cliente_filter]

    detail = []
    for _, r in dfw_oc.sort_values("fecha_despacho").iterrows():
        us = int(r["un_solicitadas"])
        ua = int(r["un_asignadas"])
        fr_r = round(ua / us * 100, 1) if us > 0 else 0.0
        detail.append({
            "producto":   r["producto"],
            "un_sol":     us,
            "un_asig":    ua,
            "bo_un":      int(r.get("bo_un", 0)),
            "val_tot":    float(r["valor_total"]),
            "val_fac":    float(r["valor_facturado"]),
            "bo_val":     float(r.get("bo_valorizado", 0)),
            "fr":         fr_r,
            "comentario": (_s(r.get("comentarios")) if fr_r < 100 else ""),
        })

    meta = {}
    if not dfw_oc.empty:
        row0 = dfw_oc.iloc[0]
        meta = {
            "cliente": row0["cliente"],
            "fecha":   row0["fecha_despacho"].strftime("%d/%m/%Y"),
        }

    return jsonify({"detail": detail, "oc": oc_key, "meta": meta})


@app.route("/api/fr-historico/semana/<path:week_key>")
@_login_required
def api_fr_semana(week_key):
    """SKU detail para una semana específica."""
    df      = get_df()
    cliente = request.args.get("cliente", "").strip()
    if df is None or df.empty:
        return jsonify({"rows": []})

    dfw = df.dropna(subset=["fecha_despacho"]).copy()
    if cliente:
        dfw = dfw[dfw["cliente"] == cliente]

    dfw["_yw"]  = dfw["fecha_despacho"].dt.to_period("W").astype(str)
    dfw_week    = dfw[dfw["_yw"] == week_key]
    dfw_bo      = dfw_week[dfw_week["bo_un"] > 0].copy()

    dfw_bo["fill_rate"] = np.where(
        dfw_bo["un_solicitadas"] > 0,
        (dfw_bo["un_asignadas"] / dfw_bo["un_solicitadas"] * 100).round(1),
        100.0,
    )

    rows = []
    for _, r in dfw_bo.iterrows():
        fd  = r.get("fecha_despacho")
        yw  = r.get("_yw", "")
        fr  = float(r.get("fill_rate", 0))
        rows.append({
            "cliente":        str(r.get("cliente", "")),
            "semana":         yw,
            "oc":             str(r.get("oc", "")),
            "producto":       str(r.get("producto", "")),
            "un_solicitadas": int(r.get("un_solicitadas", 0)),
            "un_asignadas":   int(r.get("un_asignadas", 0)),
            "bo_un":          int(r.get("bo_un", 0)),
            "fill_rate":      fr,
            "fr_chip":        fr_chip_class(fr),
            "bo_valorizado":  float(r.get("bo_valorizado", 0) or 0),
            "comentarios":    _s(r.get("comentarios")),
        })

    return jsonify({"rows": rows, "week": week_key})


@app.route("/api/export/fr-historico-csv")
@_login_required
def api_export_fr_historico_csv():
    import csv, io as _io
    df      = get_df()
    tipo    = request.args.get("tipo",    "mensual")
    cliente = request.args.get("cliente", "").strip()
    year    = request.args.get("year",    "").strip()
    month   = request.args.get("month",   "").strip()
    week    = request.args.get("week",    "").strip()

    dfw = df.dropna(subset=["fecha_despacho"]).copy() if df is not None else pd.DataFrame()
    if cliente: dfw = dfw[dfw["cliente"] == cliente]
    if year:    dfw = dfw[dfw["fecha_despacho"].dt.year  == int(year)]
    if month:   dfw = dfw[dfw["fecha_despacho"].dt.month == int(month)]

    output  = _io.StringIO()
    if tipo == "sku" and week:
        dfw["_yw"] = dfw["fecha_despacho"].dt.to_period("W").astype(str)
        dfw = dfw[(dfw["_yw"] == week) & (dfw["bo_un"] > 0)]
        fields = ["cliente","oc","producto","un_solicitadas","un_asignadas","bo_un","bo_valorizado","comentarios"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for _, r in dfw.iterrows():
            writer.writerow({f: r.get(f, "") for f in fields})
    else:
        fields = ["cliente","oc","fecha_despacho","producto","un_solicitadas","un_asignadas",
                  "bo_un","bo_valorizado","valor_total","valor_facturado"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for _, r in dfw.iterrows():
            fd = r.get("fecha_despacho")
            writer.writerow({
                "cliente": r.get("cliente",""), "oc": r.get("oc",""),
                "fecha_despacho": _fmt_date(fd),
                "producto": r.get("producto",""),
                "un_solicitadas": int(r.get("un_solicitadas",0)),
                "un_asignadas":   int(r.get("un_asignadas",0)),
                "bo_un":          int(r.get("bo_un",0)),
                "bo_valorizado":  float(r.get("bo_valorizado",0) or 0),
                "valor_total":    float(r.get("valor_total",0) or 0),
                "valor_facturado":float(r.get("valor_facturado",0) or 0),
            })

    from flask import Response
    return Response(
        "﻿" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment;filename=spot_fr_historico_{tipo}_{date.today()}.csv"}
    )


@app.route("/api/export/backorder-csv")
@_login_required
def api_export_backorder_csv():
    """Exporta el detalle de BO como CSV (respeta filtros query params)."""
    import csv, io as _io
    df = get_bo_detail_df()

    rows = []
    for _, r in df.iterrows():
        fd = r.get("fecha_despacho")
        rows.append({
            "Cliente":           str(r.get("cliente", "")),
            "OC":                str(r.get("oc", "")),
            "Fecha Despacho":    _fmt_date(fd),
            "Producto":          str(r.get("producto", "")),
            "UN Solicitadas":    int(r.get("un_solicitadas", 0)),
            "UN Asignadas":      int(r.get("un_asignadas", 0)),
            "UN Pendientes":     int(r.get("bo_un", 0)),
            "Fill Rate SKU (%)": float(r.get("fill_rate", 0)),
            "BO Valorizado":     float(r.get("bo_valorizado", 0) or 0),
            "Comentario":        _s(r.get("comentarios")),
            "Motivo BO":         _s(r.get("motivo_bo")),
        })

    # Aplicar los mismos filtros
    cliente    = request.args.get("cliente",    "").strip().lower()
    oc_f       = request.args.get("oc",         "").strip().lower()
    producto   = request.args.get("producto",   "").strip().lower()
    fecha_from = request.args.get("fecha_from", "").strip()
    fecha_to   = request.args.get("fecha_to",   "").strip()
    q          = request.args.get("q",          "").strip().lower()

    if cliente:
        rows = [r for r in rows if cliente in r["Cliente"].lower()]
    if oc_f:
        rows = [r for r in rows if oc_f in r["OC"].lower()]
    if producto:
        rows = [r for r in rows if producto in r["Producto"].lower()]
    if q:
        rows = [r for r in rows if (
            q in r["Cliente"].lower() or
            q in r["OC"].lower() or
            q in r["Producto"].lower()
        )]

    output = _io.StringIO()
    fields = list(rows[0].keys()) if rows else ["Cliente","OC","Fecha Despacho","Producto",
        "UN Solicitadas","UN Asignadas","UN Pendientes","Fill Rate SKU (%)","BO Valorizado",
        "Comentario","Motivo BO"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

    from flask import Response
    return Response(
        "﻿" + output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment;filename=spot_backorder_detalle_{date.today()}.csv"}
    )


@app.route("/api/export/csv")
@_login_required
def api_export_csv():
    """Exporta OCs pendientes como CSV."""
    import csv
    import io
    pending = get_pending_df()
    rows    = _pending_to_json(pending)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "cliente","oc","fecha_despacho","estado","fill_rate","bo_un","un_solicitadas","comentarios"
    ])
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k,"") for k in writer.fieldnames})

    from flask import Response
    return Response(
        "﻿" + output.getvalue(),   # BOM para Excel
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment;filename=spot_oc_pendientes_{date.today()}.csv"}
    )


@app.route("/api/fr-mes")
@_login_required
def api_fr_mes():
    """KPIs y OCs cerradas MTD con detalle SKU — Fill Rate Mes."""
    df = get_df()
    if df is None or df.empty:
        return jsonify({"kpis": {}, "clientes": [], "ocs": []})

    from kpi_calculator import semaforo_fr, fr_chip_class, _CLIENTES_VENTA_PERDIDA

    today   = pd.Timestamp(date.today())
    mes_ini = today.replace(day=1)
    mes_fin = mes_ini + pd.offsets.MonthEnd(1)
    mes_label = _mes_largo(today)

    # Mes anterior
    ant_ini = (mes_ini - pd.DateOffset(months=1)).replace(day=1)
    ant_fin = ant_ini + pd.offsets.MonthEnd(1)
    ant_label = _mes_largo(ant_ini)

    dfw = df.dropna(subset=["fecha_despacho"]).copy()
    cerradas = dfw[dfw["estado"].str.upper() == "CERRADA"]

    df_mes = cerradas[(cerradas["fecha_despacho"] >= mes_ini) & (cerradas["fecha_despacho"] <= mes_fin)]
    df_ant = cerradas[(cerradas["fecha_despacho"] >= ant_ini) & (cerradas["fecha_despacho"] <= ant_fin)]

    clientes_list = sorted(df_mes["cliente"].dropna().unique().tolist()) if not df_mes.empty else []

    def _fr_cerradas(df_scope):
        sol  = float(df_scope["un_solicitadas"].sum())
        asig = float(df_scope["un_asignadas"].sum())
        return round(asig / sol * 100, 1) if sol > 0 else None

    # FR mes anterior (cerradas)
    fr_ant = _fr_cerradas(df_ant)

    if df_mes.empty:
        return jsonify({
            "kpis": {"fr_mtd": None, "fr_mtd_color": "red",
                     "venta_facturada_mtd": 0, "venta_perdida_mtd": 0,
                     "n_ocs_despachadas": 0, "mes_label": mes_label,
                     "fr_ant": fr_ant, "ant_label": ant_label, "variacion": None},
            "clientes": clientes_list,
            "ocs": [],
        })

    def _build_kpis(df_scope):
        sol  = float(df_scope["un_solicitadas"].sum())
        asig = float(df_scope["un_asignadas"].sum())
        fr   = round(asig / sol * 100, 1) if sol > 0 else None
        fac  = float(df_scope["valor_facturado"].sum())
        cl   = df_scope["cliente"].str.lower().fillna("")
        mask = cl.apply(lambda c: any(kw in c for kw in _CLIENTES_VENTA_PERDIDA))
        perdida = float(df_scope.loc[mask, "bo_valorizado"].sum())
        variacion = round(fr - fr_ant, 1) if (fr is not None and fr_ant is not None) else None
        return {
            "fr_mtd":              fr,
            "fr_mtd_color":        semaforo_fr(fr) if fr is not None else "red",
            "venta_facturada_mtd": round(fac, 0),
            "venta_perdida_mtd":   round(perdida, 0),
            "n_ocs_despachadas":   int(df_scope["oc"].nunique()),
            "mes_label":           mes_label,
            "fr_ant":              fr_ant,
            "ant_label":           ant_label,
            "variacion":           variacion,
        }

    kpis = _build_kpis(df_mes)

    # ── OCs con SKU detail ─────────────────────────────────────────
    ocs = []
    for (oc_id, cliente), grp in df_mes.groupby(["oc", "cliente"]):
        o_sol   = float(grp["un_solicitadas"].sum())
        o_asig  = float(grp["un_asignadas"].sum())
        o_fr    = round(o_asig / o_sol * 100, 1) if o_sol > 0 else 100.0
        o_fac   = float(grp["valor_facturado"].sum())
        o_nofac = float(grp["bo_valorizado"].sum())
        fd      = grp["fecha_despacho"].dropna()
        fd_str  = fd.iloc[0].strftime("%d/%m/%Y") if not fd.empty else "—"
        fd_sort = fd.iloc[0].strftime("%Y%m%d") if not fd.empty else "99999999"

        skus = []
        for _, row in grp.iterrows():
            s_sol  = int(row.get("un_solicitadas", 0) or 0)
            s_asig = int(row.get("un_asignadas",   0) or 0)
            s_bo   = int(row.get("bo_un",          0) or 0)
            s_fr   = round(s_asig / s_sol * 100, 1) if s_sol > 0 else 100.0
            coment = str(row.get("comentarios", "") or "").strip()
            if coment in ("nan", "None"): coment = ""
            motivo = str(row.get("motivo_bo", "") or "").strip()
            if motivo in ("nan", "None"): motivo = ""
            nota = (coment or motivo) if s_bo > 0 else ""
            cat_arbol = str(row.get("categoria_arbol", "") or "").strip()
            if cat_arbol in ("nan", "None"): cat_arbol = ""
            skus.append({
                "producto":       str(row.get("producto", "") or ""),
                "ean":            str(row.get("ean_spot",  "") or "").replace(".0",""),
                "categoria":      str(row.get("categoria", "") or ""),
                "categoria_arbol": cat_arbol,
                "sol":            s_sol,
                "asig":           s_asig,
                "bo":             s_bo,
                "bo_val":         round(float(row.get("bo_valorizado", 0) or 0), 0),
                "fr":             s_fr,
                "fr_color":       fr_chip_class(s_fr),
                "comentario":     nota,
            })

        ocs.append({
            "oc":           str(oc_id),
            "cliente":      str(cliente),
            "fecha_despacho": fd_str,
            "_fd_sort":     fd_sort,
            "fr":           o_fr,
            "fr_color":     fr_chip_class(o_fr),
            "val_fac":      round(o_fac, 0),
            "val_no_fac":   round(o_nofac, 0),
            "skus":         skus,
        })

    ocs.sort(key=lambda x: x["_fd_sort"])
    for o in ocs: del o["_fd_sort"]

    return jsonify({"kpis": kpis, "clientes": clientes_list, "ocs": ocs})


@app.route("/api/spotia", methods=["POST"])
@_login_required
def api_spotia():
    """Asistente conversacional SpotIA."""
    body        = request.json or {}
    question    = body.get("question", "").strip()
    mode        = body.get("mode", "chat")
    cliente_ctx = body.get("cliente", "").strip()

    if not question and mode == "chat":
        return jsonify({"error": "Sin pregunta"}), 400

    df = get_df()
    # Modos predefinidos usan contexto liviano (~2.000 tokens) para respetar rate limits
    if mode in ("executive", "comercial", "riesgos"):
        context = build_light_context(df, cliente_ctx)
    else:
        context = build_context(df, cliente_ctx)
    answer = ask_spotia(question, context, mode, cliente_ctx)
    return jsonify({"answer": answer})


@app.route("/api/spotia/clientes")
@_login_required
def api_spotia_clientes():
    """Lista de clientes para selector del asistente."""
    df = get_df()
    if df is None:
        return jsonify([])
    return jsonify(sorted(df["cliente"].dropna().unique().tolist()))


# ── TRACKING PT ───────────────────────────────────────────────────────────────
_TRACKING_PT_FOLDER = os.getenv(
    "TRACKING_PT_LOCAL_FOLDER",
    r"C:\Users\FranciscaLagos\OneDrive - Spot Essence\Escritorio\Tracking Diario"
)
# Fallback fijo, solo se usa si la carpeta local no existe o no tiene .xlsx
_TRACKING_PT_FILE = os.getenv(
    "TRACKING_PT_FILE",
    r"C:\Users\FranciscaLagos\OneDrive - Spot Essence\Escritorio\Tracking Diario\(25) Tracking Diario 24-06-2026.xlsx"
)
_tracking_pt_cache: dict | None = None


def _latest_local_tracking_pt_file() -> str:
    """Retorna la ruta del .xlsx con fecha de modificación más reciente en la carpeta local de Tracking Diario."""
    if os.path.isdir(_TRACKING_PT_FOLDER):
        candidates = [
            os.path.join(_TRACKING_PT_FOLDER, f)
            for f in os.listdir(_TRACKING_PT_FOLDER)
            if f.lower().endswith(".xlsx") and not f.startswith("~$")
        ]
        if candidates:
            return max(candidates, key=os.path.getmtime)
    return _TRACKING_PT_FILE

def _load_tracking_pt_source() -> tuple["pd.DataFrame", str, str]:
    """
    Carga el DataFrame de Tracking PT desde la carpeta de SharePoint
    (siempre el .xlsx más reciente). Si falla (sin credenciales, sin
    consentimiento, etc.) cae de vuelta al archivo local de respaldo.
    Retorna (df, file_name, file_modified_str).
    """
    import io
    try:
        from graph_client import download_latest_from_folder
        content, file_name, modified_iso = download_latest_from_folder(
            Config.TRACKING_PT_FOLDER_URL, name_contains="Tracking Diario"
        )
        df = pd.read_excel(io.BytesIO(content), sheet_name="Tracking PT", header=6)
        file_modified = "—"
        if modified_iso:
            try:
                file_modified = pd.Timestamp(modified_iso).strftime("%d-%b-%Y %H:%M")
            except Exception:
                file_modified = modified_iso
        return df, file_name, file_modified
    except Exception as e:
        log.warning(f"No se pudo leer Tracking PT desde SharePoint ({e}); usando archivo local de respaldo")

    local_path = _latest_local_tracking_pt_file()

    import shutil, tempfile
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        shutil.copy2(local_path, tmp.name)
        tmp_path = tmp.name
    df = pd.read_excel(tmp_path, sheet_name="Tracking PT", header=6)
    os.remove(tmp_path)
    file_name = os.path.basename(local_path)
    try:
        file_modified = datetime.fromtimestamp(os.path.getmtime(local_path)).strftime("%d-%b-%Y %H:%M")
    except OSError:
        file_modified = "—"
    return df, file_name, file_modified


def _load_tracking_pt() -> dict:
    global _tracking_pt_cache
    if _tracking_pt_cache is not None:
        return _tracking_pt_cache

    df, file_name, file_modified = _load_tracking_pt_source()

    def _clean(v):
        if v is None: return ""
        try:
            if pd.isna(v): return ""
        except: pass
        s = str(v).strip()
        return "" if s.lower() in {"nan","none","null","n/a","na","-"} else s

    def _num(v, pct=False):
        try:
            f = float(v)
            return None if pd.isna(f) else (round(f * 100, 1) if pct else f)
        except: return None

    # Columnas de fecha disponibles
    today     = pd.Timestamp(date.today())
    date_cols = [c for c in df.columns if hasattr(c, "year")]

    # Mes actual → forecast
    fcst_col   = next((c for c in date_cols if c.year == today.year and c.month == today.month), None)
    fcst_label = _mes_corto(today) if fcst_col is not None else ""

    # Últimos 3 meses cerrados (anteriores al mes actual)
    past_cols = [c for c in date_cols if (c.year, c.month) < (today.year, today.month)]
    last3_cols = past_cols[-3:] if len(past_cols) >= 3 else past_cols
    last3_labels = [_mes_corto(c) for c in last3_cols]

    rows = []
    for _, r in df.iterrows():
        ean = _clean(r.get("EAN",""))
        if not ean: continue
        if ean.endswith(".0"): ean = ean[:-2]

        fcst_mes = _num(r[fcst_col]) if fcst_col is not None else None
        meses_ant = [_num(r[c]) for c in last3_cols]

        rows.append({
            "ean":          ean,
            "producto":     _clean(r.get("PRODUCTO","")),
            "marca":        _clean(r.get("Marca","")),
            "categoria":    _clean(r.iloc[3]),
            "aroma":        _clean(r.iloc[4]),
            "abc":          _clean(r.get("ABC","")),
            "meses_ant":    meses_ant,
            "venta_mtd":    _num(r.get("VENTA MTD")),
            "cumplimiento": _num(r.get("CUMPLIMIENTO"), pct=True),
            "fa":           _num(r.get("FORECAST ACCURACY"), pct=True),
            "stock":        _num(r.get("STOCK")),
            "doh":          _num(r.get("DOH")),
            "fcst_mes":     fcst_mes,
        })

    # FA A+B MTD: error calculado a nivel SKU (código) y luego ponderado por unidades.
    # Para cada código A/B con forecast > 0: error_sku = |Venta MTD - Forecast mes|, peso = Forecast mes
    # Caso forecast = 0:
    #   - venta = 0  → FA SKU = 100% → no aporta error ni peso (no distorsiona el agregado)
    #   - venta > 0  → FA SKU = 0%   → error_sku = venta, peso = venta (penaliza el agregado)
    # FA = 1 - ( Σ error_sku de A+B ) / ( Σ peso_sku de A+B )
    ab_rows = [r for r in rows if r["abc"] in ("A", "B") and r["fcst_mes"] is not None]
    error_total = 0.0
    peso_total  = 0.0
    for r in ab_rows:
        venta = r["venta_mtd"] or 0
        fcst  = r["fcst_mes"]
        if fcst > 0:
            error_total += abs(venta - fcst)
            peso_total  += fcst
        elif venta > 0:
            error_total += venta
            peso_total  += venta
        # fcst == 0 y venta == 0 → FA 100%, no aporta al agregado
    fa_ab_mtd = round(max(0.0, 1 - error_total / peso_total) * 100, 1) if peso_total else None

    categorias = sorted({r["categoria"] for r in rows if r["categoria"]})
    aromas     = sorted({r["aroma"]     for r in rows if r["aroma"]})
    abcs       = sorted({r["abc"]       for r in rows if r["abc"]})

    _tracking_pt_cache = {
        "rows": rows, "categorias": categorias, "aromas": aromas, "abcs": abcs,
        "fa_ab_mtd": fa_ab_mtd, "fcst_label": fcst_label,
        "last3_labels": last3_labels,
        "file_name": file_name, "file_modified": file_modified,
    }
    return _tracking_pt_cache


@app.route("/api/tracking-pt")
def api_tracking_pt():
    try:
        data = _load_tracking_pt()
        return jsonify(data)
    except Exception as e:
        log.error(f"Error loading Tracking PT: {e}")
        return jsonify({"error": str(e), "rows": [], "categorias": [], "aromas": [], "abcs": []}), 500


@app.route("/api/tracking-pt/refresh", methods=["POST"])
@_login_required
def api_tracking_pt_refresh():
    """Fuerza recarga del Tracking PT desde la carpeta SharePoint (toma el archivo más reciente)."""
    global _tracking_pt_cache
    _tracking_pt_cache = None
    try:
        data = _load_tracking_pt()
        return jsonify({"ok": True, "file_name": data.get("file_name"), "file_modified": data.get("file_modified")})
    except Exception as e:
        log.error(f"Error refrescando Tracking PT: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
