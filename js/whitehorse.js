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
    if (!container || !count) return;
    count.textContent = list.length;
    if (list.length === 0) {
      container.innerHTML = `<li class="wh-signal-item empty-signal">暂无信号</li>`;
      return;
    }
    container.innerHTML = list.map(item => {
      const chg = item.change_pct != null ? Number(item.change_pct) : null;
      const chgHtml = chg != null ? `
        <span style="font-size:0.8rem; font-weight:600; color: ${chg > 0 ? '#e03c3c' : (chg < 0 ? '#07c160' : 'inherit')}">
          ${chg > 0 ? '+' : ''}${chg.toFixed(2)}%
        </span>` : '';
      const gap = item.gap_pct != null ? Number(item.gap_pct) : 0;
      return `
        <li class="wh-signal-item">
          <div class="wh-stock-info">
            <span class="wh-stock-name">${item.emoji ? item.emoji + ' ' : ''}${item.name || item.code}</span>
            <span class="wh-stock-code">${item.code}</span>
          </div>
          <div>
            <div class="wh-stock-target">
              ${item.price != null ? Number(item.price).toFixed(2) : '-'} 
              ${chgHtml}
            </div>
            <div class="wh-stock-gap" style="color: ${gap < 0 ? '#e03c3c' : '#07c160'}">偏离 ${gap > 0 ? '+' : ''}${gap}%</div>
          </div>
        </li>
      `;
    }).join('');
  }

  function renderRow(item, showSell) {
    const chg = item.change_pct != null ? Number(item.change_pct) : null;
    const chgColor = chg != null ? (chg > 0 ? '#e03c3c' : (chg < 0 ? '#07c160' : 'inherit')) : 'inherit';
    const chgSign = chg != null && chg > 0 ? '+' : '';
    const chgText = chg != null ? `${chgSign}${chg.toFixed(2)}%` : '--';
    
    const priceText = item.price != null ? Number(item.price).toFixed(2) : '--';
    const maText = item.ma != null ? Number(item.ma).toFixed(2) : '--';
    const gapText = item.gap_pct != null ? `${item.gap_pct > 0 ? '+' : ''}${Number(item.gap_pct).toFixed(2)}%` : '--';
    const buy1Text = item.buy1 != null ? Number(item.buy1).toFixed(2) : '--';
    const buy2Text = item.buy2 != null ? Number(item.buy2).toFixed(2) : '--';
    const sellVal = item.sell != null ? Number(item.sell) : (item.ma != null ? Number(item.ma * 1.12) : null);
    const sellCol = showSell ? `<td style="text-align:right">${sellVal != null ? sellVal.toFixed(2) : '-'}</td>` : '';
    const statusText = item.status || '正常';
    
    return `
      <tr>
        <td><span style="color:var(--text-muted);font-size:0.8rem">${item.code}</span></td>
        <td style="font-weight:600">${item.emoji ? item.emoji + ' ' : ''}${item.name || item.code}</td>
        <td style="text-align:right;font-weight:700">${priceText}</td>
        <td style="text-align:right;color:${chgColor}">${chgText}</td>
        <td style="text-align:right">${maText}</td>
        <td style="text-align:right">${gapText}</td>
        <td style="text-align:right;color:#07c160">${buy1Text}</td>
        <td style="text-align:right;color:#07c160">${buy2Text}</td>
        ${sellCol}
        <td style="text-align:center"><span class="status-badge ${getStatusClass(statusText)}">${statusText}</span></td>
      </tr>
    `;
  }

  async function loadWhitehorseData(targetDate) {
    showLoading();
    let url = targetDate ? `data/history/whitehorse_data_${targetDate}.json` : 'data/whitehorse_data.json';

    try {
      const fetchUrl = url.includes('?') ? `${url}&_t=${Date.now()}` : `${url}?_t=${Date.now()}`;
      const res = await fetch(fetchUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      const parsedDate = data.update_time ? data.update_time.split(' ')[0] : '今日';
      updateTimeEl.innerHTML = `✅ 数据基准日期: <strong style="color:var(--text-primary)">${parsedDate}</strong> (最后计算: ${data.update_time})`;
      
      const sigs = data.signals || {};
      const allBuys = [...(sigs.buy || []), ...(sigs.buy2 || [])];
      renderList('list-buy', 'count-buy', allBuys);
      renderList('list-near', 'count-near', sigs.near || []);
      renderList('list-sell', 'count-sell', sigs.sell || []);

      let all = [];
      if (Array.isArray(data)) {
        all = data;
      } else if (Array.isArray(data.all_status)) {
        all = data.all_status;
      } else if (sigs && Array.isArray(sigs.all_status)) {
        all = sigs.all_status;
      }

      const rangeItems = all.filter(x => (x.category || x.type || '').includes('横盘')).sort((a,b) => (b.gap_pct || 0) - (a.gap_pct || 0));
      const trendItems = all.filter(x => (x.category || x.type || '').includes('趋势')).sort((a,b) => (b.gap_pct || 0) - (a.gap_pct || 0));
      const holdItems = all.filter(x => (x.category || x.type || '').includes('持有')).sort((a,b) => (b.gap_pct || 0) - (a.gap_pct || 0));

      tableRange.innerHTML = rangeItems.map(x => renderRow(x, true)).join('');
      tableTrend.innerHTML = trendItems.map(x => renderRow(x, true)).join('');
      tableHold.innerHTML = holdItems.map(x => renderRow(x, true)).join('');

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
