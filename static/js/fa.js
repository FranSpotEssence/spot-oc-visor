/* ================================================================
   SPOT ESSENCE — Forecast Accuracy Module
   fa.js — frontend completo: KPIs, Chart, Tablas, Heatmap, Ranking
================================================================ */

(function () {
  'use strict';

  /* ── Estado local ─────────────────────────────────────────────── */
  const FA = {
    data:          null,   // payload completo del API
    chartInstance: null,   // Chart.js instance
    skuRows:       [],     // filas para la tabla SKU (cacheadas)
    subtab:        'sku',  // 'sku' | 'cliente'
    groupMode:     'sku',  // 'sku' | 'cliente' — Nivel Cliente: agrupar por SKU o por Cliente
    expanded:      new Set(), // claves de grupos expandidos
  };

  /* ── Colores semáforo → CSS ───────────────────────────────────── */
  const FA_COLORS = {
    green:  { bg: '#dcfce7', text: '#166534', border: '#16a34a' },
    yellow: { bg: '#fef9c3', text: '#854d0e', border: '#ca8a04' },
    orange: { bg: '#ffedd5', text: '#9a3412', border: '#ea580c' },
    red:    { bg: '#fee2e2', text: '#991b1b', border: '#dc2626' },
  };

  function faColorByVal(fa) {
    if (fa === null || fa === undefined) return FA_COLORS.red;
    if (fa >= 80) return FA_COLORS.green;
    if (fa >= 60) return FA_COLORS.yellow;
    if (fa >= 40) return FA_COLORS.orange;
    return FA_COLORS.red;
  }

  function faSClass(fa) {
    if (fa === null || fa === undefined) return 'neu';
    if (fa >= 80) return 'green';
    if (fa >= 60) return 'yellow';
    if (fa >= 40) return 'orange';
    return 'red';
  }

  function faChipHtml(fa, cls) {
    if (fa === null || fa === undefined) return '<span class="pct-chip pct-red">—</span>';
    const c = cls || (fa >= 80 ? 'pct-green' : fa >= 60 ? 'pct-yellow' : fa >= 40 ? 'pct-orange' : 'pct-red');
    return `<span class="pct-chip ${c}">${fa.toFixed(1)}%</span>`;
  }

  function fmtNum(n) {
    if (n === null || n === undefined) return '—';
    return Number(n).toLocaleString('es-CL', { maximumFractionDigits: 0 });
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
  }

  /* ── Carga de datos ───────────────────────────────────────────── */
  async function faLoad(force) {
    try {
      _faSetLoading(true);
      let resp;
      if (force) {
        resp = await fetch('/api/fa/refresh', { method: 'POST' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const refreshResult = await resp.json();
        if (!refreshResult.ok) {
          _faShowError(refreshResult.error || 'Error al actualizar');
          return;
        }
        resp = await fetch('/api/fa/data');
      } else {
        resp = await fetch('/api/fa/data');
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      FA.data = await resp.json();
      if (FA.data.error) {
        _faShowError(FA.data.error);
        return;
      }
      _faHideError();
      faRender();
    } catch (e) {
      _faShowError('No se pudo conectar al servidor: ' + e.message);
    } finally {
      _faSetLoading(false);
    }
  }

  function _faSetLoading(on) {
    const btn = document.getElementById('btnFaRefresh');
    if (btn) btn.disabled = on;
    if (btn) btn.textContent = on ? '↻ Actualizando...' : '↻ Actualizar información';
  }

  function _faShowError(msg) {
    const el = document.getElementById('faError');
    if (!el) return;
    el.textContent = '⚠️ ' + msg;
    el.classList.remove('d-none');
  }

  function _faHideError() {
    const el = document.getElementById('faError');
    if (el) el.classList.add('d-none');
  }

  /* ── Render principal ─────────────────────────────────────────── */
  function faRender() {
    if (!FA.data) return;
    const d = FA.data;
    _renderSubtitle(d);
    _renderKpis(d.kpis || {});
    _renderTrend(d.trend || []);
    _renderRanking(d.ranking || {});
    _renderHeatmap(d.heatmap || {});
    _renderSkuTable(d.sku_table || [], d.meses || []);
    faRenderGroupTable();
  }

  /* ── Subtítulo ────────────────────────────────────────────────── */
  function _renderSubtitle(d) {
    const el = document.getElementById('faSubtitle');
    if (!el) return;
    const archivos = [d.archivo_forecast, d.archivo_venta].filter(Boolean).join(' + ');
    el.textContent = archivos ? `Archivos: ${archivos}` : 'Datos cargados';
    const upEl = document.getElementById('faUpdatedAt');
    if (upEl) upEl.textContent = d.updated_at ? `Actualizado: ${d.updated_at}` : '';
  }

  /* ── Sub-pestañas Nivel SKU / Nivel Cliente ─────────────────────── */
  function faShowSubtab(tab) {
    FA.subtab = tab;
    const panelSku = document.getElementById('faPanelSku');
    const panelCli = document.getElementById('faPanelCliente');
    if (panelSku) panelSku.classList.toggle('d-none', tab !== 'sku');
    if (panelCli) panelCli.classList.toggle('d-none', tab !== 'cliente');

    document.getElementById('faSubtabBtnSku')?.classList.toggle('active', tab === 'sku');
    document.getElementById('faSubtabBtnCliente')?.classList.toggle('active', tab === 'cliente');

    // Chart.js necesita recalcular tamaño si estaba oculto al renderizar
    if (tab === 'sku' && FA.chartInstance) FA.chartInstance.resize();
  }

  /* ── KPIs ─────────────────────────────────────────────────────── */
  function _renderKpis(kpis) {
    const fa      = kpis.fa_ultimo_mes;
    const faTotal = kpis.fa_total;
    const variac  = kpis.variacion;
    const tend    = kpis.tendencia;

    // KPI principal (kpi-fr — mismo estilo que Fill Rate)
    const mEl = document.getElementById('faKpiMain');
    if (mEl) mEl.className = 'kpi-fr c-' + faSClass(fa);

    const vEl = document.getElementById('faKpiValue');
    if (vEl) vEl.textContent = fa !== null && fa !== undefined ? fa.toFixed(1) + '%' : '—';

    const lblEl = document.getElementById('faKpiMesLabel');
    if (lblEl) lblEl.textContent = kpis.mes_label || '';

    const sEl = document.getElementById('faKpiSub');
    if (sEl) {
      if (kpis.fa_mes_ant !== null && kpis.fa_mes_ant !== undefined) {
        sEl.textContent = `Mes anterior (${kpis.mes_ant_label || ''}): ${kpis.fa_mes_ant.toFixed(1)}%`;
      } else {
        sEl.textContent = '';
      }
    }

    // FA Total
    const totCard = document.getElementById('faKpiTotal')?.closest('.kpi-s');
    if (totCard) totCard.className = 'kpi-s s-' + faSClass(faTotal);
    const totEl  = document.getElementById('faKpiTotal');
    const totSub = document.getElementById('faKpiTotalSub');
    if (totEl) totEl.textContent = faTotal !== null && faTotal !== undefined ? faTotal.toFixed(1) + '%' : '—';
    if (totSub) totSub.textContent = `${kpis.n_meses || 0} meses`;

    // Variación
    const varCard = document.getElementById('faKpiVarCard');
    if (varCard) varCard.className = 'kpi-s s-' + (variac > 0 ? 'green' : variac < 0 ? 'red' : 'neu');
    const varEl  = document.getElementById('faKpiVar');
    const varSub = document.getElementById('faKpiVarSub');
    if (varEl) {
      if (variac !== null && variac !== undefined) {
        const sign = variac > 0 ? '+' : '';
        varEl.textContent = sign + variac.toFixed(1) + '%';
      } else {
        varEl.textContent = '—';
      }
    }
    if (varSub && tend) {
      varSub.textContent = tend === 'up' ? '▲ Mejorando' : tend === 'down' ? '▼ Empeorando' : '→ Sin cambio';
    }

    // Meses
    const mesesEl  = document.getElementById('faKpiMeses');
    const mesesSub = document.getElementById('faKpiMesesSub');
    if (mesesEl) mesesEl.textContent = kpis.n_meses || '—';
    if (mesesSub && FA.data && FA.data.meses && FA.data.meses.length) {
      const first = FA.data.meses[0].label;
      const last  = FA.data.meses[FA.data.meses.length - 1].label;
      mesesSub.textContent = first === last ? first : `${first} – ${last}`;
    }
  }

  /* ── Evolución mensual (Chart.js) ─────────────────────────────── */
  function _renderTrend(trend) {
    const canvas = document.getElementById('faChartTrend');
    if (!canvas) return;

    if (FA.chartInstance) {
      FA.chartInstance.destroy();
      FA.chartInstance = null;
    }

    if (!trend || !trend.length) {
      canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
      return;
    }

    const labels  = trend.map(r => r.label);
    const values  = trend.map(r => r.fa);
    const bgColors = values.map(v => faColorByVal(v).bg);
    const bdColors = values.map(v => faColorByVal(v).border);

    FA.chartInstance = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            type:            'line',
            label:           'FA (%)',
            data:            values,
            borderColor:     '#1a1a1a',
            backgroundColor: 'transparent',
            pointBackgroundColor: bdColors,
            pointRadius:     5,
            pointHoverRadius:7,
            borderWidth:     2,
            tension:         0.35,
            yAxisID:         'y',
            order:           1,
          },
          {
            type:            'bar',
            label:           'FA (%)',
            data:            values,
            backgroundColor: bgColors,
            borderColor:     bdColors,
            borderWidth:     1.5,
            borderRadius:    4,
            yAxisID:         'y',
            order:           2,
          }
        ]
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        interaction:         { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ` FA: ${ctx.parsed.y !== null ? ctx.parsed.y.toFixed(1) : '—'}%`,
            }
          }
        },
        scales: {
          y: {
            min: 0,
            max: 100,
            grid:  { color: '#f0f0f0' },
            ticks: { callback: v => v + '%', font: { size: 10 } },
          },
          x: {
            grid:  { display: false },
            ticks: { font: { size: 10 } },
          }
        }
      }
    });
  }

  /* ── Ranking ──────────────────────────────────────────────────── */
  function _renderRanking(ranking) {
    _fillRankList('faRankMejores', ranking.mejores || []);
    _fillRankList('faRankPeores',  ranking.peores  || []);
  }

  function _fillRankList(id, items) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!items.length) { el.innerHTML = '<div class="fa-rank-empty">Sin datos</div>'; return; }
    el.innerHTML = items.map((r, i) => {
      const col = faColorByVal(r.fa);
      const pct = r.fa !== null ? r.fa : 0;
      return `
        <div class="fa-rank-item">
          <span class="fa-rank-pos">${i + 1}</span>
          <div class="fa-rank-info">
            <div class="fa-rank-sku">${esc(r.sku)}</div>
            <div class="fa-rank-desc">${esc(r.descripcion || r.clientes || '')}</div>
            <div class="fa-rank-bar-wrap">
              <div class="fa-rank-bar" style="width:${pct}%;background:${col.border}"></div>
            </div>
          </div>
          <span class="fa-rank-val" style="color:${col.text}">${r.fa !== null ? r.fa.toFixed(1) + '%' : '—'}</span>
        </div>`;
    }).join('');
  }

  /* ── Heatmap ──────────────────────────────────────────────────── */
  function _renderHeatmap(heatmap) {
    const thead = document.getElementById('faHeatmapHead');
    const tbody = document.getElementById('faHeatmapBody');
    if (!thead || !tbody) return;

    const meses  = heatmap.meses  || [];
    const matrix = heatmap.matrix || [];

    if (!meses.length || !matrix.length) {
      thead.innerHTML = '';
      tbody.innerHTML = '<tr><td class="text-muted p-3">Sin datos para mostrar</td></tr>';
      return;
    }

    thead.innerHTML = '<tr>' +
      '<th class="fa-hm-cliente-col">Cliente</th>' +
      meses.map(m => `<th class="fa-hm-mes-col">${esc(m)}</th>`).join('') +
      '</tr>';

    tbody.innerHTML = matrix.map(row => {
      const cells = row.values.map((v, i) => {
        const bg   = row.colors[i];
        const text = v !== null ? v.toFixed(1) + '%' : '—';
        const txtColor = v !== null ? faColorByVal(v).text : '#aaa';
        return `<td class="fa-hm-cell" style="background:${bg};color:${txtColor}">${text}</td>`;
      }).join('');
      return `<tr><td class="fa-hm-cliente">${esc(row.cliente)}</td>${cells}</tr>`;
    }).join('');
  }

  /* ── Tabla FA por SKU (Nivel SKU) ─────────────────────────────── */
  function _renderSkuTable(rows, meses) {
    FA.skuRows = rows;
    faFilterSkuTable();

    const countEl = document.getElementById('faSkuCount');
    if (countEl) countEl.textContent = rows.length + ' SKUs';
  }

  function faFilterSkuTable() {
    const q    = (document.getElementById('faSkuSearch')?.value || '').toLowerCase();
    const rows = FA.skuRows.filter(r =>
      !q || r.sku.toLowerCase().includes(q) || (r.descripcion || '').toLowerCase().includes(q)
    );

    const tbody = document.getElementById('faSkuBody');
    if (!tbody) return;

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-muted">Sin resultados</td></tr>';
      return;
    }

    // sparkline: mini barras de tendencia
    tbody.innerHTML = rows.map(r => {
      const trend = (r.trend || []).map(v => {
        if (v === null) return '<span class="fa-spark-dot" style="background:#e0e0e0"></span>';
        const col = faColorByVal(v);
        return `<span class="fa-spark-dot" style="background:${col.border}" title="${v.toFixed(1)}%"></span>`;
      }).join('');

      return `<tr>
        <td><code style="font-size:11px">${esc(r.sku)}</code></td>
        <td>${esc(r.descripcion || '')}</td>
        <td class="text-center">${r.n_clientes ?? '—'}</td>
        <td class="text-end">${fmtNum(r.forecast)}</td>
        <td class="text-end">${fmtNum(r.venta)}</td>
        <td class="text-center">${faChipHtml(r.fa, r.fa_color ? r.fa_color.replace('c-', 'pct-') : null)}</td>
        <td class="text-center"><div class="fa-spark-row">${trend}</div></td>
      </tr>`;
    }).join('');
  }

  /* ── Nivel Cliente: tabla agrupable y expandible ────────────────── */
  function faSetGroupMode(mode) {
    FA.groupMode = mode;
    FA.expanded.clear();
    document.getElementById('faGroupBtnSku')?.classList.toggle('active', mode === 'sku');
    document.getElementById('faGroupBtnCliente')?.classList.toggle('active', mode === 'cliente');
    faRenderGroupTable();
  }

  function faToggleGroup(key) {
    if (FA.expanded.has(key)) FA.expanded.delete(key);
    else FA.expanded.add(key);
    faRenderGroupTable();
  }

  function faRenderGroupTable() {
    if (!FA.data) return;
    const mode = FA.groupMode;
    const q = (document.getElementById('faGroupSearch')?.value || '').toLowerCase();

    const head = document.getElementById('faGroupHead');
    const body = document.getElementById('faGroupBody');
    const countEl = document.getElementById('faGroupCount');
    if (!head || !body) return;

    const detail = FA.data.cliente_sku_detail || [];

    if (mode === 'sku') {
      head.innerHTML = `
        <th style="width:24px"></th>
        <th>SKU</th>
        <th>Descripción</th>
        <th class="text-center">N° Clientes</th>
        <th class="text-end">Forecast Total</th>
        <th class="text-end">Venta Total</th>
        <th class="text-center">FA</th>`;

      let parents = (FA.data.sku_table || []).slice();
      if (q) {
        parents = parents.filter(p =>
          p.sku.toLowerCase().includes(q) || (p.descripcion || '').toLowerCase().includes(q) ||
          detail.some(d => d.sku === p.sku && d.cliente.toLowerCase().includes(q))
        );
      }
      if (countEl) countEl.textContent = parents.length + ' SKUs';

      if (!parents.length) {
        body.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-muted">Sin resultados</td></tr>';
        return;
      }

      body.innerHTML = parents.map(p => {
        const key = 'sku:' + p.sku;
        const open = FA.expanded.has(key);
        const children = detail.filter(d => d.sku === p.sku)
          .sort((a, b) => (a.fa ?? 0) - (b.fa ?? 0));

        const parentRow = `
          <tr class="fa-grp-parent-row" onclick="faToggleGroup('${_jsKey(key)}')">
            <td><span class="fa-grp-chevron ${open ? 'open' : ''}">▸</span></td>
            <td><code style="font-size:11px">${esc(p.sku)}</code></td>
            <td>${esc(p.descripcion || '')}</td>
            <td class="text-center">${p.n_clientes ?? children.length}</td>
            <td class="text-end">${fmtNum(p.forecast)}</td>
            <td class="text-end">${fmtNum(p.venta)}</td>
            <td class="text-center">${faChipHtml(p.fa, p.fa_color ? p.fa_color.replace('c-', 'pct-') : null)}</td>
          </tr>`;

        const childRows = open ? children.map(c => `
          <tr class="fa-grp-child-row">
            <td></td>
            <td colspan="2" class="fa-grp-child-lbl">↳ ${esc(c.cliente)}</td>
            <td class="text-center" style="color:#aaa;font-size:10px">${c.n_meses} mes(es)</td>
            <td class="text-end">${fmtNum(c.forecast)}</td>
            <td class="text-end">${fmtNum(c.venta)}</td>
            <td class="text-center">${faChipHtml(c.fa, c.fa_color ? c.fa_color.replace('c-', 'pct-') : null)}</td>
          </tr>`).join('') : '';

        return parentRow + childRows;
      }).join('');

    } else {
      head.innerHTML = `
        <th style="width:24px"></th>
        <th>Cliente</th>
        <th class="text-center">N° SKUs</th>
        <th class="text-end">Forecast Total</th>
        <th class="text-end">Venta Total</th>
        <th class="text-center">FA</th>`;

      let parents = (FA.data.cliente_table || []).slice();
      if (q) {
        parents = parents.filter(p =>
          p.cliente.toLowerCase().includes(q) ||
          detail.some(d => d.cliente === p.cliente && (d.sku.toLowerCase().includes(q) || (d.descripcion || '').toLowerCase().includes(q)))
        );
      }
      if (countEl) countEl.textContent = parents.length + ' clientes';

      if (!parents.length) {
        body.innerHTML = '<tr><td colspan="6" class="text-center py-3 text-muted">Sin resultados</td></tr>';
        return;
      }

      body.innerHTML = parents.map(p => {
        const key = 'cli:' + p.cliente;
        const open = FA.expanded.has(key);
        const children = detail.filter(d => d.cliente === p.cliente)
          .sort((a, b) => (a.fa ?? 0) - (b.fa ?? 0));

        const parentRow = `
          <tr class="fa-grp-parent-row" onclick="faToggleGroup('${_jsKey(key)}')">
            <td><span class="fa-grp-chevron ${open ? 'open' : ''}">▸</span></td>
            <td>${esc(p.cliente)}</td>
            <td class="text-center">${p.n_skus ?? children.length}</td>
            <td class="text-end">${fmtNum(p.forecast)}</td>
            <td class="text-end">${fmtNum(p.venta)}</td>
            <td class="text-center">${faChipHtml(p.fa, p.fa_color ? p.fa_color.replace('c-', 'pct-') : null)}</td>
          </tr>`;

        const childRows = open ? children.map(c => `
          <tr class="fa-grp-child-row">
            <td></td>
            <td class="fa-grp-child-lbl">↳ <code style="font-size:11px">${esc(c.sku)}</code> ${esc(c.descripcion || '')}</td>
            <td class="text-center" style="color:#aaa;font-size:10px">${c.n_meses} mes(es)</td>
            <td class="text-end">${fmtNum(c.forecast)}</td>
            <td class="text-end">${fmtNum(c.venta)}</td>
            <td class="text-center">${faChipHtml(c.fa, c.fa_color ? c.fa_color.replace('c-', 'pct-') : null)}</td>
          </tr>`).join('') : '';

        return parentRow + childRows;
      }).join('');
    }
  }

  // Las keys pueden contener caracteres especiales (comillas, etc.) — codificar para usar en atributo onclick
  function _jsKey(key) {
    return encodeURIComponent(key).replace(/'/g, '%27');
  }

  /* ── Exportar CSV ─────────────────────────────────────────────── */
  function faExportSkuCsv() {
    window.location.href = '/api/fa/export/sku';
  }

  function faExportClienteSkuCsv() {
    window.location.href = '/api/fa/export/cliente-sku';
  }

  /* ── Refresh manual ───────────────────────────────────────────── */
  function faRefresh() {
    faLoad(true);
  }

  /* ── Inicialización cuando se activa la sección ───────────────── */
  function faInit() {
    if (!FA.data) {
      faLoad(false);
    }
  }

  /* ── Exponer al scope global (necesario para onclick en HTML) ──── */
  window.faRefresh             = faRefresh;
  window.faExportSkuCsv        = faExportSkuCsv;
  window.faExportClienteSkuCsv = faExportClienteSkuCsv;
  window.faFilterSkuTable      = faFilterSkuTable;
  window.faShowSubtab          = faShowSubtab;
  window.faSetGroupMode        = faSetGroupMode;
  window.faRenderGroupTable    = faRenderGroupTable;
  window.faToggleGroup         = function (encodedKey) { faToggleGroup(decodeURIComponent(encodedKey)); };
  window.faInit                = faInit;

  /* ── Hook en showSection de dashboard.js ─────────────────────── */
  const _origShowSection = window.showSection;
  window.showSection = function (name) {
    if (typeof _origShowSection === 'function') _origShowSection(name);
    if (name === 'fa') faInit();
  };

})();
