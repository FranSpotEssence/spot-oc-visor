/* ================================================================
   SPOT ESSENCE — Dashboard JS
   Gestión de KPIs, tabla OC, ranking, drill-down y gráficos
================================================================ */

"use strict";

// ── Estado global ─────────────────────────────────────────────
const STATE = {
  orders:        [],
  kpis:          {},
  refreshMinutes: 60,
  countdown:      60 * 60,
  countdownTimer: null,
  refreshTimer:   null,
  frChart:        null,
  boChart:        null,
};

// ── Utilidades semana ─────────────────────────────────────────
const _MES_EN = { jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11 };

function currentWeekBounds() {
  const hoy  = new Date();
  const dow  = hoy.getDay();
  const lunes = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - (dow === 0 ? 6 : dow - 1));
  const domingo = new Date(lunes.getFullYear(), lunes.getMonth(), lunes.getDate() + 6);
  return { lunes, domingo };
}

function parseDispatchDate(str) {
  if (!str) return null;
  const p = str.split("-");
  if (p.length !== 3) return null;
  const d = parseInt(p[0], 10);
  const m = _MES_EN[p[1].toLowerCase().slice(0, 3)];
  const y = parseInt(p[2], 10);
  if (isNaN(d) || m === undefined || isNaN(y)) return null;
  return new Date(y, m, d);
}

function sortWeekOrders(orders) {
  return [...orders].sort((a, b) => {
    const da = parseDispatchDate(a.fecha_despacho);
    const db = parseDispatchDate(b.fecha_despacho);
    if (!da && !db) return 0;
    if (!da) return 1;
    if (!db) return -1;
    return da - db;
  });
}

// ── Título semana en curso ────────────────────────────────────
function setWeekRangeTitle() {
  const el = document.getElementById("weekRangeTitle");
  if (!el) return;
  const MESES = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"];
  const hoy   = new Date();
  const dow   = hoy.getDay(); // 0=dom, 1=lun … 6=sab
  const lunes = new Date(hoy);
  lunes.setDate(hoy.getDate() - (dow === 0 ? 6 : dow - 1));
  const domingo = new Date(lunes);
  domingo.setDate(lunes.getDate() + 6);
  const dL = lunes.getDate(),   mL = MESES[lunes.getMonth()];
  const dD = domingo.getDate(), mD = MESES[domingo.getMonth()];
  const rango = mL === mD
    ? `${dL}–${dD} ${mL}`
    : `${dL} ${mL} – ${dD} ${mD}`;
  el.textContent = `semana ${rango}`;
}

// ── Init ──────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  setWeekRangeTitle();
  loadAll();
  startCountdown();

  // Filtros tabla OCs
  document.getElementById("searchInput")?.addEventListener("input", filterTable);
  document.getElementById("filtroEstado")?.addEventListener("change", filterTable);

  // Filtros BO detalle
  ["boSearch","boFilterOc","boFilterProducto"].forEach(id => {
    document.getElementById(id)?.addEventListener("input", filterBoDetail);
  });
  document.getElementById("boFilterCliente")?.addEventListener("change", filterBoDetail);
});

// ── Carga principal ───────────────────────────────────────────
async function loadAll() {
  await Promise.all([loadKPIs(), loadOrders()]);
}

// ── KPIs ──────────────────────────────────────────────────────
async function loadKPIs() {
  try {
    const res  = await fetch("/api/kpis");
    const data = await res.json();
    STATE.kpis = data;
    renderKPIs(data);
    updateNavbar(data);
    renderRanking(data.bo_por_producto || []);

    if (data.error) showError(data.error);
    else            hideError();

    if (STATE.frChart)  renderFrChart(data.fr_por_cliente || []);
  } catch (e) {
    showError("No se pudo conectar con el servidor.");
    console.error(e);
  }
}

function renderKPIs(d) {
  const grid = document.getElementById("kpiGrid");
  if (!grid) return;

  const frColor = colorClass(d.fr_pend_mes_color);

  grid.innerHTML = `
    <!-- BIG: Fill Rate OCs Pendientes del Mes -->
    <div class="kpi-fr ${frColor}">
      <div>
        <div class="fr-main-label">Fill Rate — OCs Pendientes del Mes</div>
        <div class="fr-main-value">${fmtPct(d.fr_pend_mes)}</div>
        <div class="fr-main-sub">
          ${fmtNum(d.asig_pend_mes)} / ${fmtNum(d.sol_pend_mes)} UN · ${fmtNum(d.oc_pend_mes)} OCs · ${d.mes_label || ""}
        </div>
      </div>
      <span class="fr-main-badge">${d.fr_pend_mes_label || ""}</span>
    </div>

    <!-- OC en Curso -->
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">OC en Curso</div>
        <div class="kpi-s-val">${d.oc_en_curso ?? "—"}</div>
        <div class="kpi-s-sub">pendientes de despacho</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>

    <!-- Valorizado OC en Curso -->
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Valorizado OC en Curso</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(d.val_en_curso)}</div>
        <div class="kpi-s-sub">valor total OCs pendientes</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>

    <!-- Pendiente de Facturar clientes clave -->
    <div class="kpi-s s-${d.pend_facturar > 0 ? 'yellow' : 'neu'}">
      <div>
        <div class="kpi-s-lbl">Pendiente de Facturar</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(d.pend_facturar)}</div>
        <div class="kpi-s-sub">OCs abiertas · clientes Retail</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>

    <!-- BO Valorizado en Curso -->
    <div class="kpi-s s-${d.bo_val_en_curso > 0 ? 'red' : 'green'}">
      <div>
        <div class="kpi-s-lbl">Back Order Valorizado</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(d.bo_val_en_curso)}</div>
        <div class="kpi-s-sub">BO en OCs en curso</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
  `;

  // Actualizar badges sidebar
  setEl("badgeOcs",  d.oc_en_curso);
  setEl("mesLabel",  d.mes_label);
}

// ── TABLA OCs ─────────────────────────────────────────────────
async function loadOrders() {
  try {
    const res  = await fetch("/api/orders");
    const data = await res.json();
    const all  = data.orders || [];

    // OCs pendientes (cualquier fecha futura) + OCs cerradas solo de la semana actual
    const { lunes, domingo } = currentWeekBounds();
    const visible = all.filter(r => {
      const cerrada = (r.estado || "").toUpperCase() === "CERRADA";
      if (!cerrada) return true; // todas las pendientes
      const d = parseDispatchDate(r.fecha_despacho);
      return d && d >= lunes && d <= domingo; // cerradas solo si son de esta semana
    });

    STATE.orders = sortWeekOrders(visible);
    renderTable(STATE.orders);
  } catch (e) {
    console.error("Error cargando órdenes:", e);
    const tbody = document.getElementById("ocTableBody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="text-center py-4 text-muted">Error al cargar órdenes: ${e.message}</td></tr>`;
    const tbody2 = document.getElementById("ocTableBody2");
    if (tbody2) tbody2.innerHTML = tbody ? tbody.innerHTML : "";
  }
}

function renderTable(orders) {
  const tbody = document.getElementById("ocTableBody");
  const count = document.getElementById("tableCount");
  if (!tbody) return;

  const pendientes = orders.filter(r => (r.estado || "").toUpperCase() !== "CERRADA");
  if (count) count.textContent = `${orders.length} en semana`;
  const pendCount = document.getElementById("tablePendCount");
  if (pendCount) {
    pendCount.textContent  = `${pendientes.length} pendientes`;
    pendCount.style.display = pendientes.length > 0 ? "" : "none";
  }

  if (!orders.length) {
    tbody.innerHTML = `<tr><td colspan="8">
      <div style="text-align:center;padding:40px 0;color:#ccc">
        <div style="font-size:13px;font-weight:600;letter-spacing:1px;text-transform:uppercase">Sin órdenes pendientes</div>
      </div>
    </td></tr>`;
    return;
  }

  tbody.innerHTML = orders.map(r => {
    const cerrada = (r.estado || "").toUpperCase() === "CERRADA";
    const clienteCls = cerrada ? "c-green" : "c-yellow";
    return `
    <tr onclick="openDetail('${esc(r.oc)}','${esc(r.cliente)}')">
      <td><span class="cliente-chip ${clienteCls}">${esc(r.cliente)}</span></td>
      <td class="font-mono">${esc(r.oc)}</td>
      <td class="${r.fecha_clase}">${esc(r.fecha_despacho)}</td>
      <td><span class="fr-chip ${r.fr_chip}">${fmtPct(r.fill_rate)}</span></td>
      <td class="col-money">${fmtMoney(r.valor_total)}</td>
      <td class="col-money">${fmtMoney(r.valor_facturado)}</td>
      <td class="col-money ${r.bo_valorizado > 0 ? 'bo-val-warn' : ''}">${fmtMoney(r.bo_valorizado)}</td>
      <td><button class="detail-btn" onclick="event.stopPropagation();openDetail('${esc(r.oc)}','${esc(r.cliente)}')">Ver →</button></td>
    </tr>
  `;
  }).join("");

  // Renderizar copia en sección OCs si existe
  const tbody2 = document.getElementById("ocTableBody2");
  if (tbody2) {
    tbody2.innerHTML = tbody.innerHTML;
    setEl("tableCount2", `${orders.length} órdenes`);
  }

  _renderDashLossTree(orders);
}

function populateEstadoFilter(orders) {
  const sel = document.getElementById("filtroEstado");
  if (!sel) return;
  const current = sel.value;

  // Orden lógico preferido; estados no listados van al final alfabético
  const ORDER = ["VENCIDA","PRÓX. VENCER","BACK ORDER","PENDIENTE","CERRADA"];
  const found  = [...new Set(orders.map(r => r.estado).filter(Boolean))];
  found.sort((a, b) => {
    const ia = ORDER.indexOf(a);
    const ib = ORDER.indexOf(b);
    if (ia === -1 && ib === -1) return a.localeCompare(b);
    if (ia === -1) return 1;
    if (ib === -1) return -1;
    return ia - ib;
  });

  sel.innerHTML = `<option value="">Todos los estados</option>` +
    found.map(e => `<option value="${esc(e)}">${esc(e)}</option>`).join("");

  // Restaurar selección previa si sigue siendo válida
  if (current && found.includes(current)) sel.value = current;
}

function filterTable() {
  const q      = (document.getElementById("searchInput")?.value || "").toLowerCase().trim();
  const estado = (document.getElementById("filtroEstado")?.value || "").toUpperCase();

  let filtered = STATE.orders;
  const hasFilter = q || estado;

  // Mostrar/ocultar botón limpiar
  const btnClear = document.getElementById("btnClearFilters");
  if (btnClear) btnClear.style.display = hasFilter ? "" : "none";

  if (q) {
    filtered = filtered.filter(r =>
      r.cliente.toLowerCase().includes(q) ||
      r.oc.toLowerCase().includes(q) ||
      (r.comentarios || "").toLowerCase().includes(q)
    );
  }
  if (estado === "CERRADA") {
    filtered = filtered.filter(r => r.estado.toUpperCase() === "CERRADA");
  } else if (estado === "PENDIENTE") {
    filtered = filtered.filter(r => r.estado.toUpperCase() !== "CERRADA");
  }

  renderTable(filtered);
  _renderDashLossTree(filtered);
}

function clearFilters() {
  const search = document.getElementById("searchInput");
  const estado = document.getElementById("filtroEstado");
  if (search) search.value = "";
  if (estado) estado.value = "";
  document.getElementById("btnClearFilters").style.display = "none";
  const orders = sortWeekOrders(STATE.orders);
  renderTable(orders);
  _renderDashLossTree(orders);
}

// ── ÁRBOL DE PÉRDIDA DASHBOARD (OCs Cerradas MTD) ────────────
const _DASH_LOSS = { chart: null };

function _renderDashLossTree(visibleOrders) {
  const ctx = document.getElementById("dashLossTreeChart")?.getContext("2d");
  const tbl = document.getElementById("dashLossTreeTable");
  if (!ctx) return;

  // Filtrar OCs abiertas/pendientes (no cerradas) visibles en la tabla
  const abiertas = visibleOrders.filter(r => (r.estado || "").toUpperCase() !== "CERRADA");

  // Actualizar subtítulo
  const sub = document.getElementById("dashLossTreeSub");
  if (sub) {
    sub.textContent = abiertas.length
      ? `${abiertas.length} OC${abiertas.length !== 1 ? "s" : ""} abierta${abiertas.length !== 1 ? "s" : ""}/pendiente${abiertas.length !== 1 ? "s" : ""}`
      : `sin OCs abiertas`;
  }

  // Cruzar con BO detail para obtener SKUs con categoria_arbol
  const ocIds = new Set(abiertas.map(r => String(r.oc)));
  const boRows = (BO.rows || []).filter(r => ocIds.has(String(r.oc)));

  // Si BO.rows aún no cargó, cargarlo en background y reintentar
  if (!BO.rows.length && ocIds.size > 0) {
    fetch("/api/backorder-detail")
      .then(r => r.json())
      .then(d => { BO.rows = d.rows || []; _renderDashLossTree(visibleOrders); })
      .catch(() => {});
    return;
  }

  // Agrupar por categoría árbol de pérdida
  const COLORS = ["#dc2626","#2563eb","#16a34a","#7c3aed","#ea580c","#0891b2","#db2777","#ca8a04","#65a30d","#b45309"];
  const groups = {};
  boRows.forEach(r => {
    const k = (r.categoria_arbol && r.categoria_arbol.trim()) ? r.categoria_arbol.trim() : "Sin clasificar";
    if (!groups[k]) groups[k] = { bo_un: 0, bo_val: 0, items: [] };
    groups[k].bo_un  += (r.bo_un        || 0);
    groups[k].bo_val += (r.bo_valorizado || 0);
    groups[k].items.push(r);
  });

  const entries  = Object.entries(groups).sort((a, b) => b[1].bo_val - a[1].bo_val);
  const totalVal = entries.reduce((s, [, v]) => s + v.bo_val, 0);

  if (!entries.length) {
    if (_DASH_LOSS.chart) { _DASH_LOSS.chart.destroy(); _DASH_LOSS.chart = null; }
    if (tbl) tbl.innerHTML = `<div style="padding:24px;color:#aaa;font-size:12px;text-align:center">Sin back order en OCs abiertas</div>`;
    return;
  }

  const labels   = entries.map(([k]) => k);
  const values   = entries.map(([, v]) => v.bo_val);
  const units    = entries.map(([, v]) => v.bo_un);
  const skuCnt   = entries.map(([, v]) => v.items.length);
  const bgColors = entries.map((_, i) => COLORS[i % COLORS.length]);

  if (_DASH_LOSS.chart) _DASH_LOSS.chart.destroy();
  _DASH_LOSS.chart = new Chart(ctx, {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: bgColors.map(c => c + "dd"), borderColor: bgColors, borderWidth: 2, hoverOffset: 8 }] },
    options: {
      responsive: true, cutout: "52%",
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: c => { const pct = totalVal > 0 ? ((c.raw/totalVal)*100).toFixed(1) : 0; return ` ${fmtMoney(c.raw)}  (${pct}%)`; },
          afterLabel: c => ` ${fmtNum(units[c.dataIndex])} UN · ${skuCnt[c.dataIndex]} SKU`,
        }}
      }
    }
  });

  if (!tbl) return;
  const rowsHtml = entries.map(([k, v], i) => {
    const pct = totalVal > 0 ? ((v.bo_val / totalVal) * 100).toFixed(1) : "0.0";
    const uid = `dlt-skus-${i}`;
    const skuRows = v.items.map(r => `
      <tr style="background:#fafafa">
        <td colspan="2" style="padding:5px 12px 5px 36px;font-size:10px;color:#444">${esc(r.producto)}</td>
        <td style="padding:5px 10px;text-align:right;font-size:10px;color:#666">${fmtPct(r.fill_rate)}</td>
        <td style="padding:5px 10px;text-align:right;font-size:10px;font-weight:600;font-variant-numeric:tabular-nums">${fmtMoney(r.bo_valorizado)}</td>
        <td style="padding:5px 10px;text-align:right;font-size:10px;color:#666">${fmtNum(r.bo_un)}</td>
        <td></td>
      </tr>`).join("");
    return `
      <tr style="border-bottom:1px solid #f0f0f0">
        <td style="padding:8px 10px"><div style="width:12px;height:12px;border-radius:3px;background:${bgColors[i]}"></div></td>
        <td style="padding:8px 10px;font-weight:600;color:#1a1a1a">${esc(k)}</td>
        <td style="padding:8px 10px;text-align:right">
          <div style="display:flex;align-items:center;justify-content:flex-end;gap:6px">
            <div style="width:60px;height:6px;background:#f0f0f0;border-radius:3px;overflow:hidden">
              <div style="width:${pct}%;height:100%;background:${bgColors[i]};border-radius:3px"></div>
            </div>
            <span style="font-weight:700;color:#333;min-width:36px;text-align:right">${pct}%</span>
          </div>
        </td>
        <td style="padding:8px 10px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums">${fmtMoney(v.bo_val)}</td>
        <td style="padding:8px 10px;text-align:right;color:#555">${fmtNum(v.bo_un)}</td>
        <td style="padding:8px 10px;text-align:right">
          <button onclick="toggleLtSkus('${uid}',this)"
            style="background:none;border:1px solid #e4e4e4;border-radius:4px;padding:3px 8px;font-size:9px;font-family:inherit;font-weight:700;color:#555;cursor:pointer;letter-spacing:.3px;white-space:nowrap">
            ${v.items.length} SKU ▼
          </button>
        </td>
      </tr>
      <tr id="${uid}" style="display:none;border-bottom:1px solid #e8e8e8">
        <td colspan="6" style="padding:0">
          <table style="width:100%;border-collapse:collapse">
            <thead><tr style="background:#f5f5f5">
              <th colspan="2" style="padding:5px 12px 5px 36px;text-align:left;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">Producto</th>
              <th style="padding:5px 10px;text-align:right;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">FR</th>
              <th style="padding:5px 10px;text-align:right;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">BO Val.</th>
              <th style="padding:5px 10px;text-align:right;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">UN</th>
              <th></th>
            </tr></thead>
            <tbody>${skuRows}</tbody>
          </table>
        </td>
      </tr>`;
  }).join("");

  tbl.innerHTML = `
    <table style="width:100%;border-collapse:collapse;font-size:11px">
      <thead><tr style="border-bottom:2px solid #e8e8e8">
        <th style="padding:6px 10px;width:24px"></th>
        <th style="text-align:left;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">Motivo</th>
        <th style="text-align:right;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">% del BO</th>
        <th style="text-align:right;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">Valorizado</th>
        <th style="text-align:right;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">UN</th>
        <th></th>
      </tr></thead>
      <tbody>${rowsHtml}</tbody>
    </table>`;
}

