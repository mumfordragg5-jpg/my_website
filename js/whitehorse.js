document.addEventListener('DOMContentLoaded', () => {
  const tableRange = document.getElementById('table-range');
  const tableTrend = document.getElementById('table-trend');
  const tableHold = document.getElementById('table-hold');
  const updateTimeEl = document.getElementById('updateTime');
  const historyDateInput = document.getElementById('historyDateInput');
  const btnResetDate = document.getElementById('btnResetDate');
  
  let currentDateMode = null; // null = latest
  const today = new Date().toISOString().split('T')[0];

  function showLoading() {
    [tableRange, tableTrend, tableHold].forEach(t => {
      t.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:40px;color:var(--text-muted);">加载中...</td></tr>`;
    });
  }

  function getStatusClass(status) {
    if (status.includes('买入') || status.includes('补仓')) return 'status-buy';
    if (status.includes('卖出')) return 'status-sell';
    if (status.includes('到位')) return 'status-near';
    return 'status-normal';
  }

  function renderList(containerId, countId, list) {
    const container = document.getElementById(containerId);
    const count = document.getElementById(countId);
    count.textContent = list.length;
    if (list.length === 0) {
      container.innerHTML = `<li class="wh-signal-item empty-signal">暂无信号</li>`;
      return;
    }
    container.innerHTML = list.map(item => `
      <li class="wh-signal-item">
        <div class="wh-stock-info">
          <span class="wh-stock-name">${item.emoji} ${item.name}</span>
          <span class="wh-stock-code">${item.code}</span>
        </div>
        <div>
          <div class="wh-stock-target">${item.target ? item.target.toFixed(2) : '-'}</div>
          <div class="wh-stock-gap" style="color: ${item.gap_pct < 0 ? '#e03c3c' : '#07c160'}">偏离 ${item.gap_pct > 0 ? '+' : ''}${item.gap_pct}%</div>
        </div>
      </li>
    `).join('');
  }

  function renderRow(item, showSell) {
    const chgColor = item.change_pct > 0 ? '#e03c3c' : (item.change_pct < 0 ? '#07c160' : 'inherit');
    const chgSign = item.change_pct > 0 ? '+' : '';
    let sellCol = showSell ? `<td style="text-align:right">${item.sell ? item.sell.toFixed(2) : '-'}</td>` : '';
    
    return `
      <tr>
        <td><span style="color:var(--text-muted);font-size:0.8rem">${item.code}</span></td>
        <td style="font-weight:600">${item.emoji} ${item.name}</td>
        <td style="text-align:right;font-weight:700">${item.price.toFixed(2)}</td>
        <td style="text-align:right;color:${chgColor}">${chgSign}${item.change_pct.toFixed(2)}%</td>
        <td style="text-align:right">${item.ma.toFixed(2)}</td>
        <td style="text-align:right">${item.gap_pct > 0 ? '+' : ''}${item.gap_pct}%</td>
        <td style="text-align:right;color:#07c160">${item.buy1.toFixed(2)}</td>
        <td style="text-align:right;color:#07c160">${item.buy2.toFixed(2)}</td>
        ${sellCol}
        <td style="text-align:center"><span class="status-badge ${getStatusClass(item.status)}">${item.status}</span></td>
      </tr>
    `;
  }

  async function loadWhitehorseData(targetDate) {
    showLoading();
    let url = targetDate ? `/api/whitehorse-data?date=${targetDate}` : '/data/whitehorse_data.json';
    if (!targetDate && window.location.hostname === 'localhost') {
        url = `/api/whitehorse-data?date=${today}`;
    }
    if (window.location.protocol === 'file:') {
        url = 'data/whitehorse_data.json';
        if (targetDate) url = `data/history/whitehorse_data_${targetDate}.json`;
    }

    try {
      const fetchUrl = url.includes('?') ? `${url}&_t=${Date.now()}` : `${url}?_t=${Date.now()}`;
      const res = await fetch(fetchUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      updateTimeEl.innerHTML = `✅ 数据基准日期: <strong style="color:var(--text-primary)">${data.target_date}</strong> (最后计算: ${data.last_update})`;
      
      const sigs = data.signals || {};
      const allBuys = [...(sigs.buy || []), ...(sigs.buy2 || [])];
      renderList('list-buy', 'count-buy', allBuys);
      renderList('list-near', 'count-near', sigs.near || []);
      renderList('list-sell', 'count-sell', sigs.sell || []);

      const all = sigs.all_status || [];
      const rangeItems = all.filter(x => x.category.includes('横盘')).sort((a,b) => b.gap_pct - a.gap_pct);
      const trendItems = all.filter(x => x.category.includes('趋势')).sort((a,b) => b.gap_pct - a.gap_pct);
      const holdItems = all.filter(x => x.category.includes('持有')).sort((a,b) => b.gap_pct - a.gap_pct);

      tableRange.innerHTML = rangeItems.map(x => renderRow(x, true)).join('');
      tableTrend.innerHTML = trendItems.map(x => renderRow(x, false)).join('');
      tableHold.innerHTML = holdItems.map(x => renderRow(x, false)).join('');

    } catch (e) {
      console.error(e);
      updateTimeEl.innerHTML = `❌ 加载数据失败，可能是该日期没有历史记录`;
      [tableRange, tableTrend, tableHold].forEach(t => {
        t.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:40px;color:#e03c3c;">加载失败：${e.message}</td></tr>`;
      });
    }
  }

  historyDateInput.addEventListener('change', (e) => {
    const selected = e.target.value;
    if (selected) {
      currentDateMode = selected;
      btnResetDate.style.display = 'inline-block';
      loadWhitehorseData(selected);
    }
  });

  btnResetDate.addEventListener('click', () => {
    currentDateMode = null;
    historyDateInput.value = '';
    btnResetDate.style.display = 'none';
    loadWhitehorseData(null);
  });

  loadWhitehorseData(null);
});
