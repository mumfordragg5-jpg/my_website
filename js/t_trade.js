document.addEventListener('DOMContentLoaded', () => {
  const updateTimeEl = document.getElementById('updateTime');
  const tableBody = document.getElementById('table-t-stocks');
  const historyDateInput = document.getElementById('historyDateInput');
  const btnResetDate = document.getElementById('btnResetDate');

  function showLoading() {
    if (tableBody) {
      tableBody.innerHTML = `<tr><td colspan="13" style="text-align:center;padding:40px;color:var(--text-muted);">正在同步做T数据...</td></tr>`;
    }
  }

  function getStatusClass(status) {
    if (status.includes('买入')) return 'status-buy';
    if (status.includes('卖出')) return 'status-sell';
    if (status.includes('临近')) return 'status-near';
    return 'status-normal';
  }

  function renderList(containerId, countId, list, type) {
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
      
      let gapText = '';
      let gapColor = '#07c160';
      if (type === 'BUY' || type === 'NEAR_BUY') {
        const gap = item.gap_buy_pct != null ? Number(item.gap_buy_pct) : 0;
        gapText = `距买点 ${gap > 0 ? '+' : ''}${gap.toFixed(2)}%`;
        gapColor = gap <= 0 ? '#07c160' : '#f5a623';
      } else {
        const gap = item.gap_sell_pct != null ? Number(item.gap_sell_pct) : 0;
        gapText = `距卖点 ${gap > 0 ? '+' : ''}${gap.toFixed(2)}%`;
        gapColor = gap >= 0 ? '#e03c3c' : '#ff9a76';
      }

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
            <div class="wh-stock-gap" style="color: ${gapColor}">${gapText}</div>
          </div>
        </li>
      `;
    }).join('');
  }

  function renderRow(item) {
    const chg = item.change_pct != null ? Number(item.change_pct) : null;
    const chgColor = chg != null ? (chg > 0 ? '#e03c3c' : (chg < 0 ? '#07c160' : 'inherit')) : 'inherit';
    const chgSign = chg != null && chg > 0 ? '+' : '';
    const chgText = chg != null ? `${chgSign}${chg.toFixed(2)}%` : '--';

    const priceText = item.price != null ? Number(item.price).toFixed(2) : '--';
    const lowText = item.low != null ? Number(item.low).toFixed(2) : '--';
    const highText = item.high != null ? Number(item.high).toFixed(2) : '--';
    const rangeText = `${lowText} ~ ${highText}`;

    const buyPrice = item.buy_price != null ? Number(item.buy_price).toFixed(2) : '--';
    const sellPrice = item.sell_price != null ? Number(item.sell_price).toFixed(2) : '--';
    const spreadPct = item.spread_pct != null ? `+${Number(item.spread_pct).toFixed(2)}%` : '--';

    const gapBuy = item.gap_buy_pct != null ? Number(item.gap_buy_pct) : null;
    const gapBuyColor = gapBuy != null ? (gapBuy <= 0 ? '#07c160' : (gapBuy <= 1.0 ? '#f5a623' : 'inherit')) : 'inherit';
    const gapBuyText = gapBuy != null ? `${gapBuy > 0 ? '+' : ''}${gapBuy.toFixed(2)}%` : '--';

    const gapSell = item.gap_sell_pct != null ? Number(item.gap_sell_pct) : null;
    const gapSellColor = gapSell != null ? (gapSell >= 0 ? '#e03c3c' : (gapSell >= -1.0 ? '#ff9a76' : 'inherit')) : 'inherit';
    const gapSellText = gapSell != null ? `${gapSell > 0 ? '+' : ''}${gapSell.toFixed(2)}%` : '--';

    // 进度条 (0% 到 100%)
    let progress = item.grid_progress != null ? Number(item.grid_progress) : 50;
    const clampProgress = Math.max(0, Math.min(100, progress));
    let progressColor = '#f5a623';
    if (progress <= 10) progressColor = '#07c160'; // 靠近买点
    else if (progress >= 90) progressColor = '#e03c3c'; // 靠近卖点

    const progressBarHtml = `
      <div class="grid-progress-wrap">
        <div class="grid-progress-bar">
          <div class="grid-progress-fill" style="width: ${clampProgress}%; background: ${progressColor};"></div>
        </div>
        <div class="grid-progress-label">
          <span>${buyPrice}</span>
          <span style="font-weight:700; color:${progressColor}">${progress.toFixed(0)}%</span>
          <span>${sellPrice}</span>
        </div>
      </div>
    `;

    const statusText = item.status || '区间震荡';
    const noteText = item.note || '--';

    return `
      <tr>
        <td><span style="color:var(--text-muted);font-family:monospace;font-size:0.85rem">${item.code}</span></td>
        <td style="font-weight:700">${item.emoji ? item.emoji + ' ' : ''}${item.name || item.code}</td>
        <td style="text-align:right;font-weight:800;font-size:1.05rem">${priceText}</td>
        <td style="text-align:right;font-weight:600;color:${chgColor}">${chgText}</td>
        <td style="text-align:right;color:var(--text-muted);font-size:0.85rem">${rangeText}</td>
        <td style="text-align:right;color:#07c160;font-weight:700">${buyPrice}</td>
        <td style="text-align:right;color:#e03c3c;font-weight:700">${sellPrice}</td>
        <td style="text-align:right;font-weight:600;color:var(--accent)">${spreadPct}</td>
        <td style="text-align:center">${progressBarHtml}</td>
        <td style="text-align:right;color:${gapBuyColor};font-weight:600">${gapBuyText}</td>
        <td style="text-align:right;color:${gapSellColor};font-weight:600">${gapSellText}</td>
        <td style="text-align:center"><span class="status-badge ${getStatusClass(statusText)}">${statusText}</span></td>
        <td style="color:var(--text-muted);font-size:0.82rem">${noteText}</td>
      </tr>
    `;
  }

  async function loadTTradeData(targetDate) {
    showLoading();
    let url = targetDate ? `data/history/t_trade_data_${targetDate}.json` : 'data/t_trade_data.json';

    try {
      const fetchUrl = url.includes('?') ? `${url}&_t=${Date.now()}` : `${url}?_t=${Date.now()}`;
      const res = await fetch(fetchUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const parsedDate = data.update_time ? data.update_time.split(' ')[0] : '今日';
      updateTimeEl.innerHTML = `✅ 数据基准时间: <strong style="color:var(--text-primary)">${data.update_time || parsedDate}</strong>`;

      const items = data.items || [];
      const buySignals = items.filter(x => x.trigger_type === 'BUY');
      const nearBuySignals = items.filter(x => x.trigger_type === 'NEAR_BUY');
      const sellSignals = items.filter(x => x.trigger_type === 'SELL');
      const nearSellSignals = items.filter(x => x.trigger_type === 'NEAR_SELL');

      renderList('list-buy', 'count-buy', buySignals, 'BUY');
      renderList('list-near-buy', 'count-near-buy', nearBuySignals, 'NEAR_BUY');
      renderList('list-sell', 'count-sell', sellSignals, 'SELL');
      renderList('list-near-sell', 'count-near-sell', nearSellSignals, 'NEAR_SELL');

      if (tableBody) {
        if (items.length === 0) {
          tableBody.innerHTML = `<tr><td colspan="13" style="text-align:center;padding:40px;color:var(--text-muted);">暂无配置的做T标的</td></tr>`;
        } else {
          tableBody.innerHTML = items.map(renderRow).join('');
        }
      }

    } catch (e) {
      console.error(e);
      updateTimeEl.innerHTML = `❌ 加载做T数据失败，可能是该日期没有历史记录`;
      if (tableBody) {
        tableBody.innerHTML = `<tr><td colspan="13" style="text-align:center;padding:40px;color:#e03c3c;">加载失败：${e.message}</td></tr>`;
      }
    }
  }

  if (historyDateInput) {
    historyDateInput.addEventListener('change', (e) => {
      const selected = e.target.value;
      if (selected) {
        if (btnResetDate) btnResetDate.style.display = 'inline-block';
        loadTTradeData(selected);
      }
    });
  }

  if (btnResetDate) {
    btnResetDate.addEventListener('click', () => {
      if (historyDateInput) historyDateInput.value = '';
      btnResetDate.style.display = 'none';
      loadTTradeData(null);
    });
  }

  loadTTradeData(null);
});