// ── PANEL BO POR PRODUCTO ─────────────────────────────────────
function renderRanking(productos) {
  const body = document.getElementById("rankingBody");
  if (!body) return;

  if (!productos.length) {
    body.innerHTML = `<div class="rank-empty">Sin back order en OCs en curso</div>`;
    return;
  }

  const maxBo = productos[0]?.bo_un || 1;

  body.innerHTML = productos.map((p, i) => {
    const barColor = semColorHex(p.semaforo);
    const barW     = Math.round((p.bo_un / maxBo) * 100);
    return `
      <div class="rank-item">
        <div class="ri-top">
          <div class="ri-num">${i + 1}</div>
          <div class="ri-name" style="font-size:10px">${esc(p.producto)}</div>
          <div class="ri-fr" style="color:${barColor}">${fmtPct(p.fr)}</div>
        </div>
        <div class="ri-bar-wrap">
          <div class="ri-bar" style="width:${barW}%;background:${barColor}"></div>
        </div>
        <div class="ri-bottom">
          <span><strong>${fmtNum(p.bo_un)}</strong> UN pend.</span>
          <span><strong>${p.n_ocs}</strong> OC${p.n_ocs !== 1 ? 's' : ''}</span>
        </div>
      </div>
    `;
  }).join("");
}

function filterByCliente(nombre) {
  const input = document.getElementById("searchInput");
  if (input) {
    input.value = nombre;
    filterTable();
    // Scroll a la tabla
    document.querySelector(".panel")?.scrollIntoView({ behavior: "smooth" });
  }
}

// ── DRILL-DOWN MODAL ──────────────────────────────────────────
async function openDetail(ocId, cliente) {
  const modal = new bootstrap.Modal(document.getElementById("ocModal"));
  const body  = document.getElementById("modalBody");

  setEl("modalClient", "Cargando...");
  setEl("modalOcInfo",  "");
  setEl("modalFr",      "—");
  if (body) body.innerHTML = `<div class="text-center py-5 text-muted">Cargando detalle SKU...</div>`;
  modal.show();

  try {
    const clienteParam = cliente ? `?cliente=${encodeURIComponent(cliente)}` : "";
    const res  = await fetch(`/api/orders/${encodeURIComponent(ocId)}${clienteParam}`);
    const d    = await res.json();

    if (d.error) {
      if (body) body.innerHTML = `<div class="text-center py-4 text-danger">${esc(d.error)}</div>`;
      return;
    }

    // Header del modal
    setEl("modalClient",  d.cliente);
    setEl("modalOcInfo",  `OC ${d.oc} · F. Despacho: ${d.fecha_despacho}${d.es_vencida ? ' · <span style="color:#f87171;font-weight:700">VENCIDA</span>' : ''}`);
    const frEl = document.getElementById("modalFr");
    if (frEl) {
      frEl.textContent  = fmtPct(d.fr);
      frEl.className    = `modal-fr-value ${d.fr_color}`;
    }

    // Body
    const boValFmt = d.bo_valorizado ? `$${fmtNum(Math.round(d.bo_valorizado))}` : "$0";

    const skuRows = (d.skus || []).map(s => {
      const motivoHtml = s.fr >= 100
        ? `<span class="motivo-ok">Completado</span>`
        : s.motivo ? `<span style="font-size:10px;color:#555">${esc(s.motivo)}</span>` : ``;

      const fillColor = s.fr >= 95 ? "#16a34a" : s.fr >= 90 ? "#ca8a04" : s.fr >= 80 ? "#ea580c" : "#dc2626";

      return `
        <tr>
          <td>
            <div style="font-size:10px;font-weight:600;color:#000">${esc(s.producto)}</div>
            <div style="font-size:9px;color:#aaa">${esc(s.marca)} · ${esc(s.categoria)}</div>
          </td>
          <td style="font-family:monospace;font-size:9px;color:#aaa">${esc(s.ean_spot)}</td>
          <td>${fmtNum(s.sol)}</td>
          <td>${fmtNum(s.asig)}</td>
          <td class="${s.bo > 0 ? 'fw-800' : ''}" style="${s.bo > 0 ? 'color:#dc2626' : 'color:#ccc'}">${fmtNum(s.bo)}</td>
          <td>
            <span class="fr-chip ${s.fr_color}" style="font-size:10px;padding:3px 8px">${fmtPct(s.fr)}</span>
            <div class="pct-bar" style="margin-top:5px">
              <div class="pct-fill" style="width:${s.fr}%;background:${fillColor}"></div>
            </div>
          </td>
          <td>
            <span style="font-size:10px;${s.stock === 0 ? 'color:#dc2626;font-weight:700' : 'color:#555'}">${fmtNum(s.stock)}</span>
          </td>
          <td>${motivoHtml}</td>
        </tr>
      `;
    }).join("");

    const comentarios = (d.skus || [])
      .filter(s => s.comentario)
      .map(s => `<strong>${esc(s.producto)}:</strong> ${esc(s.comentario)}`)
      .join("<br>");

    // Guardar datos en el modal para exportación
    document.getElementById("ocModal").dataset.exportData = JSON.stringify(d);

    if (body) body.innerHTML = `
      <div class="modal-sec-label">Resumen de la OC</div>
      <div class="modal-kpis">
        <div class="mk"><div class="mk-lbl">UN Solicitadas</div><div class="mk-val">${fmtNum(d.un_sol)}</div></div>
        <div class="mk"><div class="mk-lbl">UN Asignadas</div><div class="mk-val ok">${fmtNum(d.un_asig)}</div></div>
        <div class="mk"><div class="mk-lbl">UN Pendientes</div><div class="mk-val ${d.bo_un > 0 ? 'crit' : 'ok'}">${fmtNum(d.bo_un)}</div></div>
        <div class="mk"><div class="mk-lbl">BO Valorizado</div><div class="mk-val ${d.bo_valorizado > 0 ? 'warn' : 'ok'}">${boValFmt}</div></div>
      </div>

      <div class="modal-sec-label">Productos Afectados</div>
      <div class="table-responsive">
        <table class="modal-table">
          <thead>
            <tr>
              <th>Producto</th>
              <th>EAN SPOT</th>
              <th>Solic.</th>
              <th>Asign.</th>
              <th>Pendiente</th>
              <th>FR SKU</th>
              <th>Stock</th>
              <th>Comentario</th>
            </tr>
          </thead>
          <tbody>${skuRows}</tbody>
        </table>
      </div>

    `;

  } catch (e) {
    if (body) body.innerHTML = `<div class="text-center py-4 text-danger">Error cargando detalle: ${e.message}</div>`;
    console.error(e);
  }
}

// ══ FILL RATE HISTÓRICO ══════════════════════════════════════════

// selMonths: "YYYY-M" strings; selWeeks: "YYYY-MM-DD" Monday strings
const FRH = { data: null, monthChart: null, weekChart: null, activeTab: "consulta", selMonths: new Set(), selWeeks: new Set(), consultaLoaded: false, consultaDebounce: null };

function _curWeekMonday() {
  const n = new Date();
  const day = n.getDay(); // 0=Sun,1=Mon,...,6=Sat
  const diff = day === 0 ? -6 : 1 - day; // shift to Monday
  const d = new Date(n.getFullYear(), n.getMonth(), n.getDate() + diff);
  const yr = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const dy = String(d.getDate()).padStart(2, "0");
  return `${yr}-${mo}-${dy}`;
}

async function loadFrHistorico() {
  if (FRH.selMonths.size === 0) {
    const n = new Date();
    FRH.selMonths.add(`${n.getFullYear()}-${n.getMonth() + 1}`);
  }
  if (FRH.selWeeks.size === 0) {
    FRH.selWeeks.add(_curWeekMonday());
  }
  // Populate client dropdown in Consulta tab from first API call
  try {
    const res  = await fetch("/api/fr-historico/consulta");
    const data = await res.json();
    _frhConsultaPopulateClientes(data.clientes || []);
    FRH.consultaLoaded = true;
    renderFrhConsultaTable([], false);
  } catch(e) { console.error("Error FRH Consulta:", e); }

  // Pre-cargar datos de pestañas Semanal y Mensual
  await filterFrh();
}

async function filterFrh() {
  const params = _frhParams();
  try {
    const res = await fetch("/api/fr-historico?" + params);
    FRH.data  = await res.json();
    renderFrhMonthPills(FRH.data.available_months || []);
    renderFrhWeekPills(FRH.data.available_weeks   || []);
    renderFrhKpis(FRH.data.kpis || {});
    renderFrhMonthChart();
    renderFrhMensualTable();
    renderFrhProductTable();
    renderFrhKpisW(FRH.data.kpis_w || {});
    renderFrhWeekChart();
    renderFrhClienteWTable();
    renderFrhProductWTable();
    _frhUpdateExportLinks();
  } catch(e) { console.error(e); }
}

function switchFrhTab(tab) {
  FRH.activeTab = tab;
  document.querySelectorAll(".frh-tab").forEach(btn =>
    btn.classList.toggle("frh-tab-active", btn.getAttribute("data-tab") === tab)
  );
  document.getElementById("frhTabConsulta").style.display = tab === "consulta" ? "" : "none";
  document.getElementById("frhTabMensual") .style.display = tab === "mensual"  ? "" : "none";
  document.getElementById("frhTabSemanal") .style.display = tab === "semanal"  ? "" : "none";
  if (tab === "consulta") {
    if (!FRH.consultaLoaded) searchFrhConsulta();
  } else {
    filterFrh();
  }
}

function _frhParams() {
  const p = new URLSearchParams();
  const c = document.getElementById("frhCliente")?.value || "";
  if (c) p.set("cliente", c);
  if (FRH.selMonths.size > 0) p.set("months", [...FRH.selMonths].sort().join(","));
  if (FRH.selWeeks.size  > 0) p.set("weeks",  [...FRH.selWeeks].sort().join(","));
  return p.toString();
}

function _frhPopulateSelects(data) {
  const cSel = document.getElementById("frhCliente");
  if (cSel && cSel.options.length <= 1) {
    (data.clientes || []).forEach(c => {
      const o = document.createElement("option");
      o.value = c; o.textContent = c; cSel.appendChild(o);
    });
  }
}

function _frhUpdateExportLinks() {
  const params = _frhParams();
  const qstr   = params ? "&" + params : "";
  const el     = document.getElementById("frhExportAll");
  const em     = document.getElementById("frhExportMensual");
  const es     = document.getElementById("frhExportSemanal");
  if (el) el.href = `/api/export/fr-historico-csv?tipo=general${qstr}`;
  if (em) em.href = `/api/export/fr-historico-csv?tipo=mensual${qstr}`;
  if (es) es.href = `/api/export/fr-historico-csv?tipo=semanal${qstr}`;
}

