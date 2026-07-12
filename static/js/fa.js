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
    cliSkuRows:    [],     // filas para tabla Cliente-SKU
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

  function faChipHtml(fa, cls) {
    if (fa === null || fa === undefined) return '<span class="pct-chip pct-red">—</span>';
    const c = cls || (fa >= 80 ? 'pct-green' : fa >= 60 ? 'pct-yellow' : fa >= 40 ? 'pct-orange' : 'pct-red');
    return `<span class="pct-chip ${c}">${fa.toFixed(1)}%</span>`;
  }

  function fmtNum(n) {
    if (n === null || n === undefined) return '—';
    return Number(n).toLocaleString('es-CL', { maximumFractionDigits: 0 });
  }

  /* ── Carga de datos ───────────────────────────────────────────── */
  async function faLoad(force) {
    const url = force ? null : '/api/fa/data';
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
        // after refresh, load full data
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
    _renderCliSkuTable(d.cliente_sku_table || [], d.clientes || [], d.meses || []);
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

  /* ── KPIs ─────────────────────────────────────────────────────── */
  function _renderKpis(kpis) {
    const fa      = kpis.fa_ultimo_mes;
    const faTotal = kpis.fa_total;
    const variac  = kpis.variacion;
    const tend    = kpis.tendencia;
    const col     = faColorByVal(fa);

    // KPI principal
    const vEl = document.getElementById('faKpiValue');
    if (vEl) {
      vEl.textContent = fa !== null && fa !== undefined ? fa.toFixed(1) + '%' : '—';
      vEl.style.color = col.text;
    }
    const mEl = document.getElementById('faKpiMain');
    if (mEl) {
      mEl.style.borderLeftColor = col.border;
      const lbl = document.querySelector('#faKpiMain .kpi-label');
      if (lbl) lbl.textContent = 'FA ' + (kpis.mes_label || 'Último Mes');
    }
    const sEl = document.getElementById('faKpiSub');
    if (sEl) {
      if (kpis.fa_mes_ant !== null && kpis.fa_mes_ant !== undefined) {
        sEl.textContent = `Mes anterior (${kpis.mes_ant_label || ''}): ${kpis.fa_mes_ant.toFixed(1)}%`;
      } else {
        sEl.textContent = '';
      }
    }

    // FA Total
    const totEl  = document.getElementById('faKpiTotal');
    const totSub = document.getElementById('faKpiTotalSub');
    if (totEl) {
      totEl.textContent = faTotal !== null && faTotal !== undefined ? faTotal.toFixed(1) + '%' : '—';
      totEl.style.color = faColorByVal(faTotal).text;
    }
    if (totSub) totSub.textContent = `${kpis.n_meses || 0} meses`;

    // Variación
    const varEl  = document.getElementById('faKpiVar');
    const varSub = document.getElementById('faKpiVarSub');
    if (varEl) {
      if (variac !== null && variac !== undefined) {
        const sign = variac > 0 ? '+' : '';
        varEl.textContent = sign + variac.toFixed(1) + '%';
        varEl.style.color = variac > 0 ? '#16a34a' : variac < 0 ? '#dc2626' : '#565454';
      } else {
        varEl.textContent = '—';
        varEl.style.color = '';
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
            <div class="fa-rank-sku">${r.sku}</div>
            <div class="fa-rank-desc">${r.descripcion || r.clientes || ''}</div>
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
      meses.map(m => `<th class="fa-hm-mes-col">${m}</th>`).join('') +
      '</tr>';

    tbody.innerHTML = matrix.map(row => {
      const cells = row.values.map((v, i) => {
        const bg   = row.colors[i];
        const text = v !== null ? v.toFixed(1) + '%' : '—';
        const txtColor = v !== null ? faColorByVal(v).text : '#aaa';
        return `<td class="fa-hm-cell" style="background:${bg};color:${txtColor}">${text}</td>`;
      }).join('');
      return `<tr><td class="fa-hm-cliente">${row.cliente}</td>${cells}</tr>`;
    }).join('');
  }

  /* ── Tabla FA por SKU ─────────────────────────────────────────── */
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
      tbody.innerHTML = '<tr><td colspan="6" class="text-center py-3 text-muted">Sin resultados</td></tr>';
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
        <td><code style="font-size:11px">${r.sku}</code></td>
        <td>${r.descripcion || ''}</td>
        <td class="text-end">${fmtNum(r.forecast)}</td>
        <td class="text-end">${fmtNum(r.venta)}</td>
        <td class="text-center">${faChipHtml(r.fa, r.fa_color ? r.fa_color.replace('c-', 'pct-') : null)}</td>
        <td class="text-center"><div class="fa-spark-row">${trend}</div></td>
      </tr>`;
    }).join('');
  }

  /* ── Tabla FA Cliente-SKU ─────────────────────────────────────── */
  function _renderCliSkuTable(rows, clientes, meses) {
    FA.cliSkuRows = rows;

    // Poblar filtros
    const selCli = document.getElementById('faCliSkuCliente');
    if (selCli) {
      selCli.innerHTML = '<option value="">Todos los clientes</option>' +
        clientes.map(c => `<option value="${c}">${c}</option>`).join('');
    }
    const selMes = document.getElementById('faCliSkuMes');
    if (selMes) {
      selMes.innerHTML = '<option value="">Todos los meses</option>' +
        meses.map(m => `<option value="${m.key}">${m.label}</option>`).join('');
    }

    faFilterCliSkuTable();
  }

  function faFilterCliSkuTable() {
    const cli = document.getElementById('faCliSkuCliente')?.value || '';
    const mes = document.getElementById('faCliSkuMes')?.value || '';
    const q   = (document.getElementById('faCliSkuSearch')?.value || '').toLowerCase();

    const rows = FA.cliSkuRows.filter(r =>
      (!cli || r.cliente === cli) &&
      (!mes || r.mes === mes) &&
      (!q   || r.sku.toLowerCase().includes(q) || (r.descripcion || '').toLowerCase().includes(q))
    );

    const countEl = document.getElementById('faCliSkuCount');
    if (countEl) countEl.textContent = rows.length + ' filas';

    const tbody = document.getElementById('faCliSkuBody');
    if (!tbody) return;

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center py-3 text-muted">Sin resultados</td></tr>';
      return;
    }

    tbody.innerHTML = rows.map(r => `<tr>
      <td>${r.cliente}</td>
      <td><code style="font-size:11px">${r.sku}</code></td>
      <td>${r.descripcion || ''}</td>
      <td style="color:#888;font-size:11px">${r.mes_label || r.mes}</td>
      <td class="text-end">${fmtNum(r.forecast)}</td>
      <td class="text-end">${fmtNum(r.venta)}</td>
      <td class="text-center">${faChipHtml(r.fa, r.fa_color ? r.fa_color.replace('c-', 'pct-') : null)}</td>
    </tr>`).join('');
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
  window.faRefresh          = faRefresh;
  window.faExportSkuCsv    = faExportSkuCsv;
  window.faExportClienteSkuCsv = faExportClienteSkuCsv;
  window.faFilterSkuTable  = faFilterSkuTable;
  window.faFilterCliSkuTable = faFilterCliSkuTable;
  window.faInit             = faInit;

  /* ── Hook en showSection de dashboard.js ─────────────────────── */
  const _origShowSection = window.showSection;
  window.showSection = function (name) {
    if (typeof _origShowSection === 'function') _origShowSection(name);
    if (name === 'fa') faInit();
  };

})();
