"""
SpotIA — Asistente conversacional de Fill Rate & Supply Chain.
Construye contexto completo desde el DataFrame en memoria y consulta Claude API.
"""
import os
import logging
from datetime import date

import pandas as pd

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────

def _fr(sol, asig):
    return round(float(asig) / float(sol) * 100, 1) if sol > 0 else 0.0

def _str(val):
    s = str(val) if not pd.isna(val) else ""
    return s if s not in ("nan", "None") else ""


# ── Construcción de contexto ──────────────────────────────────────

def build_context(df: pd.DataFrame, cliente_ctx: str = "") -> str:
    """
    Genera un contexto completo y detallado para Claude.
    Si cliente_ctx está definido, el contexto se centra en ese cliente
    pero también incluye benchmarks globales para comparación.
    """
    if df is None or df.empty:
        return "No hay datos cargados actualmente."

    today   = pd.Timestamp(date.today())
    cur_y   = today.year
    cur_m   = today.month
    dfall   = df.copy()
    dfw     = df.dropna(subset=["fecha_despacho"]).copy()

    # Scope de trabajo: si hay cliente seleccionado, todo el detalle es de ese cliente
    if cliente_ctx:
        df_scope  = dfall[dfall["cliente"] == cliente_ctx].copy()
        dfw_scope = dfw[dfw["cliente"] == cliente_ctx].copy()
        scope_label = f"CLIENTE SELECCIONADO: {cliente_ctx}"
    else:
        df_scope  = dfall
        dfw_scope = dfw
        scope_label = "TODOS LOS CLIENTES"

    lines = []
    lines.append(f"=== DATOS SUPPLY CHAIN SPOT ESSENCE — {today.strftime('%d/%m/%Y')} ===")
    lines.append(f"Alcance del análisis: {scope_label}")
    lines.append(f"Total registros en base: {len(dfall):,}")
    lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 1 — KPIs GLOBALES (siempre del scope)
    # ══════════════════════════════════════════════════════════════
    sol  = df_scope["un_solicitadas"].sum()
    asig = df_scope["un_asignadas"].sum()
    bo   = df_scope["bo_un"].sum()
    vt   = df_scope["valor_total"].sum()
    vf   = df_scope["valor_facturado"].sum()
    bv   = df_scope["bo_valorizado"].sum()

    lines.append("--- KPIs GLOBALES (histórico completo) ---")
    lines.append(f"Fill Rate global: {_fr(sol, asig)}%")
    lines.append(f"Unidades solicitadas: {int(sol):,}")
    lines.append(f"Unidades asignadas: {int(asig):,}")
    lines.append(f"Unidades en Back Order: {int(bo):,}")
    lines.append(f"Valor total OCs: ${vt:,.0f}")
    lines.append(f"Valor facturado: ${vf:,.0f}")
    lines.append(f"Back Order valorizado: ${bv:,.0f}")
    lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 2 — MTD (mes en curso)
    # ══════════════════════════════════════════════════════════════
    df_mtd = dfw_scope[
        (dfw_scope["fecha_despacho"].dt.year  == cur_y) &
        (dfw_scope["fecha_despacho"].dt.month == cur_m) &
        (dfw_scope["fecha_despacho"] <= today)
    ]
    lines.append("--- FILL RATE MTD (mes en curso hasta hoy) ---")
    if not df_mtd.empty:
        sol_m = df_mtd["un_solicitadas"].sum()
        lines.append(f"Fill Rate MTD: {_fr(sol_m, df_mtd['un_asignadas'].sum())}%")
        lines.append(f"Valor total MTD: ${df_mtd['valor_total'].sum():,.0f}")
        lines.append(f"Valor facturado MTD: ${df_mtd['valor_facturado'].sum():,.0f}")
        lines.append(f"Back Order MTD: ${df_mtd['bo_valorizado'].sum():,.0f}")
        lines.append(f"OCs distintas MTD: {df_mtd['oc'].nunique()}")
    else:
        lines.append("Sin despachos registrados en el mes actual.")
    lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 3 — FILL RATE MENSUAL (últimos 12 meses)
    # ══════════════════════════════════════════════════════════════
    lines.append("--- FILL RATE MENSUAL HISTÓRICO (últimos 12 meses) ---")
    dfw_scope["_ym"] = dfw_scope["fecha_despacho"].dt.to_period("M")
    mo_grp = dfw_scope.groupby("_ym").agg(
        un_sol  =("un_solicitadas",  "sum"),
        un_asig =("un_asignadas",    "sum"),
        bo_val  =("bo_valorizado",   "sum"),
        val_tot =("valor_total",     "sum"),
        val_fac =("valor_facturado", "sum"),
        n_ocs   =("oc",              "nunique"),
    ).reset_index().sort_values("_ym").tail(12)
    for _, r in mo_grp.iterrows():
        fr_mo = _fr(r["un_sol"], r["un_asig"])
        lines.append(
            f"  {r['_ym']}: FR={fr_mo}% | "
            f"Val.Fac=${r['val_fac']:,.0f} | BO=${r['bo_val']:,.0f} | OCs={int(r['n_ocs'])}"
        )
    lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 4 — FILL RATE SEMANAL (últimas 12 semanas)
    # ══════════════════════════════════════════════════════════════
    lines.append("--- FILL RATE SEMANAL (últimas 12 semanas) ---")
    dfw_scope["_wmon"] = (
        dfw_scope["fecha_despacho"]
        - pd.to_timedelta(dfw_scope["fecha_despacho"].dt.dayofweek, unit="D")
    ).dt.strftime("%Y-%m-%d")
    from datetime import timedelta
    cur_mon = date.today() - timedelta(days=date.today().weekday())
    wkeys = [(cur_mon - timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(12)]
    dfw_w12 = dfw_scope[dfw_scope["_wmon"].isin(wkeys)]
    if not dfw_w12.empty:
        wk_grp = dfw_w12.groupby("_wmon").agg(
            un_sol  =("un_solicitadas",  "sum"),
            un_asig =("un_asignadas",    "sum"),
            bo_val  =("bo_valorizado",   "sum"),
            val_fac =("valor_facturado", "sum"),
        ).reset_index().sort_values("_wmon")
        for _, r in wk_grp.iterrows():
            wmon = date.fromisoformat(r["_wmon"])
            wend = wmon + timedelta(days=6)
            lines.append(
                f"  Sem {wmon.strftime('%d/%m')}–{wend.strftime('%d/%m')}: "
                f"FR={_fr(r['un_sol'], r['un_asig'])}% | "
                f"Val.Fac=${r['val_fac']:,.0f} | BO=${r['bo_val']:,.0f}"
            )
    else:
        lines.append("  Sin datos en las últimas 12 semanas.")
    lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 5 — OCs ACTIVAS/ABIERTAS (estado PENDIENTE) — detalle completo
    # ══════════════════════════════════════════════════════════════
    # En el archivo solo existen dos estados reales:
    #   PENDIENTE = OC activa/abierta (el cliente aún tiene el pedido vigente)
    #   CERRADA   = OC cerrada formalmente por el cliente
    # Dentro de PENDIENTE, si bo_un > 0 hay Back Order en esa línea.

    df_pend = df_scope[df_scope["estado"].str.upper().isin(["PENDIENTE", "BACK ORDER"])].copy()
    n_con_bo = df_pend[df_pend["bo_un"] > 0]["oc"].nunique()
    n_sin_bo = df_pend[df_pend["bo_un"] == 0]["oc"].nunique()

    lines.append("--- OCs ACTIVAS/ABIERTAS (estado PENDIENTE) — DETALLE COMPLETO ---")
    lines.append(f"IMPORTANTE: 'PENDIENTE' = OC activa/abierta (vigente, no cerrada por el cliente).")
    lines.append(f"Total OCs activas (PENDIENTE): {df_pend['oc'].nunique()}")
    lines.append(f"  - Con Back Order (bo_un > 0): {n_con_bo} OCs")
    lines.append(f"  - Sin Back Order (FR=100%):   {n_sin_bo} OCs")
    if "es_vencida" in df_pend.columns:
        n_venc = df_pend[df_pend["es_vencida"] == True]["oc"].nunique()
        if n_venc:
            lines.append(f"  ⚠ OCs con fecha de despacho vencida: {n_venc}")
    lines.append(f"Back Order valorizado total (OCs activas): ${df_pend['bo_valorizado'].sum():,.0f}")
    lines.append("")

    # Detalle por OC — todos los SKUs con sus motivos
    for (oc_id, cli), grp in df_pend.groupby(["oc", "cliente"]):
        fd      = grp["fecha_despacho"].dropna()
        fd_str  = fd.iloc[0].strftime("%d/%m/%Y") if not fd.empty else "S/F"
        sol_oc  = grp["un_solicitadas"].sum()
        asig_oc = grp["un_asignadas"].sum()
        bo_oc   = grp["bo_un"].sum()
        bv_oc   = grp["bo_valorizado"].sum()
        vt_oc   = grp["valor_total"].sum()
        vf_oc   = grp["valor_facturado"].sum()
        fr_oc   = _fr(sol_oc, asig_oc)
        tiene_bo = "CON BACK ORDER" if bo_oc > 0 else "SIN BACK ORDER (completa)"
        venc     = " ⚠FECHA VENCIDA" if ("es_vencida" in grp.columns and grp["es_vencida"].any()) else ""

        lines.append(
            f"OC {oc_id} | Cliente:{cli} | Estado:PENDIENTE (activa) | {tiene_bo}{venc} | "
            f"Despacho:{fd_str} | FR={fr_oc}% | "
            f"UN Sol:{int(sol_oc)} | UN Asig:{int(asig_oc)} | BO:{int(bo_oc)}un | "
            f"BO Val:${bv_oc:,.0f} | Val.Total:${vt_oc:,.0f} | Val.Fac:${vf_oc:,.0f}"
        )

        # Líneas por producto (SKU)
        for _, row in grp.iterrows():
            prod   = _str(row.get("producto",      ""))
            ean    = _str(row.get("ean_spot",       ""))
            cat    = _str(row.get("categoria",      ""))
            us     = int(row.get("un_solicitadas",  0))
            ua     = int(row.get("un_asignadas",    0))
            bo_r   = int(row.get("bo_un",           0))
            fr_r   = _fr(us, ua)
            coment = _str(row.get("comentarios",    ""))
            motivo = _str(row.get("motivo_bo",      ""))
            nota   = coment or motivo

            sku_line = (
                f"    SKU: {prod} | EAN:{ean} | Cat:{cat} | "
                f"Sol:{us} | Asig:{ua} | BO:{bo_r}un | FR:{fr_r}%"
            )
            if nota:
                sku_line += f" | Motivo/Comentario: \"{nota}\""
            lines.append(sku_line)
        lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 6 — TOP PRODUCTOS CON MAYOR BACK ORDER (activas)
    # ══════════════════════════════════════════════════════════════
    lines.append("--- TOP PRODUCTOS CON MAYOR BACK ORDER (OCs activas) ---")
    df_bo_prods = df_pend[df_pend["bo_un"] > 0]
    if not df_bo_prods.empty:
        prod_bo = df_bo_prods.groupby("producto").agg(
            bo_un   =("bo_un",          "sum"),
            bo_val  =("bo_valorizado",  "sum"),
            un_sol  =("un_solicitadas", "sum"),
            un_asig =("un_asignadas",   "sum"),
            n_ocs   =("oc",             "nunique"),
        ).reset_index()
        prod_bo["fr"] = prod_bo.apply(lambda r: _fr(r["un_sol"], r["un_asig"]), axis=1)
        prod_bo = prod_bo.sort_values("bo_val", ascending=False).head(30)
        for _, r in prod_bo.iterrows():
            lines.append(
                f"  {r['producto']}: BO={int(r['bo_un'])}un | "
                f"BO=${r['bo_val']:,.0f} | FR={r['fr']}% | OCs afectadas={int(r['n_ocs'])}"
            )
    else:
        lines.append("  Sin Back Order en OCs activas.")
    lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 7 — FILL RATE POR CLIENTE (solo si scope es global)
    # ══════════════════════════════════════════════════════════════
    if not cliente_ctx:
        lines.append("--- FILL RATE POR CLIENTE (histórico completo) ---")
        cli_grp = dfall.groupby("cliente").agg(
            un_sol  =("un_solicitadas",  "sum"),
            un_asig =("un_asignadas",    "sum"),
            bo_val  =("bo_valorizado",   "sum"),
            val_tot =("valor_total",     "sum"),
            val_fac =("valor_facturado", "sum"),
            n_ocs   =("oc",              "nunique"),
        ).reset_index()
        cli_grp["fr"] = cli_grp.apply(lambda r: _fr(r["un_sol"], r["un_asig"]), axis=1)
        cli_grp = cli_grp.sort_values("fr")
        for _, r in cli_grp.iterrows():
            lines.append(
                f"  {r['cliente']}: FR={r['fr']}% | "
                f"Val.Total=${r['val_tot']:,.0f} | Val.Fac=${r['val_fac']:,.0f} | "
                f"BO=${r['bo_val']:,.0f} | OCs={int(r['n_ocs'])}"
            )
        lines.append("")

    # ══════════════════════════════════════════════════════════════
    # SECCIÓN 8 — HISTÓRICO COMPLETO POR PRODUCTO (scope)
    # ══════════════════════════════════════════════════════════════
    lines.append("--- FILL RATE POR PRODUCTO (histórico, todos los estados) ---")
    prod_hist = df_scope.groupby("producto").agg(
        un_sol  =("un_solicitadas",  "sum"),
        un_asig =("un_asignadas",    "sum"),
        bo_val  =("bo_valorizado",   "sum"),
        val_tot =("valor_total",     "sum"),
        val_fac =("valor_facturado", "sum"),
        n_ocs   =("oc",              "nunique"),
    ).reset_index()
    prod_hist["fr"] = prod_hist.apply(lambda r: _fr(r["un_sol"], r["un_asig"]), axis=1)
    prod_hist = prod_hist.sort_values("fr").head(50)
    for _, r in prod_hist.iterrows():
        lines.append(
            f"  {r['producto']}: FR={r['fr']}% | "
            f"BO=${r['bo_val']:,.0f} | Val.Fac=${r['val_fac']:,.0f} | OCs={int(r['n_ocs'])}"
        )
    lines.append("")

    return "\n".join(lines)


def build_light_context(df: pd.DataFrame, cliente_ctx: str = "") -> str:
    """
    Contexto compacto (~2.000 tokens) para preguntas de modo rápido.
    Omite detalle SKU por OC y limita históricos.
    """
    if df is None or df.empty:
        return "No hay datos cargados actualmente."

    today  = pd.Timestamp(date.today())
    cur_y  = today.year
    cur_m  = today.month
    dfall  = df.copy()
    dfw    = df.dropna(subset=["fecha_despacho"]).copy()

    if cliente_ctx:
        df_scope  = dfall[dfall["cliente"] == cliente_ctx].copy()
        dfw_scope = dfw[dfw["cliente"] == cliente_ctx].copy()
        scope_label = f"CLIENTE: {cliente_ctx}"
    else:
        df_scope  = dfall
        dfw_scope = dfw
        scope_label = "TODOS LOS CLIENTES"

    lines = []
    lines.append(f"=== RESUMEN SUPPLY CHAIN SPOT ESSENCE — {today.strftime('%d/%m/%Y')} ===")
    lines.append(f"Alcance: {scope_label}")
    lines.append("")

    # KPIs globales
    sol  = df_scope["un_solicitadas"].sum()
    asig = df_scope["un_asignadas"].sum()
    bv   = df_scope["bo_valorizado"].sum()
    lines.append(f"FR global: {_fr(sol, asig)}%  |  BO valorizado total: ${bv:,.0f}")

    # MTD
    df_mtd = dfw_scope[
        (dfw_scope["fecha_despacho"].dt.year  == cur_y) &
        (dfw_scope["fecha_despacho"].dt.month == cur_m) &
        (dfw_scope["fecha_despacho"] <= today)
    ]
    if not df_mtd.empty:
        sol_m = df_mtd["un_solicitadas"].sum()
        lines.append(
            f"FR MTD: {_fr(sol_m, df_mtd['un_asignadas'].sum())}%  |  "
            f"Facturado MTD: ${df_mtd['valor_facturado'].sum():,.0f}  |  "
            f"BO MTD: ${df_mtd['bo_valorizado'].sum():,.0f}"
        )
    lines.append("")

    # Últimos 6 meses (sin detalle SKU)
    lines.append("--- FR MENSUAL (últimos 6 meses) ---")
    dfw_scope["_ym"] = dfw_scope["fecha_despacho"].dt.to_period("M")
    mo_grp = dfw_scope.groupby("_ym").agg(
        un_sol  =("un_solicitadas", "sum"),
        un_asig =("un_asignadas",   "sum"),
        bo_val  =("bo_valorizado",  "sum"),
    ).reset_index().sort_values("_ym").tail(6)
    for _, r in mo_grp.iterrows():
        lines.append(f"  {r['_ym']}: FR={_fr(r['un_sol'],r['un_asig'])}% | BO=${r['bo_val']:,.0f}")
    lines.append("")

    # OCs activas — resumen sin detalle SKU
    df_pend = df_scope[df_scope["estado"].str.upper().isin(["PENDIENTE", "BACK ORDER"])].copy()
    lines.append(f"--- OCs ACTIVAS: {df_pend['oc'].nunique()} OCs ---")
    n_bo   = df_pend[df_pend["bo_un"] > 0]["oc"].nunique()
    n_venc = 0
    if "es_vencida" in df_pend.columns:
        n_venc = df_pend[df_pend["es_vencida"] == True]["oc"].nunique()
    lines.append(f"  Con BO: {n_bo}  |  Vencidas: {n_venc}  |  BO total: ${df_pend['bo_valorizado'].sum():,.0f}")

    # Top 10 OCs con mayor BO (sin SKU)
    oc_bo = df_pend[df_pend["bo_un"] > 0].groupby(["oc","cliente"]).agg(
        bo_val=("bo_valorizado","sum"), bo_un=("bo_un","sum"),
        fd=("fecha_despacho","first"), fr_sol=("un_solicitadas","sum"), fr_asig=("un_asignadas","sum"),
    ).reset_index().sort_values("bo_val", ascending=False).head(10)
    for _, r in oc_bo.iterrows():
        fd_str = r["fd"].strftime("%d/%m/%Y") if pd.notna(r["fd"]) else "S/F"
        venc_tag = " ⚠VENCIDA" if ("es_vencida" in df_pend.columns and
            df_pend[(df_pend["oc"]==r["oc"]) & (df_pend["es_vencida"]==True)].any().any()) else ""
        lines.append(
            f"  OC {r['oc']} | {r['cliente']} | Desp:{fd_str}{venc_tag} | "
            f"FR={_fr(r['fr_sol'],r['fr_asig'])}% | BO: {int(r['bo_un'])}un / ${r['bo_val']:,.0f}"
        )
    lines.append("")

    # Top 10 productos con BO
    lines.append("--- TOP 10 PRODUCTOS CON MAYOR BO ---")
    df_bo_p = df_pend[df_pend["bo_un"] > 0].groupby("producto").agg(
        bo_un=("bo_un","sum"), bo_val=("bo_valorizado","sum"),
        un_sol=("un_solicitadas","sum"), un_asig=("un_asignadas","sum"),
    ).reset_index().sort_values("bo_val", ascending=False).head(10)
    for _, r in df_bo_p.iterrows():
        lines.append(f"  {r['producto']}: FR={_fr(r['un_sol'],r['un_asig'])}% | BO {int(r['bo_un'])}un / ${r['bo_val']:,.0f}")
    lines.append("")

    # FR por cliente (global, siempre pequeño)
    if not cliente_ctx:
        lines.append("--- FR POR CLIENTE ---")
        cli_g = dfall.groupby("cliente").agg(
            un_sol=("un_solicitadas","sum"), un_asig=("un_asignadas","sum"),
            bo_val=("bo_valorizado","sum"),
        ).reset_index()
        cli_g["fr"] = cli_g.apply(lambda r: _fr(r["un_sol"], r["un_asig"]), axis=1)
        for _, r in cli_g.sort_values("fr").iterrows():
            lines.append(f"  {r['cliente']}: FR={r['fr']}% | BO=${r['bo_val']:,.0f}")

    return "\n".join(lines)


# ── Llamada a Claude API ──────────────────────────────────────────

def ask_spotia(question: str, context: str, mode: str = "chat", cliente_ctx: str = "") -> str:
    """Envía la pregunta + contexto a Claude y retorna respuesta HTML."""
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return (
            "<div class='spotia-error'>"
            "⚠️ Se requiere una clave API de Anthropic. "
            "Agrega <code>ANTHROPIC_API_KEY=tu_clave</code> en el archivo <code>.env</code> y reinicia el servidor."
            "</div>"
        )

    client = anthropic.Anthropic(api_key=api_key)

    # Instrucción de foco en cliente si aplica
    cliente_instruction = ""
    if cliente_ctx:
        cliente_instruction = f"""
CLIENTE ACTIVO EN EL VISOR: {cliente_ctx}
IMPORTANTE: El usuario tiene seleccionado el cliente "{cliente_ctx}".
Todas tus respuestas deben referirse EXCLUSIVAMENTE a este cliente, a menos que el usuario
explícitamente pida información de otro cliente o de todos los clientes.
No menciones datos de otros clientes salvo que sea necesario para una comparación solicitada."""

    system_prompt = f"""Eres SpotIA, el asistente inteligente de Supply Chain de SPOT ESSENCE.

Tu función es responder preguntas sobre Fill Rate, Back Orders, Órdenes de Compra, clientes y productos
utilizando EXCLUSIVAMENTE los datos que se te proporcionan en el contexto.
{cliente_instruction}

GLOSARIO DE NEGOCIO — entiende estos términos exactamente así:
- OC PENDIENTE / OC ACTIVA / OC ABIERTA: son sinónimos. El estado "PENDIENTE" en el archivo significa que la Orden de Compra sigue vigente, el cliente aún la tiene abierta. Puede estar totalmente asignada (FR=100%) o con unidades sin despachar (Back Order).
- OC CERRADA: el cliente ya cerró formalmente el pedido. Puede haber cerrado con o sin Back Order. Ya no se puede modificar.
- BACK ORDER (BO): dentro de una OC PENDIENTE, son las unidades solicitadas que NO se han podido asignar/despachar. Si BO UN > 0 en una OC pendiente, esa OC tiene Back Order.
- FILL RATE (FR): porcentaje de unidades asignadas / unidades solicitadas × 100. Un FR 100% = todo despachado. FR < 100% = hay unidades pendientes.
- MTD (Month to Date): acumulado del mes en curso hasta hoy.
- El campo COMENTARIOS del archivo explica el motivo por el que no se pudo despachar cuando hay Back Order.

REGLAS ESTRICTAS:
- Responde SOLO con la información del contexto proporcionado.
- Si no hay datos suficientes, dilo claramente.
- NO uses conocimiento general ni inventes cifras.
- Sé preciso con números, porcentajes y nombres de productos/clientes/OCs.
- Responde siempre en español.
- Cuando el usuario diga "OC activa", "OC abierta" o "OC vigente", entiende que se refiere a OCs con estado PENDIENTE.

FORMATO DE RESPUESTA (usa HTML, NO markdown):
- Datos clave: <strong>texto</strong>, <span class="spotia-kpi">XX%</span>
- Alertas: <span class="spotia-alert">texto</span>
- Positivo: <span class="spotia-ok">texto</span>
- Tablas: <table class="spotia-table"><thead><tr><th>Col</th></tr></thead><tbody><tr><td>dato</td></tr></tbody></table>
- Avisos: <div class="spotia-warning">⚠️ mensaje</div>
- Éxito: <div class="spotia-success">✓ mensaje</div>
- Insights: <div class="spotia-insight">💡 mensaje</div>
- Separadores: <hr class="spotia-hr">
- NO incluyas etiquetas html, body, head.

COMPORTAMIENTO:
- Siempre incluye contexto adicional: tendencias, riesgos, comparaciones relevantes.
- Destaca alertas: FR < 80%, OCs vencidas, BO elevado.
- Al hablar de productos con BO, incluye siempre el comentario/motivo de por qué no se despachó cuando esté disponible en los datos.
- Sé conciso pero completo."""

    mode_prompts = {
        "executive": (
            f"Genera un RESUMEN EJECUTIVO completo para reunión de gerencia.\n"
            f"{'Enfocado en el cliente: ' + cliente_ctx if cliente_ctx else 'De todo el portafolio.'}\n"
            "Incluye: Fill Rate MTD vs mes anterior, clientes/productos con riesgo, Back Order total y valorizado, "
            "principales causas de incumplimiento por producto con sus motivos, y recomendaciones concretas priorizadas."
        ),
        "comercial": (
            f"Prepara un INFORME COMPLETO para reunión comercial con: {cliente_ctx or 'el cliente seleccionado'}.\n"
            "Incluye: Fill Rate MTD, histórico mensual y semanal, todas las OCs pendientes con sus SKUs y motivos de BO, "
            "valor pendiente total, evolución del FR, riesgos actuales, y un mensaje ejecutivo profesional listo para presentar."
        ),
        "riesgos": (
            f"Realiza un ANÁLISIS DE RIESGOS completo {'para ' + cliente_ctx if cliente_ctx else 'del portafolio'}.\n"
            "Identifica: OCs vencidas o próximas a vencer, FR < 85%, productos con BO crítico y sus motivos, "
            "tendencias negativas en FR semanal/mensual. Genera recomendaciones concretas y priorizadas por urgencia e impacto."
        ),
        "chat": question,
    }

    user_message = mode_prompts.get(mode, question)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"CONTEXTO DE DATOS:\n{context}\n\n---\nSOLICITUD: {user_message}"
            }]
        )
        return message.content[0].text

    except anthropic.AuthenticationError:
        return "<div class='spotia-error'>⚠️ Clave API inválida. Verifica <code>ANTHROPIC_API_KEY</code> en el archivo <code>.env</code>.</div>"
    except Exception as e:
        log.error(f"SpotIA error: {e}")
        return f"<div class='spotia-error'>⚠️ Error al consultar el asistente: {str(e)}</div>"