function renderFrhKpis(k) {
  const el = document.getElementById("frhKpis");
  if (!el) return;
  if (!k || !Object.keys(k).length) {
    el.innerHTML = `<div style="color:#bbb;padding:20px">Sin datos para los filtros seleccionados</div>`;
    return;
  }
  const varClass = k.variacion == null ? "neu" : k.variacion >= 0 ? "green" : "red";
  const varArrow = k.variacion == null ? "" : k.variacion >= 0 ? "▲" : "▼";
  const varAbs   = k.variacion != null ? Math.abs(k.variacion).toFixed(1) + "%" : "—";
  const boPct    = k.bo_pct != null ? k.bo_pct.toFixed(1) + "%" : "—";

  el.innerHTML = `
    <div class="kpi-s s-${varClass === 'neu' ? 'neu' : frSClass(k.fr_mtd)}">
      <div>
        <div class="kpi-s-lbl">${k.is_mtd ? "Fill Rate MTD" : "Fill Rate"}</div>
        <div class="kpi-s-val">${fmtPct(k.fr_mtd)}</div>
        <div class="kpi-s-sub">${esc(k.label_mes || "período seleccionado")}</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-${k.fr_mes_ant != null ? frSClass(k.fr_mes_ant) : 'neu'}">
      <div>
        <div class="kpi-s-lbl">FR Mes Anterior</div>
        <div class="kpi-s-val">${k.fr_mes_ant != null ? fmtPct(k.fr_mes_ant) : "—"}</div>
        <div class="kpi-s-sub">${esc(k.label_mes_ant || "mes previo")}</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-${varClass}">
      <div>
        <div class="kpi-s-lbl">Variación FR</div>
        <div class="kpi-s-val" style="font-size:22px">${varArrow} ${varAbs}</div>
        <div class="kpi-s-sub">vs ${esc(k.label_mes_ant || "mes anterior")}</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Valor Total Pedidos</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(k.val_tot)}</div>
        <div class="kpi-s-sub">período seleccionado</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Valor Facturado</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(k.val_fac)}</div>
        <div class="kpi-s-sub">efectivamente despachado</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-${k.bo_val > 0 ? 'red' : 'green'}">
      <div>
        <div class="kpi-s-lbl">Valor Back Order</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(k.bo_val)}</div>
        <div class="kpi-s-sub">BO% ${boPct}</div>
      </div><div class="kpi-s-dot"></div>
    </div>
  `;
}

function renderFrhMonthChart() {
  const ctx     = document.getElementById("frhMonthChart")?.getContext("2d");
  // 1 mes seleccionado → tendencia completa (12 meses); varios → solo meses seleccionados
  const monthly = FRH.selMonths.size > 1
    ? (FRH.data?.monthly || [])
    : (FRH.data?.monthly_all || []);
  if (!ctx || !monthly.length) return;

  if (FRH.monthChart) FRH.monthChart.destroy();

  const labels   = monthly.map(m => m.label);
  const frValues = monthly.map(m => m.fr);
  const ptColors = monthly.map(m => frhColorHex(m.fr));
  const ptRadii  = monthly.map(m =>
    FRH.selMonths.size === 0 || FRH.selMonths.has(`${m.year}-${m.month}`) ? 5 : 3
  );

  FRH.monthChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Fill Rate",
          data: frValues,
          borderColor: "#1a1a1a",
          backgroundColor: "transparent",
          borderWidth: 2,
          tension: 0.3,
          pointBackgroundColor: ptColors,
          pointBorderColor:     ptColors,
          pointRadius: ptRadii,
          pointHoverRadius: 8,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => ctx.datasetIndex === 0
              ? ` FR: ${ctx.raw.toFixed(1)}%`
              : ` Meta: ${ctx.raw}%`,
            afterBody: (items) => {
              const i = items[0]?.dataIndex;
              if (i == null) return [];
              const m = monthly[i];
              return [
                `Pedidos:   ${fmtMoney(m.val_tot)}`,
                `Facturado: ${fmtMoney(m.val_fac)}`,
                `BO:        ${fmtMoney(m.bo_val)}`,
              ];
            }
          }
        }
      },
      scales: {
        y: {
          min: 55, max: 100,
          ticks: { font: { family: "Montserrat", size: 9 }, callback: v => v + "%", maxTicksLimit: 5 },
          grid: { color: "#f0f0f0" }
        },
        x: {
          ticks: { font: { family: "Montserrat", size: 9, weight: "600" }, maxRotation: 0 },
          grid: { display: false }
        }
      }
    }
  });
}

function renderFrhWeekChart() {
  const ctx = document.getElementById("frhWeekChart")?.getContext("2d");
  if (!ctx) return;

  // Use weekly_all (last 12) when ≤1 week selected, else weekly (filtered)
  const weekly = FRH.selWeeks.size > 1
    ? (FRH.data?.weekly || [])
    : (FRH.data?.weekly_all || []);

  if (FRH.weekChart) { FRH.weekChart.destroy(); FRH.weekChart = null; }
  if (!weekly.length) return;

  FRH.weekChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: weekly.map(w => w.label_short),
      datasets: [{
        data: weekly.map(w => w.fr),
        borderColor: "#1a1a1a",
        backgroundColor: "rgba(26,26,26,0.06)",
        borderWidth: 1.5,
        pointRadius: 3,
        pointBackgroundColor: "#1a1a1a",
        tension: 0.3,
        fill: true,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => weekly[items[0]?.dataIndex]?.label || "",
            label: ctx  => ` FR: ${ctx.raw.toFixed(1)}%`,
            afterBody: items => {
              const w = weekly[items[0]?.dataIndex];
              if (!w) return [];
              return [`Pedidos: ${fmtMoney(w.val_tot)}`, `BO: ${fmtMoney(w.bo_val)}`];
            }
          }
        }
      },
      scales: {
        y: {
          min: 50, max: 100,
          ticks: { font: { family: "Montserrat", size: 10 }, callback: v => v + "%" },
          grid: { color: "#f0f0f0" }
        },
        x: {
          ticks: { font: { family: "Montserrat", size: 9, weight: "600" }, maxRotation: 45 },
          grid: { display: false }
        }
      }
    }
  });
}

function clearFrhFilters() {
  const el = document.getElementById("frhCliente");
  if (el) el.value = "";
  FRH.selMonths.clear();
  const _n = new Date();
  FRH.selMonths.add(`${_n.getFullYear()}-${_n.getMonth() + 1}`);
  FRH.selWeeks.clear();
  FRH.selWeeks.add(_curWeekMonday());
  filterFrh();
}

function renderFrhMonthPills(availMonths) {
  const container = document.getElementById("frhMonthPills");
  if (!container) return;
  container.innerHTML = availMonths.map(m => {
    const key    = `${m.year}-${m.num}`;
    const active = FRH.selMonths.has(key) ? " frh-month-pill-active" : "";
    return `<button class="frh-month-pill${active}" data-key="${key}" onclick="toggleFrhMonth('${key}')">${m.label}</button>`;
  }).join("");
}

function toggleFrhMonth(key) {
  if (FRH.selMonths.has(key)) {
    FRH.selMonths.delete(key);
  } else {
    FRH.selMonths.add(key);
  }
  document.querySelectorAll(".frh-month-pill").forEach(btn => {
    btn.classList.toggle("frh-month-pill-active", FRH.selMonths.has(btn.dataset.key));
  });
  filterFrh();
}

function clearFrhMonths() {
  FRH.selMonths.clear();
  document.querySelectorAll(".frh-month-pill").forEach(btn =>
    btn.classList.remove("frh-month-pill-active")
  );
  filterFrh();
}

function renderFrhWeekPills(availWeeks) {
  const container = document.getElementById("frhWeekPills");
  if (!container) return;
  container.innerHTML = availWeeks.map(w => {
    const active = FRH.selWeeks.has(w.key) ? " frh-month-pill-active" : "";
    return `<button class="frh-month-pill${active}" data-wkey="${w.key}"
      onclick="toggleFrhWeek('${w.key}')" title="${w.label}">${w.label_short}</button>`;
  }).join("");
}

function toggleFrhWeek(key) {
  if (FRH.selWeeks.has(key)) { FRH.selWeeks.delete(key); }
  else                        { FRH.selWeeks.add(key);    }
  document.querySelectorAll("[data-wkey]").forEach(btn =>
    btn.classList.toggle("frh-month-pill-active", FRH.selWeeks.has(btn.dataset.wkey))
  );
  filterFrh();
}

function clearFrhWeeks() {
  FRH.selWeeks.clear();
  document.querySelectorAll("[data-wkey]").forEach(btn =>
    btn.classList.remove("frh-month-pill-active")
  );
  filterFrh();
}

function renderFrhMensualTable() {
  const clients = FRH.data?.by_client || [];
  const body    = document.getElementById("frhMensualBody");
  const count   = document.getElementById("frhMensualCount");
  if (!body) return;
  if (count) count.textContent = `${clients.length} clientes`;

  if (!clients.length) {
    body.innerHTML = `<tr><td colspan="5" class="text-center py-4 text-muted">Sin datos para los filtros seleccionados</td></tr>`;
    return;
  }

  body.innerHTML = clients.map(c => `
    <tr>
      <td><strong>${esc(c.cliente)}</strong></td>
      <td style="text-align:center"><span class="fr-chip ${frChipBo(c.fr)}">${fmtPct(c.fr)}</span></td>
      <td style="text-align:center;font-weight:600">${c.despachos}</td>
      <td style="text-align:center">${fmtMoney(c.val_tot)}</td>
      <td style="text-align:center">${fmtMoney(c.val_fac)}</td>
      <td style="text-align:center" class="bo-val-warn">${fmtMoney(c.bo_val)}</td>
    </tr>`).join("");
}

function renderFrhProductTable() {
  const products = FRH.data?.by_product || [];
  const panel    = document.getElementById("frhProductPanel");
  const body     = document.getElementById("frhProductBody");
  const count    = document.getElementById("frhProductCount");
  const cliente  = document.getElementById("frhCliente")?.value || "";

  if (!panel) return;

  if (!cliente) {
    panel.style.display = "none";
    return;
  }

  panel.style.display = "";
  if (count) count.textContent = `${products.length} productos`;

  if (!body) return;
  if (!products.length) {
    body.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-muted">Sin datos para el período seleccionado</td></tr>`;
    return;
  }

  body.innerHTML = products.map((p, i) => {
    // Detalle rows HTML
    const detailRows = (p.rows || []).map(r => {
      const comentario = r.comentario
        ? `<span style="font-size:10px;color:#666">${esc(r.comentario)}</span>`
        : `<span style="color:#ccc">—</span>`;
      const boClass = r.bo_un > 0 ? "bo-un-cell" : "";
      return `<tr style="background:#f9f9f9">
        <td class="font-mono" style="font-size:10px;padding:6px 12px">${esc(r.oc)}</td>
        <td style="padding:6px 12px;font-size:10px">${esc(r.fecha)}</td>
        <td style="text-align:center;padding:6px 12px;font-size:10px">${fmtNum(r.un_sol)}</td>
        <td style="text-align:center;padding:6px 12px;font-size:10px">${fmtNum(r.un_asig)}</td>
        <td style="text-align:center;padding:6px 12px;font-size:10px" class="${boClass}">${fmtNum(r.bo_un)}</td>
        <td style="padding:6px 12px">${comentario}</td>
      </tr>`;
    }).join("");

    const detailTable = `
      <table class="spot-table w-100" style="border-top:2px solid #e4e4e4">
        <thead>
          <tr style="background:#f0f0f0">
            <th style="padding:6px 12px;font-size:8px">N° OC</th>
            <th style="padding:6px 12px;font-size:8px">F. Despacho</th>
            <th style="text-align:center;padding:6px 12px;font-size:8px">UN Sol.</th>
            <th style="text-align:center;padding:6px 12px;font-size:8px">UN Asig.</th>
            <th style="text-align:center;padding:6px 12px;font-size:8px">UN Perdidas</th>
            <th style="padding:6px 12px;font-size:8px">Comentario</th>
          </tr>
        </thead>
        <tbody>${detailRows}</tbody>
      </table>`;

    return `
      <tr>
        <td><strong>${esc(p.producto)}</strong></td>
        <td style="text-align:center"><span class="fr-chip ${frChipBo(p.fr)}">${fmtPct(p.fr)}</span></td>
        <td style="text-align:center">${fmtMoney(p.val_sol)}</td>
        <td style="text-align:center">${fmtMoney(p.val_asig)}</td>
        <td style="text-align:center" class="bo-val-warn">${fmtMoney(p.bo_val)}</td>
        <td style="text-align:center">
          <button class="clear-btn" style="font-size:9px;padding:3px 10px"
            onclick="toggleFrhProdDetail(${i}, this)">Ver →</button>
        </td>
      </tr>
      <tr id="frh-prod-detail-${i}" style="display:none">
        <td colspan="6" style="padding:0">${detailTable}</td>
      </tr>`;
  }).join("");
}

function toggleFrhProdDetail(idx, btn) {
  const row = document.getElementById(`frh-prod-detail-${idx}`);
  if (!row) return;
  const isOpen = row.style.display !== "none";
  row.style.display = isOpen ? "none" : "";
  btn.textContent   = isOpen ? "Ver →" : "Cerrar ↑";
}

function renderFrhKpisW(k) {
  const el = document.getElementById("frhKpisW");
  if (!el) return;
  if (!k || !Object.keys(k).length) {
    el.innerHTML = `<div style="color:#bbb;padding:20px">Sin datos para los filtros seleccionados</div>`;
    return;
  }

  const varClass = k.variacion == null ? "neu" : k.variacion >= 0 ? "green" : "red";
  const varArrow = k.variacion == null ? "" : k.variacion >= 0 ? "▲" : "▼";
  const varAbs   = k.variacion != null ? Math.abs(k.variacion).toFixed(1) + "%" : "—";
  const boPct    = k.bo_pct != null ? k.bo_pct.toFixed(1) + "%" : "—";

  el.innerHTML = `
    <div class="kpi-s s-${frSClass(k.fr)}">
      <div class="kpi-s-lbl">${k.is_cur_week ? "Fill Rate Semana Actual" : "Fill Rate"}</div>
      <div class="kpi-s-val">${fmtPct(k.fr)}</div>
      <div class="kpi-s-sub">${esc(k.label_periodo || "")}</div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div class="kpi-s-lbl">FR Semana Anterior</div>
      <div class="kpi-s-val">${k.fr_sem_ant != null ? fmtPct(k.fr_sem_ant) : "—"}</div>
      <div class="kpi-s-sub">${esc(k.label_sem_ant || "semana previa")}</div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-${varClass}">
      <div class="kpi-s-lbl">Variación FR</div>
      <div class="kpi-s-val">${varArrow} ${varAbs}</div>
      <div class="kpi-s-sub">vs ${esc(k.label_sem_ant || "semana anterior")}</div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div class="kpi-s-lbl">Valor Total OC</div>
      <div class="kpi-s-val">${fmtMoney(k.val_tot)}</div>
      <div class="kpi-s-sub">período seleccionado</div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div class="kpi-s-lbl">Valor Facturado</div>
      <div class="kpi-s-val">${fmtMoney(k.val_fac)}</div>
      <div class="kpi-s-sub">efectivamente despachado</div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-${k.bo_val > 0 ? "red" : "neu"}">
      <div class="kpi-s-lbl">Valor Back Order</div>
      <div class="kpi-s-val">${fmtMoney(k.bo_val)}</div>
      <div class="kpi-s-sub">BO${boPct !== "—" ? " " + boPct : ""}</div>
      <div class="kpi-s-dot"></div>
    </div>`;
}

function renderFrhClienteWTable() {
  const clients = FRH.data?.by_client_w || [];
  const body    = document.getElementById("frhClienteWBody");
  const count   = document.getElementById("frhClienteWCount");
  if (!body) return;
  if (count) count.textContent = `${clients.length} clientes`;

  if (!clients.length) {
    body.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-muted">Sin datos para los filtros seleccionados</td></tr>`;
    return;
  }

  body.innerHTML = clients.map(c => `
    <tr>
      <td><strong>${esc(c.cliente)}</strong></td>
      <td style="text-align:center"><span class="fr-chip ${frChipBo(c.fr)}">${fmtPct(c.fr)}</span></td>
      <td style="text-align:center;font-weight:600">${c.despachos}</td>
      <td style="text-align:center">${fmtMoney(c.val_tot)}</td>
      <td style="text-align:center">${fmtMoney(c.val_fac)}</td>
      <td style="text-align:center" class="bo-val-warn">${fmtMoney(c.bo_val)}</td>
    </tr>`).join("");
}

function renderFrhProductWTable() {
  const products = FRH.data?.by_product_w || [];
  const panel    = document.getElementById("frhProductWPanel");
  const body     = document.getElementById("frhProductWBody");
  const count    = document.getElementById("frhProductWCount");
  const cliente  = document.getElementById("frhCliente")?.value || "";

  if (!panel) return;
  if (!cliente) { panel.style.display = "none"; return; }

  panel.style.display = "";
  if (count) count.textContent = `${products.length} productos`;

  if (!body) return;
  if (!products.length) {
    body.innerHTML = `<tr><td colspan="6" class="text-center py-4 text-muted">Sin datos para el período seleccionado</td></tr>`;
    return;
  }

  body.innerHTML = products.map((p, i) => {
    const detailRows = (p.rows || []).map(r => {
      const comentario = r.comentario
        ? `<span style="font-size:10px;color:#666">${esc(r.comentario)}</span>`
        : `<span style="color:#ccc">—</span>`;
      const boClass = r.bo_un > 0 ? "bo-un-cell" : "";
      return `<tr style="background:#f9f9f9">
        <td class="font-mono" style="font-size:10px;padding:6px 12px">${esc(r.oc)}</td>
        <td style="padding:6px 12px;font-size:10px">${esc(r.fecha)}</td>
        <td style="text-align:center;padding:6px 12px;font-size:10px">${fmtNum(r.un_sol)}</td>
        <td style="text-align:center;padding:6px 12px;font-size:10px">${fmtNum(r.un_asig)}</td>
        <td style="text-align:center;padding:6px 12px;font-size:10px" class="${boClass}">${fmtNum(r.bo_un)}</td>
        <td style="padding:6px 12px">${comentario}</td>
      </tr>`;
    }).join("");

    const detailTable = `
      <table class="spot-table w-100" style="border-top:2px solid #e4e4e4">
        <thead>
          <tr style="background:#f0f0f0">
            <th style="padding:6px 12px;font-size:8px">N° OC</th>
            <th style="padding:6px 12px;font-size:8px">F. Despacho</th>
            <th style="text-align:center;padding:6px 12px;font-size:8px">UN Sol.</th>
            <th style="text-align:center;padding:6px 12px;font-size:8px">UN Asig.</th>
            <th style="text-align:center;padding:6px 12px;font-size:8px">UN Perdidas</th>
            <th style="padding:6px 12px;font-size:8px">Comentario</th>
          </tr>
        </thead>
        <tbody>${detailRows}</tbody>
      </table>`;

    return `
      <tr>
        <td><strong>${esc(p.producto)}</strong></td>
        <td style="text-align:center"><span class="fr-chip ${frChipBo(p.fr)}">${fmtPct(p.fr)}</span></td>
        <td style="text-align:center">${fmtMoney(p.val_sol)}</td>
        <td style="text-align:center">${fmtMoney(p.val_asig)}</td>
        <td style="text-align:center" class="bo-val-warn">${fmtMoney(p.bo_val)}</td>
        <td style="text-align:center">
          <button class="clear-btn" style="font-size:9px;padding:3px 10px"
            onclick="toggleFrhProdWDetail(${i}, this)">Ver →</button>
        </td>
      </tr>
      <tr id="frh-prod-w-detail-${i}" style="display:none">
        <td colspan="6" style="padding:0">${detailTable}</td>
      </tr>`;
  }).join("");
}

function toggleFrhProdWDetail(idx, btn) {
  const row = document.getElementById(`frh-prod-w-detail-${idx}`);
  if (!row) return;
  const isOpen = row.style.display !== "none";
  row.style.display = isOpen ? "none" : "";
  btn.textContent   = isOpen ? "Ver →" : "Cerrar ↑";
}

// ── CONSULTA ──────────────────────────────────────────────────────

function _frhConsultaPopulateClientes(clientes) {
  const sel = document.getElementById("cCliente");
  if (!sel || sel.options.length > 1) return;
  clientes.forEach(c => {
    const o = document.createElement("option");
    o.value = c; o.textContent = c; sel.appendChild(o);
  });
}

function debounceFrhConsulta() {
  clearTimeout(FRH.consultaDebounce);
  FRH.consultaDebounce = setTimeout(searchFrhConsulta, 380);
}

async function searchFrhConsulta() {
  const oc      = (document.getElementById("cOcSearch")?.value  || "").trim();
  const cliente = document.getElementById("cCliente")?.value    || "";
  const desde   = document.getElementById("cFechaDesde")?.value || "";
  const hasta   = document.getElementById("cFechaHasta")?.value || "";

  const hasFilter = oc || cliente || desde || hasta;
  if (!hasFilter) { renderFrhConsultaTable([], false); return; }

  const p = new URLSearchParams();
  if (oc)      p.set("oc",          oc);
  if (cliente) p.set("cliente",     cliente);
  if (desde)   p.set("fecha_desde", desde);
  if (hasta)   p.set("fecha_hasta", hasta);

  const sub = document.getElementById("cOcSub");
  if (sub) sub.textContent = "Buscando…";

  try {
    const res  = await fetch("/api/fr-historico/consulta?" + p.toString());
    const data = await res.json();
    renderFrhConsultaTable(data.ocs || [], true);

    // OC exacta con una sola coincidencia → auto-expandir
    if (oc && data.ocs.length === 1) {
      const btn = document.querySelector(`#cOcBody button[data-oc-idx="0"]`);
      if (btn) toggleFrhConsultaDetail(0, data.ocs[0].oc, data.ocs[0].cliente, btn);
    }
  } catch(e) { console.error("Error consulta:", e); }
}

function renderFrhConsultaTable(ocs, searched) {
  const body  = document.getElementById("cOcBody");
  const count = document.getElementById("cOcCount");
  const sub   = document.getElementById("cOcSub");
  if (!body) return;

  if (!searched) {
    if (count) count.textContent = "—";
    if (sub)   sub.textContent   = "Ingresa una OC o aplica filtros para buscar";
    body.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-muted">Ingresa una OC o aplica filtros para buscar</td></tr>`;
    const kg = document.getElementById("cKpiGrid");
    if (kg) kg.style.display = "none";
    return;
  }

  if (count) count.textContent = `${ocs.length} resultado${ocs.length !== 1 ? "s" : ""}`;
  if (sub)   sub.textContent   = "";

  _cRenderKpis(ocs);

  if (!ocs.length) {
    body.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-muted">Sin resultados para los filtros aplicados</td></tr>`;
    return;
  }

  body.innerHTML = ocs.map((o, i) => `
    <tr class="frh-week-row">
      <td><strong style="${o.pendiente ? 'background:#fef9c3;color:#854d0e;padding:2px 6px;border-radius:4px' : ''}">${esc(o.cliente)}</strong></td>
      <td class="font-mono" style="font-size:11px">${esc(o.oc)}</td>
      <td style="text-align:center">${esc(o.fecha)}</td>
      <td style="text-align:center">${fmtMoney(o.val_tot)}</td>
      <td style="text-align:center">${fmtMoney(o.val_fac)}</td>
      <td style="text-align:center"><span class="fr-chip ${frChipBo(o.fr)}">${fmtPct(o.fr)}</span></td>
      <td style="text-align:center">
        <button class="clear-btn" style="font-size:9px;padding:3px 10px"
          data-oc-idx="${i}"
          onclick="toggleFrhConsultaDetail(${i},'${esc(o.oc)}','${esc(o.cliente)}',this)">Ver →</button>
      </td>
    </tr>
    <tr id="c-oc-detail-${i}" style="display:none;background:#fafafa">
      <td colspan="7" style="padding:0">
        <div id="c-oc-detail-content-${i}" style="padding:4px 0 8px"></div>
      </td>
    </tr>`).join("");
}

function _cRenderKpis(ocs) {
  const grid = document.getElementById("cKpiGrid");
  if (!grid) return;

  if (!ocs.length) { grid.style.display = "none"; return; }

  const totalOcs = ocs.length;
  const valOc    = ocs.reduce((s, o) => s + (o.val_tot || 0), 0);
  const valFac   = ocs.reduce((s, o) => s + (o.val_fac || 0), 0);
  const valBo    = valOc - valFac;
  const fr       = valOc > 0 ? (valFac / valOc * 100).toFixed(1) : null;
  const frColor  = fr == null ? "#6b7280" : fr >= 95 ? "#16a34a" : fr >= 90 ? "#ca8a04" : fr >= 80 ? "#ea580c" : "#dc2626";
  const frBg     = fr == null ? "#f3f4f6" : fr >= 95 ? "#dcfce7" : fr >= 90 ? "#fef9c3" : fr >= 80 ? "#ffedd5" : "#fee2e2";

  const kpi = (label, value, sub = "", accent = "#1a1a1a", bg = "#fff") => `
    <div style="background:${bg};border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px">
      <div style="font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888;margin-bottom:6px">${label}</div>
      <div style="font-size:22px;font-weight:800;color:${accent};line-height:1.1">${value}</div>
      ${sub ? `<div style="font-size:10px;color:#aaa;margin-top:4px">${sub}</div>` : ""}
    </div>`;

  grid.style.display = "grid";
  grid.innerHTML =
    kpi("Fill Rate", fr != null ? `${fr}%` : "—", fr != null ? `${fmtMoney(valFac)} / ${fmtMoney(valOc)}` : "", frColor, frBg) +
    kpi("Cantidad de OCs", fmtNum(totalOcs), `${ocs.filter(o => o.pendiente).length} pendiente${ocs.filter(o=>o.pendiente).length!==1?"s":""}`) +
    kpi("Valor Total OC",  fmtMoney(valOc),  "valor solicitado") +
    kpi("Valor Facturado", fmtMoney(valFac), "despacho confirmado") +
    kpi("Venta Perdida o BO Valorizado", fmtMoney(valBo > 0 ? valBo : 0), "diferencia no facturada", valBo > 0 ? "#dc2626" : "#16a34a");
}

async function toggleFrhConsultaDetail(idx, ocKey, clienteKey, btn) {
  const row     = document.getElementById(`c-oc-detail-${idx}`);
  const content = document.getElementById(`c-oc-detail-content-${idx}`);
  if (!row || !content) return;

  const isOpen = row.style.display !== "none";
  if (isOpen) {
    row.style.display = "none";
    btn.textContent   = "Ver →";
    return;
  }

  row.style.display = "";
  btn.textContent   = "Cerrar ↑";

  if (!content.dataset.loaded) {
    content.innerHTML = `<div style="color:#bbb;padding:12px 16px;font-size:11px">Cargando…</div>`;
    try {
      const params = clienteKey ? `?cliente=${encodeURIComponent(clienteKey)}` : "";
      const res  = await fetch(`/api/fr-historico/consulta/${encodeURIComponent(ocKey)}${params}`);
      const data = await res.json();
      content.dataset.loaded = "1";
      content.innerHTML = _buildConsultaDetailTable(data.detail || []);
    } catch(e) {
      content.innerHTML = `<div style="color:red;padding:12px">Error al cargar detalle</div>`;
    }
  }
}

function _buildConsultaDetailTable(rows) {
  if (!rows.length) return `<div style="color:#bbb;padding:12px 16px;font-size:11px">Sin líneas de detalle</div>`;
  const rowsHtml = rows.map(r => {
    const boClass  = r.bo_un  > 0 ? "bo-un-cell"  : "";
    const boValCls = r.bo_val > 0 ? "bo-val-warn"  : "";
    const comentario = r.comentario
      ? `<span style="font-size:10px;color:#666">${esc(r.comentario)}</span>`
      : `<span style="color:#ccc">—</span>`;
    return `<tr style="background:#fafafa">
      <td style="padding:6px 12px"><strong>${esc(r.producto)}</strong></td>
      <td style="text-align:center;padding:6px 8px"><span class="fr-chip ${frChipBo(r.fr)}">${fmtPct(r.fr)}</span></td>
      <td style="text-align:center;padding:6px 8px;font-size:11px">${fmtNum(r.un_sol)}</td>
      <td style="text-align:center;padding:6px 8px;font-size:11px">${fmtNum(r.un_asig)}</td>
      <td style="text-align:center;padding:6px 8px;font-size:11px" class="${boClass}">${fmtNum(r.bo_un)}</td>
      <td style="text-align:center;padding:6px 8px;font-size:11px">${fmtMoney(r.val_tot)}</td>
      <td style="text-align:center;padding:6px 8px;font-size:11px">${fmtMoney(r.val_fac)}</td>
      <td style="text-align:center;padding:6px 8px;font-size:11px" class="${boValCls}">${fmtMoney(r.bo_val)}</td>
      <td style="padding:6px 8px">${comentario}</td>
    </tr>`;
  }).join("");

  return `<table class="spot-table w-100" style="border-top:2px solid #e4e4e4">
    <thead>
      <tr style="background:#f0f0f0">
        <th style="padding:6px 12px;font-size:8px">Producto</th>
        <th style="text-align:center;padding:6px 8px;font-size:8px">Fill Rate</th>
        <th style="text-align:center;padding:6px 8px;font-size:8px">UN Sol.</th>
        <th style="text-align:center;padding:6px 8px;font-size:8px">UN Asig.</th>
        <th style="text-align:center;padding:6px 8px;font-size:8px">UN Perdidas</th>
        <th style="text-align:center;padding:6px 8px;font-size:8px">Valor OC</th>
        <th style="text-align:center;padding:6px 8px;font-size:8px">Valor Facturado</th>
        <th style="text-align:center;padding:6px 8px;font-size:8px">Valor BO</th>
        <th style="padding:6px 8px;font-size:8px">Comentario</th>
      </tr>
    </thead>
    <tbody>${rowsHtml}</tbody>
  </table>`;
}

function clearFrhConsulta() {
  const ids = ["cOcSearch", "cFechaDesde", "cFechaHasta"];
  ids.forEach(id => { const el = document.getElementById(id); if (el) el.value = ""; });
  const cSel = document.getElementById("cCliente"); if (cSel) cSel.value = "";
  renderFrhConsultaTable([], false);
  // noop — detail rows are inline
}

function renderFrhRanking(r) {
  const el = document.getElementById("frhRanking");
  if (!el || !r.mejor) { if (el) el.innerHTML = `<div style="color:#bbb;font-size:11px;padding:8px">Sin datos suficientes</div>`; return; }

  el.innerHTML = `
    <div style="display:flex;gap:24px;flex-wrap:wrap">
      <div style="flex:1;min-width:180px">
        <div style="font-size:8px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#16a34a;margin-bottom:6px">Mejor Mes</div>
        <div style="font-size:28px;font-weight:800;color:#16a34a;letter-spacing:-1px">${fmtPct(r.mejor.fr)}</div>
        <div style="font-size:11px;font-weight:600;color:#555;margin-top:4px">${esc(r.mejor.label)}</div>
      </div>
      <div style="width:1px;background:#f0f0f0"></div>
      <div style="flex:1;min-width:180px">
        <div style="font-size:8px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#dc2626;margin-bottom:6px">Peor Mes</div>
        <div style="font-size:28px;font-weight:800;color:#dc2626;letter-spacing:-1px">${fmtPct(r.peor.fr)}</div>
        <div style="font-size:11px;font-weight:600;color:#555;margin-top:4px">${esc(r.peor.label)}</div>
      </div>
      <div style="width:1px;background:#f0f0f0"></div>
      <div style="flex:2;min-width:200px">
        <div style="font-size:8px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#666;margin-bottom:8px">Evolución (sparkline)</div>
        ${(FRH.data?.monthly || []).map(m => {
          const w = Math.round(m.fr * 0.8);
          return `<span title="${m.label}: ${m.fr}%" style="display:inline-block;width:14px;height:${w}px;background:${frhColorHex(m.fr)};border-radius:2px;margin-right:2px;vertical-align:bottom"></span>`;
        }).join("")}
      </div>
    </div>`;
}

function frSClass(fr) {
  if (fr >= 95) return "green";
  if (fr >= 85) return "yellow";
  if (fr >= 80) return "orange";
  return "red";
}

function frhColorHex(fr) {
  if (fr >= 95) return "#16a34a";
  if (fr >= 85) return "#ca8a04";
  if (fr >= 80) return "#ea580c";
  return "#dc2626";
}

// ══ DETALLE BACK ORDER ═══════════════════════════════════════════

const BO = {
  rows: [],        // all rows from API
  filtered: [],    // currently filtered
  lossChart: null,
};

async function loadBoDetail() {
  try {
    const res  = await fetch("/api/backorder-detail");
    const data = await res.json();
    BO.rows     = data.rows || [];
    BO.filtered = BO.rows;

    // Poblar select de clientes
    const sel = document.getElementById("boFilterCliente");
    if (sel) {
      const clientes = [...new Set(BO.rows.map(r => r.cliente))].sort();
      sel.innerHTML = `<option value="">Todos los clientes</option>` +
        clientes.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    }

    renderBoDetail(BO.filtered);
    renderLossTree(BO.filtered);
  } catch(e) {
    console.error("Error cargando BO detalle:", e);
  }
}

function renderBoDetailKpis(rows) {
  const kpis = document.getElementById("boDetailKpis");
  if (!kpis) return;

  const totalUn    = rows.reduce((s, r) => s + r.bo_un, 0);
  const totalVal   = rows.reduce((s, r) => s + r.bo_valorizado, 0);
  const skusAfect  = rows.length;

  kpis.innerHTML = `
    <div class="kpi-s s-red">
      <div>
        <div class="kpi-s-lbl">Total UN Pendientes</div>
        <div class="kpi-s-val">${fmtNum(totalUn)}</div>
        <div class="kpi-s-sub">unidades con back order</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-${totalVal > 0 ? 'red' : 'green'}">
      <div>
        <div class="kpi-s-lbl">BO Valorizado Total</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(totalVal)}</div>
        <div class="kpi-s-sub">impacto económico pendiente</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">SKUs Afectados</div>
        <div class="kpi-s-val">${fmtNum(skusAfect)}</div>
        <div class="kpi-s-sub">líneas con unidades pendientes</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
  `;
}

function renderBoDetail(rows) {
  renderBoDetailKpis(rows);

  const tbody = document.getElementById("boDetailBody");
  const count = document.getElementById("boDetailCount");
  if (!tbody) return;

  if (count) count.textContent = `${rows.length} líneas`;
  setEl("badgeBoDetalle", rows.length);

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:40px 0;color:#ccc">
      <div style="font-size:13px;font-weight:600;letter-spacing:1px;text-transform:uppercase">Sin back order pendiente</div>
    </td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(r => {
    const frClass = frChipBo(r.fill_rate);
    const fdClass = r.es_vencida ? "f-venc" : "f-ok";
    const boValClass = `bo-level-${r.bo_level}`;
    const comentTip = r.comentarios ? ` title="${esc(r.comentarios)}"` : "";
    return `
      <tr>
        <td><strong>${esc(r.cliente)}</strong></td>
        <td class="font-mono" style="font-size:10px">${esc(r.oc)}</td>
        <td><span class="${fdClass}">${esc(r.fecha_despacho)}</span></td>
        <td style="font-size:10px;max-width:180px">${esc(r.producto)}</td>
        <td class="col-money">${fmtNum(r.un_solicitadas)}</td>
        <td class="col-money">${fmtNum(r.un_asignadas)}</td>
        <td class="col-money bo-un-cell">${fmtNum(r.bo_un)}</td>
        <td><span class="fr-chip ${frClass}">${fmtPct(r.fill_rate)}</span></td>
        <td class="col-money ${boValClass}">${fmtMoney(r.bo_valorizado)}</td>
        <td><div class="bo-comentario"${comentTip}>${esc(r.comentarios) || "<span style='color:#ccc'>—</span>"}</div></td>
      </tr>
    `;
  }).join("");
}

function filterBoDetail() {
  const q        = (document.getElementById("boSearch")?.value         || "").toLowerCase().trim();
  const cliente  = (document.getElementById("boFilterCliente")?.value  || "").toLowerCase();
  const oc       = (document.getElementById("boFilterOc")?.value       || "").toLowerCase().trim();
  const producto = (document.getElementById("boFilterProducto")?.value || "").toLowerCase().trim();

  const hasFilter = q || cliente || oc || producto;
  const btnClear  = document.getElementById("btnClearBoFilters");
  if (btnClear) btnClear.style.display = hasFilter ? "" : "none";

  let filtered = BO.rows;
  if (q)        filtered = filtered.filter(r =>
    r.cliente.toLowerCase().includes(q) ||
    r.oc.toLowerCase().includes(q)      ||
    r.producto.toLowerCase().includes(q));
  if (cliente)  filtered = filtered.filter(r => r.cliente.toLowerCase() === cliente);
  if (oc)       filtered = filtered.filter(r => r.oc.toLowerCase().includes(oc));
  if (producto) filtered = filtered.filter(r => r.producto.toLowerCase().includes(producto));

  BO.filtered = filtered;

  // Actualizar link CSV con los mismos filtros
  const csvLink = document.getElementById("boCsvLink");
  if (csvLink) {
    const params = new URLSearchParams();
    if (q)       params.set("q",       q);
    if (cliente) params.set("cliente", cliente);
    if (oc)      params.set("oc",      oc);
    if (producto) params.set("producto", producto);
    csvLink.href = "/api/export/backorder-csv" + (params.toString() ? "?" + params.toString() : "");
  }

  renderBoDetail(filtered);
  renderLossTree(filtered);
}

function clearBoFilters() {
  ["boSearch","boFilterOc","boFilterProducto"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const sel = document.getElementById("boFilterCliente");
  if (sel) sel.value = "";
  const btnClear = document.getElementById("btnClearBoFilters");
  if (btnClear) btnClear.style.display = "none";
  BO.filtered = BO.rows;
  renderBoDetail(BO.rows);
  renderLossTree(BO.rows);
  const csvLink = document.getElementById("boCsvLink");
  if (csvLink) csvLink.href = "/api/export/backorder-csv";
}

function renderLossTree(rows) {
  const ctx = document.getElementById("lossTreeChart")?.getContext("2d");
  const tbl = document.getElementById("lossTreeTable");
  if (!ctx) return;

  // Agrupar por categoría árbol de pérdida
  const groups = {};
  rows.forEach(r => {
    const k = (r.categoria_arbol && r.categoria_arbol.trim()) ? r.categoria_arbol.trim() : "Sin clasificar";
    if (!groups[k]) groups[k] = { bo_un: 0, bo_val: 0, items: [] };
    groups[k].bo_un  += r.bo_un;
    groups[k].bo_val += r.bo_valorizado;
    groups[k].items.push(r);
  });

  const entries  = Object.entries(groups).sort((a, b) => b[1].bo_val - a[1].bo_val);
  const totalVal = entries.reduce((s, [, v]) => s + v.bo_val, 0);
  const labels   = entries.map(([k]) => k);
  const values   = entries.map(([, v]) => v.bo_val);
  const units    = entries.map(([, v]) => v.bo_un);
  const skuCnt   = entries.map(([, v]) => v.items.length);

  const COLORS = ["#dc2626","#2563eb","#16a34a","#7c3aed","#ea580c","#0891b2","#db2777","#ca8a04","#65a30d","#b45309"];
  const bgColors = entries.map((_, i) => COLORS[i % COLORS.length]);

  if (BO.lossChart) BO.lossChart.destroy();
  BO.lossChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data: values, backgroundColor: bgColors.map(c => c + "dd"), borderColor: bgColors, borderWidth: 2, hoverOffset: 8 }]
    },
    options: {
      responsive: true,
      cutout: "52%",
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => { const pct = totalVal > 0 ? ((ctx.raw / totalVal)*100).toFixed(1) : 0; return ` ${fmtMoney(ctx.raw)}  (${pct}%)`; },
            afterLabel: ctx => ` ${fmtNum(units[ctx.dataIndex])} UN · ${skuCnt[ctx.dataIndex]} SKU`,
          }
        }
      }
    }
  });

  if (!tbl) return;
  if (!entries.length) { tbl.innerHTML = ""; return; }

  const rowsHtml = entries.map(([k, v], i) => {
    const pct    = totalVal > 0 ? ((v.bo_val / totalVal) * 100).toFixed(1) : "0.0";
    const uid    = `lt-skus-${i}`;
    const skuRows = v.items.map(r => `
      <tr style="background:#fafafa">
        <td colspan="2" style="padding:5px 12px 5px 36px;font-size:10px;color:#444">${esc(r.producto)}</td>
        <td style="padding:5px 10px;text-align:right;font-size:10px;color:#666">${fmtPct(r.fill_rate)}</td>
        <td style="padding:5px 10px;text-align:right;font-size:10px;font-weight:600;color:#1a1a1a;font-variant-numeric:tabular-nums">${fmtMoney(r.bo_valorizado)}</td>
        <td style="padding:5px 10px;text-align:right;font-size:10px;color:#666">${fmtNum(r.bo_un)}</td>
        <td style="padding:5px 10px"></td>
      </tr>`).join("");

    return `
      <tr style="border-bottom:1px solid #f0f0f0">
        <td style="padding:8px 10px"><div style="width:12px;height:12px;border-radius:3px;background:${bgColors[i]}"></div></td>
        <td style="padding:8px 10px;font-weight:600;color:#1a1a1a">${esc(k)}</td>
        <td style="padding:8px 10px;text-align:right">
          <div style="display:flex;align-items:center;justify-content:flex-end;gap:6px">
            <div style="width:60px;height:6px;background:#f0f0f0;border-radius:3px;overflow:hidden">
              <div style="width:${pct}%;height:100%;background:${bgColors[i]};border-radius:3px"></div>
            </div>
            <span style="font-weight:700;color:#333;min-width:36px;text-align:right">${pct}%</span>
          </div>
        </td>
        <td style="padding:8px 10px;text-align:right;font-weight:700;color:#1a1a1a;font-variant-numeric:tabular-nums">${fmtMoney(v.bo_val)}</td>
        <td style="padding:8px 10px;text-align:right;color:#555">${fmtNum(v.bo_un)}</td>
        <td style="padding:8px 10px;text-align:right">
          <button onclick="toggleLtSkus('${uid}',this)"
            style="background:none;border:1px solid #e4e4e4;border-radius:4px;padding:3px 8px;font-size:9px;font-family:inherit;font-weight:700;color:#555;cursor:pointer;letter-spacing:.3px;white-space:nowrap">
            ${v.items.length} SKU ▼
          </button>
        </td>
      </tr>
      <tr id="${uid}" style="display:none;border-bottom:1px solid #e8e8e8">
        <td colspan="6" style="padding:0">
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr style="background:#f5f5f5">
                <th colspan="2" style="padding:5px 12px 5px 36px;text-align:left;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">Producto</th>
                <th style="padding:5px 10px;text-align:right;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">FR</th>
                <th style="padding:5px 10px;text-align:right;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">BO Val.</th>
                <th style="padding:5px 10px;text-align:right;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#888">UN</th>
                <th></th>
              </tr>
            </thead>
            <tbody>${skuRows}</tbody>
          </table>
        </td>
      </tr>`;
  }).join("");

  tbl.innerHTML = `
    <table style="width:100%;border-collapse:collapse;font-size:11px">
      <thead>
        <tr style="border-bottom:2px solid #e8e8e8">
          <th style="padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666;width:24px"></th>
          <th style="text-align:left;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">Motivo</th>
          <th style="text-align:right;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">% del BO</th>
          <th style="text-align:right;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">Valorizado</th>
          <th style="text-align:right;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">UN Pend.</th>
          <th style="text-align:right;padding:6px 10px;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#666">SKUs</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
      <tfoot>
        <tr style="border-top:2px solid #e8e8e8;background:#fafafa">
          <td colspan="2" style="padding:8px 10px;font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:#333">Total</td>
          <td style="padding:8px 10px;text-align:right;font-weight:700">100%</td>
          <td style="padding:8px 10px;text-align:right;font-weight:700;color:#dc2626;font-variant-numeric:tabular-nums">${fmtMoney(totalVal)}</td>
          <td style="padding:8px 10px;text-align:right;font-weight:700">${fmtNum(entries.reduce((s,[,v])=>s+v.bo_un,0))}</td>
          <td style="padding:8px 10px;text-align:right;font-weight:700">${entries.reduce((s,[,v])=>s+v.items.length,0)}</td>
        </tr>
      </tfoot>
    </table>`;
}

function toggleLtSkus(uid, btn) {
  const row = document.getElementById(uid);
  if (!row) return;
  const open = row.style.display !== "none";
  row.style.display = open ? "none" : "";
  btn.textContent   = btn.textContent.replace(open ? "▲" : "▼", open ? "▼" : "▲");
}

function frChipBo(fr) {
  if (fr >= 95) return "c-green";
  if (fr >= 85) return "c-yellow";
  if (fr >= 80) return "c-orange";
  return "c-red";
}

// ── SECCIONES ─────────────────────────────────────────────────
function showSection(name) {
  const sections = ["dashboard","fillrate","backorder","bodetalle","frhistorico","frmes","spotia","trackingpt"];
  sections.forEach(s => {
    const el = document.getElementById(`section${cap(s)}`);
    if (el) el.classList.toggle("d-none", s !== name);
  });

  // Activar sidebar item
  document.querySelectorAll(".sb-item").forEach(el => el.classList.remove("active"));
  event?.currentTarget?.classList.add("active");

  if (name === "fillrate")    initFrChart();
  if (name === "backorder")   initBoChart();
  if (name === "bodetalle")   loadBoDetail();
  if (name === "frhistorico") loadFrHistorico();
  if (name === "frmes")       loadFrMes();
  if (name === "spotia")      initSpotia();
  if (name === "trackingpt")  loadTrackingPT();
}

// ── GRÁFICOS ──────────────────────────────────────────────────
function initFrChart() {
  const data = STATE.kpis.fr_por_cliente || [];
  if (!data.length) return;

  const ctx = document.getElementById("frChart")?.getContext("2d");
  if (!ctx) return;
  if (STATE.frChart) STATE.frChart.destroy();

  const labels = data.map(d => d.cliente);
  const values = data.map(d => d.fr);
  const colors = data.map(d => semColorHex(d.color));

  STATE.frChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Fill Rate %",
        data: values,
        backgroundColor: colors,
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: ctx => ` ${ctx.raw.toFixed(1)}%` }
        }
      },
      scales: {
        x: {
          min: 60, max: 100,
          grid: { color: "#f0f0f0" },
          ticks: {
            font: { family: "Montserrat", size: 10 },
            callback: v => `${v}%`,
          }
        },
        y: {
          grid: { display: false },
          ticks: { font: { family: "Montserrat", size: 11, weight: "600" } }
        }
      }
    }
  });
}

function initBoChart() {
  const clientes = STATE.kpis.top_clientes || [];
  if (!clientes.length) return;

  const ctx = document.getElementById("boChart")?.getContext("2d");
  if (!ctx) return;
  if (STATE.boChart) STATE.boChart.destroy();

  STATE.boChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: clientes.map(c => c.cliente),
      datasets: [{
        label: "UN Back Order",
        data: clientes.map(c => c.bo_un),
        backgroundColor: clientes.map(c => semColorHex(c.semaforo)),
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: { grid: { color: "#f0f0f0" }, ticks: { font: { family: "Montserrat", size: 10 } } },
        x: { grid: { display: false }, ticks: { font: { family: "Montserrat", size: 11, weight: "600" } } }
      }
    }
  });
}

// ── CLIENTES GRID ─────────────────────────────────────────────
function renderClientesGrid() {
  const grid     = document.getElementById("clientesGrid");
  const clientes = STATE.kpis.top_clientes || [];
  if (!grid) return;

  if (!clientes.length) {
    grid.innerHTML = `<div style="color:#bbb;text-align:center;padding:40px">Sin datos</div>`;
    return;
  }

  grid.innerHTML = clientes.map(c => `
    <div class="cliente-card ${c.fr_color}" onclick="filterByCliente('${esc(c.cliente)}');showSection('dashboard')">
      <div class="cc-name">${esc(c.cliente)}</div>
      <div class="cc-fr ${c.fr_color}">${fmtPct(c.fr)}</div>
      <div class="cc-sub">Fill Rate mes actual</div>
      <div class="cc-bar-wrap">
        <div class="cc-bar" style="width:${c.fr}%;background:${semColorHex(c.semaforo)}"></div>
      </div>
      <div class="cc-stats">
        <span><strong>${fmtNum(c.bo_un)}</strong> UN pend.</span>
        <span><strong>${c.n_ocs}</strong> OC${c.n_ocs !== 1 ? 's' : ''}</span>
      </div>
    </div>
  `).join("");
}

// ── NAVBAR ────────────────────────────────────────────────────
function updateNavbar(data) {
  setEl("navTime",  `Actualizado: ${data.updated_at || "—"} · Próximo refresco en`);
  setEl("navMes",   data.mes_label || "");
  setEl("sidebarTime", data.updated_at || "—");

  const dot = document.getElementById("statusDot");
  if (dot) {
    dot.className = `dot-live${data.error ? " error" : ""}`;
    if (dot.classList.contains("loading")) dot.classList.remove("loading");
  }
}

// ── REFRESH MANUAL ────────────────────────────────────────────
async function manualRefresh() {
  const btn = document.getElementById("btnRefreshNav");
  const dot = document.getElementById("statusDot");
  if (btn) { btn.disabled = true; btn.textContent = "↻ Actualizando..."; }
  if (dot) dot.classList.add("loading");

  try {
    await fetch("/api/refresh", { method: "POST" });
    await loadAll();
    resetCountdown();
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "↻ Actualizar"; }
    if (dot) dot.classList.remove("loading");
  }
}

// ── COUNTDOWN ────────────────────────────────────────────────
function startCountdown() {
  STATE.countdown = STATE.refreshMinutes * 60;
  STATE.countdownTimer = setInterval(() => {
    STATE.countdown--;
    const mins = Math.floor(STATE.countdown / 60);
    const secs = STATE.countdown % 60;
    setEl("countdown", `${mins}m ${secs.toString().padStart(2,"0")}s`);

    // Mostrar próximo en navbar
    const navTime = document.getElementById("navTime");
    if (navTime && STATE.kpis.updated_at) {
      navTime.textContent = `Actualizado: ${STATE.kpis.updated_at} · Próximo en ${mins}m`;
    }

    if (STATE.countdown <= 0) {
      resetCountdown();
      loadAll();
    }
  }, 1000);
}

function resetCountdown() {
  STATE.countdown = STATE.refreshMinutes * 60;
}

// ── ERRORES ───────────────────────────────────────────────────
function showError(msg) {
  const banner = document.getElementById("errorBanner");
  const msgEl  = document.getElementById("errorMsg");
  if (banner) banner.classList.remove("d-none");
  if (msgEl)  msgEl.textContent = msg;
}

function hideError() {
  document.getElementById("errorBanner")?.classList.add("d-none");
}

// ── UTILS ─────────────────────────────────────────────────────
function fmtPct(v) {
  if (v == null) return "—";
  return `${parseFloat(v).toFixed(1)}%`;
}

function fmtMoney(v) {
  if (v == null || v === "" || v === 0) return "—";
  const n = Math.round(parseFloat(v));
  return "$ " + n.toLocaleString("es-CL");
}

function fmtNum(v) {
  if (v == null || v === "") return "—";
  return parseInt(v).toLocaleString("es-CL");
}

function esc(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g,"&amp;")
    .replace(/</g,"&lt;")
    .replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;");
}

function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = val ?? "—";
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function colorClass(c) {
  const map = { green: "c-green", yellow: "c-yellow", orange: "c-orange", red: "c-red" };
  return map[c] || "c-red";
}

function sClass(c) {   // para cards pequeñas (s-green / s-yellow / …)
  const map = { green: "green", yellow: "yellow", orange: "orange", red: "red" };
  return map[c] || "neu";
}

function semColorHex(c) {
  const map = { green: "#16a34a", yellow: "#ca8a04", orange: "#ea580c", red: "#dc2626" };
  return map[c] || "#dc2626";
}

function boColor(fr) {
  if (fr >= 95) return "green";
  if (fr >= 90) return "yellow";
  if (fr >= 80) return "orange";
  return "red";
}


// ══════════════════════════════════════════════════════════════════
//  SpotIA — Asistente Conversacional
// ══════════════════════════════════════════════════════════════════

const SPOTIA = {
  history: [],        // mensajes en memoria
  loading: false,
};

const _SPOTIA_KEY = "spotia_history";
const _SPOTIA_TTL = 48 * 60 * 60 * 1000; // 48 horas en ms

function _spotiaReadStorage() {
  try {
    const raw = localStorage.getItem(_SPOTIA_KEY);
    if (!raw) return [];
    const entries = JSON.parse(raw);
    const cutoff = Date.now() - _SPOTIA_TTL;
    return entries.filter(e => e.ts && e.ts > cutoff);
  } catch { return []; }
}

function _spotiaWriteStorage(entries) {
  try { localStorage.setItem(_SPOTIA_KEY, JSON.stringify(entries)); } catch {}
}

function _spotiaRenderHistory(entries) {
  if (!entries.length) return;
  const chat = document.getElementById("spotiaChat");
  if (!chat) return;

  // Ocultar welcome
  const welcome = chat.querySelector(".spotia-welcome");
  if (welcome) welcome.style.display = "none";

  // Agrupar por día para separadores
  let lastDay = null;
  entries.forEach(e => {
    const d = new Date(e.ts);
    const day = d.toLocaleDateString("es-CL", { weekday: "long", day: "numeric", month: "long" });
    if (day !== lastDay) {
      const sep = document.createElement("div");
      sep.className = "spotia-day-sep";
      sep.textContent = day;
      chat.appendChild(sep);
      lastDay = day;
    }
    _spotiaAddMsgDOM(e.role, e.content, /* persist= */ false);
  });

  // Separador "fin del historial"
  const endSep = document.createElement("div");
  endSep.className = "spotia-day-sep";
  endSep.textContent = "▸ conversación actual";
  chat.appendChild(endSep);
  chat.scrollTop = chat.scrollHeight;
}

function spotiaClearHistory() {
  try { localStorage.removeItem(_SPOTIA_KEY); } catch {}
  SPOTIA.history = [];
  const chat = document.getElementById("spotiaChat");
  if (!chat) return;
  // Borrar todo menos el welcome
  [...chat.children].forEach(el => {
    if (!el.classList.contains("spotia-welcome")) el.remove();
  });
  const welcome = chat.querySelector(".spotia-welcome");
  if (welcome) welcome.style.display = "";
}

function initSpotia() {
  // Cargar lista de clientes
  fetch("/api/spotia/clientes")
    .then(r => r.json())
    .then(clientes => {
      const sel = document.getElementById("spotiaClienteCtx");
      if (!sel) return;
      clientes.forEach(c => {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c;
        sel.appendChild(opt);
      });
    })
    .catch(() => {});

  // Renderizar historial persistido (últimas 48h)
  const saved = _spotiaReadStorage();
  _spotiaWriteStorage(saved); // guarda limpio (sin expirados)
  SPOTIA.history = [...saved];
  _spotiaRenderHistory(saved);
}

function spotiaKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    spotiaSubmit();
  }
}

function spotiaAsk(question) {
  const input = document.getElementById("spotiaInput");
  if (input) input.value = question;
  spotiaSubmit();
}

function spotiaMode(mode) {
  const cliente = (document.getElementById("spotiaClienteCtx") || {}).value || "";
  let label = "";
  if (mode === "executive") label = "📊 Generar Resumen Ejecutivo";
  else if (mode === "comercial") label = `🤝 Preparar reunión con cliente${cliente ? ": " + cliente : ""}`;
  else if (mode === "riesgos") label = "⚠️ Analizar riesgos de Supply Chain";

  _spotiaAddMsg("user", label);
  _spotiaSetLoading(true);

  fetch("/api/spotia", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ question: label, mode, cliente }),
  })
    .then(r => r.json())
    .then(d => {
      _spotiaSetLoading(false);
      _spotiaAddMsg("bot", d.answer || d.error || "Sin respuesta");
    })
    .catch(err => {
      _spotiaSetLoading(false);
      _spotiaAddMsg("bot", `<div class="spotia-error">⚠️ Error de conexión: ${err.message}</div>`);
    });
}

function spotiaSubmit() {
  if (SPOTIA.loading) return;
  const input   = document.getElementById("spotiaInput");
  const question = (input ? input.value : "").trim();
  if (!question) return;

  input.value = "";
  input.style.height = "auto";

  // Ocultar welcome si es el primer mensaje
  const welcome = document.querySelector(".spotia-welcome");
  if (welcome) welcome.style.display = "none";

  const cliente = (document.getElementById("spotiaClienteCtx") || {}).value || "";

  _spotiaAddMsg("user", question);
  _spotiaSetLoading(true);

  fetch("/api/spotia", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ question, mode: "chat", cliente }),
  })
    .then(r => r.json())
    .then(d => {
      _spotiaSetLoading(false);
      _spotiaAddMsg("bot", d.answer || d.error || "Sin respuesta");
    })
    .catch(err => {
      _spotiaSetLoading(false);
      _spotiaAddMsg("bot", `<div class="spotia-error">⚠️ Error de conexión: ${err.message}</div>`);
    });
}

function _spotiaAddMsgDOM(role, html, persist = true) {
  const chat = document.getElementById("spotiaChat");
  if (!chat) return;

  const isUser = role === "user";
  const avatar = isUser ? "T" : "✦";

  const div = document.createElement("div");
  div.className = `spotia-msg ${isUser ? "user" : "bot"}`;
  div.innerHTML = `
    <div class="spotia-avatar">${avatar}</div>
    <div class="spotia-bubble">${isUser ? esc(html) : html}</div>
  `;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;

  if (persist) {
    const entry = { role, content: html, ts: Date.now() };
    SPOTIA.history.push(entry);
    _spotiaWriteStorage(SPOTIA.history);
  }
}

function _spotiaAddMsg(role, html) {
  _spotiaAddMsgDOM(role, html, true);
}

let _spotiaTypingEl = null;
function _spotiaSetLoading(on) {
  SPOTIA.loading = on;
  const btn = document.getElementById("spotiaSendBtn");
  if (btn) btn.disabled = on;

  const chat = document.getElementById("spotiaChat");
  if (!chat) return;

  if (on) {
    const div = document.createElement("div");
    div.className = "spotia-msg bot";
    div.id = "spotiaTyping";
    div.innerHTML = `
      <div class="spotia-avatar">✦</div>
      <div class="spotia-bubble">
        <div class="spotia-typing"><span></span><span></span><span></span></div>
      </div>
    `;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    _spotiaTypingEl = div;
  } else {
    if (_spotiaTypingEl) { _spotiaTypingEl.remove(); _spotiaTypingEl = null; }
  }
}

// ═══════════════════════════════════════════════════════════════
// FILL RATE MES
// ═══════════════════════════════════════════════════════════════

const FRM = { data: null, selected: new Set() }; // selected = clientes seleccionados (vacío = todos)
const _FRM_LOSS = { chart: null };

async function loadFrMes() {
  if (FRM.data) { _frmApplyFilter(); return; }
  try {
    const res  = await fetch("/api/fr-mes");
    FRM.data   = await res.json();
    _frmBuildMultiSelect(FRM.data.clientes || []);
    _frmApplyFilter();
  } catch (e) {
    const tbody = document.getElementById("frMesOcBody");
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-muted">Error al cargar datos.</td></tr>`;
  }
}

// ── Multi-select helpers ───────────────────────────────────────
function _frmBuildMultiSelect(clientes) {
  const cont = document.getElementById("frmMsOptions");
  if (!cont) return;
  cont.innerHTML = clientes.map(c => `
    <label class="frm-ms-opt">
      <input type="checkbox" value="${esc(c)}" onchange="frmMsChange()">
      <span>${esc(c)}</span>
    </label>
  `).join("");
}

function frmMsToggle(e) {
  if (e) e.stopPropagation();
  const dd = document.getElementById("frmMsDropdown");
  if (!dd) return;
  const isOpen = !dd.classList.contains("d-none");
  dd.classList.toggle("d-none");
  if (!isOpen) {
    document.addEventListener("click", _frmMsOutside);
  } else {
    document.removeEventListener("click", _frmMsOutside);
  }
}
function _frmMsOutside(e) {
  const wrap = document.getElementById("frmMsWrap");
  if (wrap && !wrap.contains(e.target)) {
    const dd = document.getElementById("frmMsDropdown");
    if (dd) dd.classList.add("d-none");
    document.removeEventListener("click", _frmMsOutside);
  }
}

function frmMsToggleAll(cb) {
  document.querySelectorAll("#frmMsOptions input[type=checkbox]").forEach(el => { el.checked = cb.checked; });
  frmMsChange();
}

function frmMsChange() {
  const checked = [...document.querySelectorAll("#frmMsOptions input:checked")].map(el => el.value);
  const allCb   = document.getElementById("frmMsAll");
  const total   = document.querySelectorAll("#frmMsOptions input").length;
  if (allCb) allCb.checked = checked.length === total;
  FRM.selected = checked.length === total ? new Set() : new Set(checked);
  _frmUpdateChips(checked, total);
  _frmApplyFilter();
}

function _frmUpdateChips(checked, total) {
  const chips   = document.getElementById("frmMsChips");
  const clearBtn = document.getElementById("frmMsClearBtn");
  const label   = document.getElementById("frmMsLabel");
  const isAll   = checked.length === total || checked.length === 0;

  if (label) label.textContent = isAll ? "Todos los clientes" : `${checked.length} cliente${checked.length > 1 ? "s" : ""}`;
  if (clearBtn) clearBtn.style.display = isAll ? "none" : "";
  if (!chips) return;
  chips.innerHTML = isAll ? "" : checked.map(c =>
    `<span class="frm-chip">${esc(c)}<button onclick="frmMsRemove('${esc(c)}')" title="Quitar">×</button></span>`
  ).join("");
}

function frmMsRemove(cliente) {
  const cb = document.querySelector(`#frmMsOptions input[value="${cliente}"]`);
  if (cb) { cb.checked = false; frmMsChange(); }
}

function frmMsClear() {
  document.querySelectorAll("#frmMsOptions input").forEach(el => el.checked = true);
  const allCb = document.getElementById("frmMsAll");
  if (allCb) allCb.checked = true;
  FRM.selected = new Set();
  _frmUpdateChips([], 0);
  _frmApplyFilter();
}

// ── Filtrar y renderizar ───────────────────────────────────────
function _frmApplyFilter() {
  const data = FRM.data;
  if (!data) return;

  const allOcs = data.ocs || [];
  const ocs = FRM.selected.size === 0
    ? allOcs
    : allOcs.filter(o => FRM.selected.has(o.cliente));

  // Recalcular KPIs sobre el subconjunto filtrado
  const kpisBase = data.kpis || {};
  let kpis = { ...kpisBase };
  if (FRM.selected.size > 0) {
    const sol  = ocs.reduce((a, o) => a + o.skus.reduce((b, s) => b + s.sol,  0), 0);
    const asig = ocs.reduce((a, o) => a + o.skus.reduce((b, s) => b + s.asig, 0), 0);
    const fac  = ocs.reduce((a, o) => a + o.val_fac, 0);
    // Venta perdida: OCs de clientes clave dentro del filtro
    const CLAVE = ["sodimac","walmart","jumbo","easy","tottus","mercado libre","aramco","shell","bestias"];
    const ocsRetail = ocs.filter(o => CLAVE.some(kw => o.cliente.toLowerCase().includes(kw)));
    const perdida   = ocsRetail.reduce((a, o) => a + o.val_no_fac, 0);
    const facRetail = ocsRetail.reduce((a, o) => a + o.val_fac, 0);
    kpis = {
      ...kpisBase,
      fr_mtd:                      sol > 0 ? Math.round(asig / sol * 1000) / 10 : null,
      fr_mtd_color:                sol > 0 ? _frmColor(asig/sol*100) : "red",
      venta_facturada_mtd:         Math.round(fac),
      venta_facturada_retail_mtd:  Math.round(facRetail),
      venta_perdida_mtd:           Math.round(perdida),
      n_ocs_despachadas:           ocs.length,
    };
  }

  setEl("frMesLabel", kpis.mes_label ? `— ${kpis.mes_label}` : "");
  _frmRenderKpis(kpis);
  _frmRenderTable(ocs);
  _frmRenderLossTree(ocs);
}

function _frmColor(fr) {
  if (fr >= 95) return "green";
  if (fr >= 90) return "yellow";
  if (fr >= 80) return "orange";
  return "red";
}

function _frmRenderKpis(kpis) {
  const grid = document.getElementById("frMesKpiGrid");
  if (!grid) return;
  const frVal  = kpis.fr_mtd  != null ? `${kpis.fr_mtd}%`  : "—";
  const frAnt  = kpis.fr_ant  != null ? `${kpis.fr_ant}%`  : "—";
  const varNum = kpis.variacion;
  const varColor = varNum == null ? "neu" : (varNum >= 0 ? "green" : "red");
  const varValHtml = varNum != null
    ? `<span class="frm-var ${varNum >= 0 ? "frm-var-up" : "frm-var-dn"}" style="font-size:22px;font-weight:700;background:none;padding:0">
         ${varNum >= 0 ? "▲" : "▼"} ${Math.abs(varNum).toFixed(1)} pp
       </span>`
    : `<span style="font-size:22px;font-weight:700;color:#bbb">—</span>`;

  grid.innerHTML = `
    <div class="kpi-fr ${colorClass(kpis.fr_mtd_color || "red")}" style="grid-column:span 1">
      <div>
        <div class="fr-main-label">Fill Rate — ${kpis.mes_label || "Mes Actual"}</div>
        <div class="fr-main-value">${frVal}</div>
        <div class="fr-main-sub">OCs cerradas</div>
      </div>
      <span class="fr-main-badge">${_frLabel(kpis.fr_mtd)}</span>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Fill Rate — ${kpis.ant_label || "Mes Anterior"}</div>
        <div class="kpi-s-val">${frAnt}</div>
        <div class="kpi-s-sub">OCs cerradas mes anterior</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-${varColor}">
      <div>
        <div class="kpi-s-lbl">Variación vs mes anterior</div>
        <div class="kpi-s-val">${varValHtml}</div>
        <div class="kpi-s-sub">${kpis.mes_label || ""} vs ${kpis.ant_label || ""}</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Venta Facturada + Asignada MTD</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(kpis.venta_facturada_mtd)}</div>
        <div class="kpi-s-sub">valor facturado OCs cerradas</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Venta Facturada</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(kpis.venta_facturada_retail_mtd)}</div>
        <div class="kpi-s-sub">OCs cerradas · clientes Retail</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-red">
      <div>
        <div class="kpi-s-lbl">Venta Perdida MTD</div>
        <div class="kpi-s-val kpi-s-val--sm">${fmtMoney(kpis.venta_perdida_mtd)}</div>
        <div class="kpi-s-sub">Clientes Retail</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">OCs Despachadas</div>
        <div class="kpi-s-val">${kpis.n_ocs_despachadas ?? "—"}</div>
        <div class="kpi-s-sub">OCs cerradas en el mes</div>
      </div>
      <div class="kpi-s-dot"></div>
    </div>
  `;
}

function _frmRenderTable(ocs) {
  const tbody  = document.getElementById("frMesOcBody");
  const countEl = document.getElementById("frMesOcCount");
  if (countEl) countEl.textContent = ocs.length ? `${ocs.length} OCs` : "—";
  if (!tbody) return;

  if (!ocs.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center py-4 text-muted">Sin OCs cerradas${FRM.selected.size ? " para los clientes seleccionados" : " en el mes en curso"}.</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  ocs.forEach(oc => {
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => _frmOpenModal(oc));
    tr.innerHTML = `
      <td>${esc(oc.cliente)}</td>
      <td><strong>${esc(oc.oc)}</strong></td>
      <td style="text-align:center">${esc(oc.fecha_despacho)}</td>
      <td style="text-align:center"><span class="fr-chip ${oc.fr_color}">${oc.fr}%</span></td>
      <td style="text-align:right">${fmtMoney(oc.val_fac)}</td>
      <td style="text-align:right">${fmtMoney(oc.val_no_fac)}</td>
      <td style="text-align:center">
        <button class="frm-ver-btn" onclick="event.stopPropagation();_frmOpenModal(${JSON.stringify(oc).replace(/'/g,"&#39;")})">Ver SKU ▾</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

// ── MODAL SKU FILL RATE MES ────────────────────────────────────
function _frmOpenModal(oc) {
  const modal = new bootstrap.Modal(document.getElementById("ocModal"));
  const body  = document.getElementById("modalBody");

  setEl("modalClient", oc.cliente);
  setEl("modalOcInfo",  `OC ${oc.oc} · F. Despacho: ${oc.fecha_despacho}`);
  const frEl = document.getElementById("modalFr");
  if (frEl) {
    frEl.textContent = fmtPct(oc.fr);
    frEl.className   = `modal-fr-value ${oc.fr_color}`;
  }

  const sol  = oc.skus.reduce((a, s) => a + s.sol,  0);
  const asig = oc.skus.reduce((a, s) => a + s.asig, 0);
  const bo   = oc.skus.reduce((a, s) => a + s.bo,   0);
  const boVal = oc.val_no_fac || 0;
  const boValFmt = `$${fmtNum(Math.round(boVal))}`;

  const skuRows = oc.skus.map(s => {
    const motivoHtml = s.fr >= 100
      ? `<span class="motivo-ok">Completado</span>`
      : s.comentario ? `<span style="font-size:10px;color:#555">${esc(s.comentario)}</span>` : ``;
    const fillColor = s.fr >= 95 ? "#16a34a" : s.fr >= 90 ? "#ca8a04" : s.fr >= 80 ? "#ea580c" : "#dc2626";
    return `
      <tr>
        <td>
          <div style="font-size:10px;font-weight:600;color:#000">${esc(s.producto)}</div>
          <div style="font-size:9px;color:#aaa">${esc(s.categoria)}</div>
        </td>
        <td style="font-family:monospace;font-size:9px;color:#aaa">${esc(s.ean)}</td>
        <td>${fmtNum(s.sol)}</td>
        <td>${fmtNum(s.asig)}</td>
        <td class="${s.bo > 0 ? 'fw-800' : ''}" style="${s.bo > 0 ? 'color:#dc2626' : 'color:#ccc'}">${fmtNum(s.bo)}</td>
        <td>
          <span class="fr-chip ${s.fr_color}" style="font-size:10px;padding:3px 8px">${fmtPct(s.fr)}</span>
          <div class="pct-bar" style="margin-top:5px">
            <div class="pct-fill" style="width:${Math.min(s.fr,100)}%;background:${fillColor}"></div>
          </div>
        </td>
        <td>${motivoHtml}</td>
      </tr>`;
  }).join("");

  // Adaptar datos para _exportModalXlsx
  document.getElementById("ocModal").dataset.exportData = JSON.stringify({
    oc: oc.oc, cliente: oc.cliente, fecha_despacho: oc.fecha_despacho, estado: "CERRADA",
    skus: oc.skus.map(s => ({
      producto: s.producto, ean_spot: s.ean, marca: "", categoria: s.categoria,
      sol: s.sol, asig: s.asig, bo: s.bo, fr: s.fr, stock: "", motivo: s.comentario || "",
    })),
  });

  if (body) body.innerHTML = `
    <div class="modal-sec-label">Resumen de la OC</div>
    <div class="modal-kpis">
      <div class="mk"><div class="mk-lbl">UN Solicitadas</div><div class="mk-val">${fmtNum(sol)}</div></div>
      <div class="mk"><div class="mk-lbl">UN Asignadas</div><div class="mk-val ok">${fmtNum(asig)}</div></div>
      <div class="mk"><div class="mk-lbl">UN Pendientes</div><div class="mk-val ${bo > 0 ? 'crit' : 'ok'}">${fmtNum(bo)}</div></div>
      <div class="mk"><div class="mk-lbl">BO Valorizado</div><div class="mk-val ${boVal > 0 ? 'warn' : 'ok'}">${boValFmt}</div></div>
    </div>
    <div class="modal-sec-label" style="margin-top:16px">Detalle por SKU</div>
    <table class="spot-table w-100" style="font-size:12px">
      <thead><tr>
        <th>Producto</th><th>EAN</th>
        <th style="text-align:center">Sol.</th><th style="text-align:center">Asig.</th>
        <th style="text-align:center">BO</th><th style="text-align:center">FR</th>
        <th>Comentario</th>
      </tr></thead>
      <tbody>${skuRows}</tbody>
    </table>`;

  modal.show();
}

// ── EXPORTACIÓN EXCEL ──────────────────────────────────────────
function _exportSkuXlsx(oc) {
  const rows = (oc.skus || []).map(s => ({
    "Cliente":          oc.cliente,
    "N° OC":            oc.oc,
    "F. Despacho":      oc.fecha_despacho,
    "Producto":         s.producto,
    "Categoría":        s.categoria || "",
    "UN Solicitadas":   s.sol,
    "UN Asignadas":     s.asig,
    "Back Order (UN)":  s.bo,
    "Fill Rate (%)":    s.fr,
    "BO Valorizado":    s.bo_val || 0,
    "Comentario / BO":  s.comentario || "",
  }));
  _downloadXlsx(rows, `OC_${oc.oc}_SKU`);
}

function _exportModalXlsx() {
  const modal = document.getElementById("ocModal");
  if (!modal?.dataset.exportData) return;
  const d = JSON.parse(modal.dataset.exportData);
  const rows = (d.skus || []).map(s => ({
    "Cliente":          d.cliente,
    "N° OC":            d.oc,
    "F. Despacho":      d.fecha_despacho,
    "Estado":           d.estado || "",
    "Producto":         s.producto,
    "EAN SPOT":         s.ean_spot || "",
    "Marca":            s.marca || "",
    "Categoría":        s.categoria || "",
    "UN Solicitadas":   s.sol,
    "UN Asignadas":     s.asig,
    "Back Order (UN)":  s.bo,
    "Fill Rate (%)":    s.fr,
    "Stock":            s.stock ?? "",
    "Comentario / BO":  s.motivo || "",
  }));
  _downloadXlsx(rows, `OC_${d.oc}_SKU`);
}

function _downloadXlsx(rows, filename) {
  const ws = XLSX.utils.json_to_sheet(rows);
  // Ancho de columnas automático
  const cols = Object.keys(rows[0] || {}).map(k => ({ wch: Math.max(k.length, 14) }));
  ws["!cols"] = cols;
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "Detalle SKU");
  XLSX.writeFile(wb, `${filename}.xlsx`);
}


function _frmRenderLossTree(ocs) {
  const ctx = document.getElementById("frMesLossTreeChart")?.getContext("2d");
  const tbl = document.getElementById("frMesLossTreeTable");
  const sub = document.getElementById("frMesLossTreeSub");
  if (!ctx) return;

  const COLORS = ["#dc2626","#2563eb","#16a34a","#7c3aed","#ea580c","#0891b2","#db2777","#ca8a04","#65a30d","#b45309"];

  // Recopilar todos los SKUs con BO de las OCs visibles
  const boSkus = [];
  ocs.forEach(oc => {
    (oc.skus || []).forEach(s => {
      if (s.bo > 0) boSkus.push({ ...s, oc: oc.oc, cliente: oc.cliente });
    });
  });

  if (sub) sub.textContent = `${ocs.length} OC${ocs.length !== 1 ? "s" : ""} cerrada${ocs.length !== 1 ? "s" : ""}`;

  // Agrupar por categoria_arbol
  const groups = {};
  boSkus.forEach(s => {
    const k = s.categoria_arbol?.trim() || "Sin clasificar";
    if (!groups[k]) groups[k] = { bo_un: 0, bo_val: 0, items: [] };
    groups[k].bo_un  += s.bo;
    groups[k].bo_val += s.bo_val || 0;
    groups[k].items.push(s);
  });

  const entries  = Object.entries(groups).sort((a, b) => b[1].bo_val - a[1].bo_val);
  const totalVal = entries.reduce((s, [, v]) => s + v.bo_val, 0);

  if (!entries.length) {
    if (_FRM_LOSS.chart) { _FRM_LOSS.chart.destroy(); _FRM_LOSS.chart = null; }
    if (tbl) tbl.innerHTML = `<div style="padding:24px;color:#aaa;font-size:12px;text-align:center">Sin back order en OCs cerradas del mes</div>`;
    return;
  }

  const labels   = entries.map(([k]) => k);
  const values   = entries.map(([, v]) => v.bo_val);
  const units    = entries.map(([, v]) => v.bo_un);
  const skuCnt   = entries.map(([, v]) => v.items.length);
  const bgColors = entries.map((_, i) => COLORS[i % COLORS.length]);

  if (_FRM_LOSS.chart) _FRM_LOSS.chart.destroy();
  _FRM_LOSS.chart = new Chart(ctx, {
    type: "doughnut",
    data: { labels, datasets: [{ data: values, backgroundColor: bgColors.map(c => c + "dd"), borderColor: bgColors, borderWidth: 2, hoverOffset: 8 }] },
    options: {
      responsive: true, cutout: "52%",
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          label: c => { const pct = totalVal > 0 ? ((c.raw/totalVal)*100).toFixed(1) : 0; return ` ${fmtMoney(c.raw)}  (${pct}%)`; },
          afterLabel: c => ` ${fmtNum(units[c.dataIndex])} UN · ${skuCnt[c.dataIndex]} SKU`,
        }}
      }
    }
  });

  if (!tbl) return;
  tbl.innerHTML = `
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="border-bottom:2px solid #f0f0f0">
          <th style="padding:6px 10px;text-align:left;color:#888;font-weight:600"></th>
          <th style="padding:6px 10px;text-align:left;color:#888;font-weight:600">Categoría</th>
          <th style="padding:6px 10px;text-align:right;color:#888;font-weight:600">%</th>
          <th style="padding:6px 10px;text-align:right;color:#888;font-weight:600">BO Valorizado</th>
          <th style="padding:6px 10px;text-align:right;color:#888;font-weight:600">UN</th>
          <th style="padding:6px 10px"></th>
        </tr>
      </thead>
      <tbody>
        ${entries.map(([k, v], i) => {
          const pct = totalVal > 0 ? ((v.bo_val / totalVal) * 100).toFixed(1) : "0.0";
          const uid = `frm-lt-${i}`;
          const skuRows = v.items.map(s => `
            <tr style="background:#fafafa">
              <td colspan="2" style="padding:5px 12px 5px 36px;font-size:10px;color:#444">${esc(s.producto)}</td>
              <td style="padding:5px 10px;text-align:right;font-size:10px;color:#666">${s.fr}%</td>
              <td style="padding:5px 10px;text-align:right;font-size:10px;font-weight:600;font-variant-numeric:tabular-nums">${fmtMoney(s.bo_val||0)}</td>
              <td style="padding:5px 10px;text-align:right;font-size:10px;color:#666">${fmtNum(s.bo)}</td>
              <td></td>
            </tr>`).join("");
          return `
            <tr style="border-bottom:1px solid #f0f0f0" id="${uid}-row">
              <td style="padding:8px 10px"><div style="width:12px;height:12px;border-radius:3px;background:${bgColors[i]}"></div></td>
              <td style="padding:8px 10px;font-weight:600;color:#1a1a1a">${esc(k)}</td>
              <td style="padding:8px 10px;text-align:right">
                <div style="display:flex;align-items:center;justify-content:flex-end;gap:6px">
                  <div style="width:60px;height:6px;background:#f0f0f0;border-radius:3px;overflow:hidden">
                    <div style="width:${pct}%;height:100%;background:${bgColors[i]};border-radius:3px"></div>
                  </div>
                  <span style="font-weight:700;color:#333;min-width:36px;text-align:right">${pct}%</span>
                </div>
              </td>
              <td style="padding:8px 10px;text-align:right;font-weight:700;font-variant-numeric:tabular-nums">${fmtMoney(v.bo_val)}</td>
              <td style="padding:8px 10px;text-align:right;color:#555">${fmtNum(v.bo_un)}</td>
              <td style="padding:8px 10px;text-align:right">
                <button onclick="toggleLtSkus('${uid}',this)"
                  style="background:none;border:1px solid #e4e4e4;border-radius:4px;padding:3px 8px;font-size:9px;font-family:inherit;font-weight:700;color:#555;cursor:pointer;letter-spacing:.3px;white-space:nowrap">
                  VER SKU ▾
                </button>
              </td>
            </tr>
            <tr id="${uid}" style="display:none">${skuRows ? `<td colspan="6" style="padding:0">${'<table style="width:100%;border-collapse:collapse">' + skuRows + '</table>'}</td>` : ""}</tr>
          `;
        }).join("")}
      </tbody>
    </table>`;
}

function _frLabel(fr) {
  if (fr === null || fr === undefined) return "SIN DATOS";
  if (fr >= 95) return "ÓPTIMO";
  if (fr >= 90) return "ATENCIÓN";
  if (fr >= 80) return "RIESGO";
  return "CRÍTICO";
}

// ═══════════════════════════════════════════════════════════════
// TRACKING PT
// ═══════════════════════════════════════════════════════════════
const TPT = { data: null, filtered: [], sortCol: "abc", sortAsc: true };

async function loadTrackingPT() {
  if (TPT.data) { filterTrackingPT(); return; }
  try {
    const res  = await fetch("/api/tracking-pt");
    const json = await res.json();
    TPT.data   = json;

    setEl("tptFileName",    json.file_name     || "—");
    setEl("tptFileUpdated", json.file_modified || "—");

    const catSel   = document.getElementById("tptCategoria");
    const aromaSel = document.getElementById("tptAroma");
    const abcSel   = document.getElementById("tptAbc");
    (json.categorias || []).forEach(c => catSel.insertAdjacentHTML("beforeend",  `<option value="${esc(c)}">${esc(c)}</option>`));
    (json.aromas     || []).forEach(a => aromaSel.insertAdjacentHTML("beforeend",`<option value="${esc(a)}">${esc(a)}</option>`));
    (json.abcs       || []).forEach(b => abcSel.insertAdjacentHTML("beforeend",  `<option value="${esc(b)}">${esc(b)}</option>`));

    // Headers dinámicos de los 3 meses cerrados
    const labels = json.last3_labels || [];
    ["tptMes1Hdr","tptMes2Hdr","tptMes3Hdr"].forEach((id, i) => {
      const el = document.getElementById(id);
      if (el && labels[i]) el.textContent = labels[i];
    });

    filterTrackingPT();
  } catch(e) {
    document.getElementById("tptBody").innerHTML =
      `<tr><td colspan="11" class="text-center py-4" style="color:#dc2626">Error cargando datos: ${e.message}</td></tr>`;
  }
}

function filterTrackingPT() {
  if (!TPT.data) return;
  const q    = (document.getElementById("tptSearch")?.value    || "").toLowerCase().trim();
  const cat  = (document.getElementById("tptCategoria")?.value || "").toLowerCase();
  const arom = (document.getElementById("tptAroma")?.value     || "").toLowerCase();
  const abc  = (document.getElementById("tptAbc")?.value       || "").toLowerCase();

  TPT.filtered = TPT.data.rows.filter(r => {
    if (q    && !r.producto.toLowerCase().includes(q) && !r.ean.includes(q)) return false;
    if (cat  && r.categoria.toLowerCase() !== cat)  return false;
    if (arom && r.aroma.toLowerCase()     !== arom) return false;
    if (abc  && r.abc.toLowerCase()       !== abc)  return false;
    return true;
  });

  const hasFilter = q || cat || arom || abc;
  const btn = document.getElementById("tptBtnClear");
  if (btn) btn.style.display = hasFilter ? "" : "none";

  sortAndRenderTPT();
}

function sortTPT(col) {
  if (TPT.sortCol === col) TPT.sortAsc = !TPT.sortAsc;
  else { TPT.sortCol = col; TPT.sortAsc = col === "abc" || col === "producto"; }
  sortAndRenderTPT();
}

function sortAndRenderTPT() {
  const col = TPT.sortCol;
  const asc = TPT.sortAsc;
  TPT.filtered.sort((a, b) => {
    const va = a[col] ?? "", vb = b[col] ?? "";
    if (typeof va === "number" && typeof vb === "number") return asc ? va - vb : vb - va;
    return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  });
  renderTPT();
}

function renderTPT() {
  const rows  = TPT.filtered;
  const tbody = document.getElementById("tptBody");

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="12" class="text-center py-4 text-muted">Sin resultados</td></tr>`;
    renderTPTKpis([]);
    document.getElementById("tptCount").textContent = "0";
    return;
  }

  tbody.innerHTML = rows.map(r => {
    const abcCls  = r.abc === "A" ? "abc-A" : r.abc === "B" ? "abc-B" : r.abc === "C" ? "abc-C" : "abc-other";
    const fa      = _tptPctChip(r.fa);
    const dohCls  = r.doh === null ? "" : r.doh < 7 ? "doh-low" : r.doh > 60 ? "doh-high" : "doh-ok";
    const dohTxt  = r.doh !== null ? r.doh.toFixed(1) : "—";
    const meses   = (r.meses_ant || []).map(v =>
      `<td style="text-align:center;color:#999">${v !== null ? v.toLocaleString("es-CL") : "—"}</td>`
    ).join("");
    const fcstTxt = r.fcst_mes !== null && r.fcst_mes !== undefined
      ? r.fcst_mes.toLocaleString("es-CL")
      : "—";
    const dohInt  = r.doh !== null ? Math.round(r.doh) : null;
    const dohDisp = dohInt !== null ? dohInt.toLocaleString("es-CL") : "—";
    return `<tr>
      <td style="font-size:11px;color:#888;font-family:monospace">${esc(r.ean)}</td>
      <td style="font-weight:500;max-width:220px">${esc(r.producto)}</td>
      <td>${esc(r.marca)}</td>
      <td style="text-align:center"><span class="abc-badge ${abcCls}">${esc(r.abc)}</span></td>
      ${meses}
      <td style="text-align:center;color:#111;font-weight:700">${fcstTxt}</td>
      <td style="text-align:center;font-weight:600">${r.venta_mtd !== null ? r.venta_mtd.toLocaleString("es-CL") : "—"}</td>
      <td style="text-align:center">${fa}</td>
      <td style="text-align:center;font-weight:700;background:#fef9c3;color:#854d0e">${r.stock !== null ? r.stock.toLocaleString("es-CL") : "—"}</td>
      <td style="text-align:center"><span class="${dohCls}">${dohDisp}</span></td>
    </tr>`;
  }).join("");

  document.getElementById("tptCount").textContent =
    rows.length + (TPT.data.rows.length !== rows.length ? ` / ${TPT.data.rows.length}` : "");
  document.getElementById("tptFooter").textContent =
    `${rows.length} producto${rows.length !== 1 ? "s" : ""}${TPT.data.rows.length !== rows.length ? ` de ${TPT.data.rows.length} totales` : ""}`;

  renderTPTKpis(rows);
}

function _tptPctChip(val) {
  if (val === null || val === undefined) return `<span style="color:#bbb">—</span>`;
  const cls = val >= 90 ? "pct-green" : val >= 80 ? "pct-yellow" : val >= 70 ? "pct-orange" : "pct-red";
  return `<span class="pct-chip ${cls}">${val.toFixed(1)}%</span>`;
}

function renderTPTKpis(rows) {
  const grid = document.getElementById("tptKpiGrid");
  if (!grid) return;

  if (!rows.length) {
    grid.innerHTML = "";
    return;
  }

  const ventaTotal = rows.reduce((s, r) => s + (r.venta_mtd || 0), 0);

  // Cumplimiento mes a nivel total de códigos: Σ venta MTD / Σ forecast mes
  const withFcst   = rows.filter(r => r.fcst_mes !== null && r.fcst_mes > 0);
  const ventaFcst  = withFcst.reduce((s, r) => s + (r.venta_mtd || 0), 0);
  const fcstSum    = withFcst.reduce((s, r) => s + r.fcst_mes, 0);
  const cumplProm  = fcstSum > 0 ? (ventaFcst / fcstSum) * 100 : null;

  const stockTotal = rows.reduce((s, r) => s + (r.stock || 0), 0);

  // Sin stock: solo productos con stock 0 y forecast del mes en curso > 0
  const sinStock   = rows.filter(r => r.stock === 0 && r.fcst_mes !== null && r.fcst_mes > 0).length;

  const dohBajo    = rows.filter(r => r.doh !== null && r.doh < 7).length;

  const cumplColor = cumplProm === null ? "s-neu"
    : cumplProm >= 90 ? "s-green" : cumplProm >= 80 ? "s-yellow"
    : cumplProm >= 70 ? "s-orange" : "s-red";

  const faAB      = TPT.data?.fa_ab_mtd ?? null;
  const fcstLabel = TPT.data?.fcst_label ?? "";
  const faABColor = faAB === null ? "s-neu"
    : faAB >= 90 ? "s-green" : faAB >= 80 ? "s-yellow"
    : faAB >= 70 ? "s-orange" : "s-red";

  grid.innerHTML = `
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Venta MTD</div>
        <div class="kpi-s-val kpi-s-val--sm">${ventaTotal.toLocaleString("es-CL")}</div>
        <div class="kpi-s-sub">unidades · mes en curso</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s ${cumplColor}">
      <div>
        <div class="kpi-s-lbl">Cumplimiento Prom.</div>
        <div class="kpi-s-val">${cumplProm !== null ? cumplProm.toFixed(1)+"%" : "—"}</div>
        <div class="kpi-s-sub">vs forecast S&OP</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s ${faABColor}">
      <div>
        <div class="kpi-s-lbl">FA A+B MTD</div>
        <div class="kpi-s-val">${faAB !== null ? faAB.toFixed(1)+"%" : "—"}</div>
        <div class="kpi-s-sub">portafolio A&amp;B · ${fcstLabel}</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s s-neu">
      <div>
        <div class="kpi-s-lbl">Stock Total</div>
        <div class="kpi-s-val kpi-s-val--sm">${stockTotal.toLocaleString("es-CL")}</div>
        <div class="kpi-s-sub">unidades en bodega</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s ${sinStock > 0 ? "s-red" : "s-green"}">
      <div>
        <div class="kpi-s-lbl">Sin Stock</div>
        <div class="kpi-s-val">${sinStock}</div>
        <div class="kpi-s-sub">productos en cero</div>
      </div><div class="kpi-s-dot"></div>
    </div>
    <div class="kpi-s ${dohBajo > 0 ? "s-red" : "s-green"}">
      <div>
        <div class="kpi-s-lbl">DOH &lt; 7 días</div>
        <div class="kpi-s-val">${dohBajo}</div>
        <div class="kpi-s-sub">productos críticos</div>
      </div><div class="kpi-s-dot"></div>
    </div>`;
}

function resetTrackingPT() {
  document.getElementById("tptSearch").value    = "";
  document.getElementById("tptCategoria").value = "";
  document.getElementById("tptAroma").value     = "";
  document.getElementById("tptAbc").value       = "";
  filterTrackingPT();
}
