document.addEventListener('DOMContentLoaded', () => {
  const tableBroad = document.getElementById('table-broad');
  const tableSector = document.getElementById('table-sector');
  const tableTech = document.getElementById('table-tech');
  const updateTimeEl = document.getElementById('updateTime');
  const vixVal = document.getElementById('vix-val');
  const vixStatus = document.getElementById('vix-status');
  
  const historyDateInput = document.getElementById('historyDateInput');
  const btnResetDate = document.getElementById('btnResetDate');

  function showLoading() {
    [tableBroad, tableSector, tableTech].forEach(t => {
      if (t) t.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:40px;color:var(--text-muted);">正在加载美股数据...</td></tr>';
    });
    updateTimeEl.innerHTML = '<span class="loading-spinner"></span> 正在同步最新行情数据...';
  }

  function getEastMoneyUrl(code) {
    if (!code) return '#';
    const clean = String(code).trim().toUpperCase();
    return `https://quote.eastmoney.com/us/${clean}.html`;
  }

  function getStatusClass(status) {
    if (!status) return 'status-normal';
    if (status.includes('买入') || status.includes('抄底')) return 'status-buy';
    if (status.includes('到位') || status.includes('接近')) return 'status-near';
    if (status.includes('恐慌') || status.includes('卖出')) return 'status-sell';
    return 'status-normal';
  }

  function renderRow(item) {
    const chg = item.change_pct != null ? Number(item.change_pct) : null;
    const chgColor = chg != null ? (chg > 0 ? '#e03c3c' : (chg < 0 ? '#07c160' : 'inherit')) : 'inherit';
    const chgSign = chg != null && chg > 0 ? '+' : '';
    const chgText = chg != null ? `${chgSign}${chg.toFixed(2)}%` : '--';
    
    const price = item.price != null ? Number(item.price) : null;
    const high52 = item.high_52w != null ? Number(item.high_52w) : null;
    const drawdown = item.drawdown_pct != null ? Number(item.drawdown_pct) : ((price != null && high52 != null && high52 > 0) ? (price - high52) / high52 * 100 : null);
    
    const ma120 = item.ma120 != null ? Number(item.ma120) : null;
    const maDev = item.ma120_dev != null ? Number(item.ma120_dev) : ((price != null && ma120 != null && ma120 > 0) ? (price - ma120) / ma120 * 100 : null);

    const bpH = item.buy_point_high != null ? Number(item.buy_point_high) : (high52 != null ? high52 * 0.9 : null);
    const bpM = item.buy_point_ma != null ? Number(item.buy_point_ma) : (ma120 != null ? ma120 * 0.95 : null);
    
    const status = item.status || (item.is_buy ? '触发买入' : (item.is_near ? '即将到位' : '正常'));
    const statusClass = getStatusClass(status);
    const stockUrl = getEastMoneyUrl(item.code);

    return `
      <tr>
        <td><span style="font-weight:700;color:var(--text-muted);font-size:0.85rem">${item.code}</span></td>
        <td style="font-weight:700">
          <a href="${stockUrl}" target="_blank" rel="noopener noreferrer" class="stock-link" title="点击查看东方财富实时行情">
            ${item.name}
          </a>
        </td>
        <td style="text-align:right;font-weight:800;font-size:0.95rem">${price != null ? '$' + price.toFixed(2) : '--'}</td>
        <td style="text-align:right;font-weight:600;color:${chgColor}">${chgText}</td>
        <td style="text-align:right">${high52 != null ? '$' + high52.toFixed(2) : '--'}</td>
        <td style="text-align:right;font-weight:600;color:${drawdown != null && drawdown <= -10 ? '#07c160' : 'inherit'}">
          ${drawdown != null ? (drawdown > 0 ? '+' : '') + drawdown.toFixed(2) + '%' : '-'}
        </td>
        <td style="text-align:right">${ma120 != null ? '$' + ma120.toFixed(2) : '-'}</td>
        <td style="text-align:right;font-weight:600;color:${maDev != null && maDev <= -5 ? '#07c160' : 'inherit'}">
          ${maDev != null ? (maDev > 0 ? '+' : '') + maDev.toFixed(2) + '%' : '-'}
        </td>
        <td style="text-align:right;color:var(--text-secondary)">${bpH != null ? '$' + bpH.toFixed(2) : '-'}</td>
        <td style="text-align:right;color:var(--text-secondary)">${bpM != null ? '$' + bpM.toFixed(2) : '-'}</td>
        <td style="text-align:center"><span class="status-badge ${statusClass}">${status}</span></td>
      </tr>
    `;
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
      const stockUrl = getEastMoneyUrl(item.code);
      const targetPrice = item.target_buy_price ? item.target_buy_price.toFixed(2) : (item.buy_point_high ? item.buy_point_high.toFixed(2) : '--');
      const isBuy = item.is_buy || (item.status && item.status.includes('买入'));
      const gapText = isBuy ? `已触及买点` : `距买点 +${gap.toFixed(2)}%`;
      const gapColor = isBuy ? '#07c160' : '#f5a623';

      return `
        <li class="wh-signal-item">
          <div class="wh-stock-info">
            <span class="wh-stock-name"><a href="${stockUrl}" target="_blank" class="stock-link">${item.name}</a></span>
            <span class="wh-stock-code">${item.code} · 现价 $${item.price != null ? item.price.toFixed(2) : '--'} ${chgHtml}</span>
          </div>
          <div style="text-align:right">
            <div class="wh-stock-target">$${targetPrice}</div>
            <div class="wh-stock-gap" style="color:${gapColor}">${gapText}</div>
          </div>
        </li>
      `;
    }).join('');
  }

  async function loadUsStockData(targetDate) {
    showLoading();
    let url = targetDate ? `data/history/us_stock_data_${targetDate}.json` : 'data/us_stock_data.json';

    try {
      const fetchUrl = url.includes('?') ? `${url}&_t=${Date.now()}` : `${url}?_t=${Date.now()}`;
      const res = await fetch(fetchUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      
      const parsedDate = data.update_time ? data.update_time.split(' ')[0] : '今日';
      updateTimeEl.innerHTML = `✅ 数据基准时间: <strong style="color:var(--text-primary)">${data.update_time || parsedDate}</strong>`;
      
      // 1. 渲染 VIX 卡片
      const vix = data.vix;
      if (vix) {
        vixVal.textContent = vix.price != null ? vix.price.toFixed(2) : '--';
        if (vix.is_panic) {
          vixVal.style.color = '#e03c3c';
          vixStatus.textContent = '🚨 极度恐慌 (抄底时机)';
          vixStatus.className = 'status-badge status-panic';
        } else {
          vixVal.style.color = 'var(--text-primary)';
          vixStatus.textContent = '情绪平稳';
          vixStatus.className = 'status-badge status-normal';
        }
      }
      
      // 2. 渲染顶部信号列表
      const sigs = data.signals || {};
      const allBuys = sigs.buy || (data.stocks ? data.stocks.filter(s => s.is_buy) : []);
      const allNears = sigs.near || (data.stocks ? data.stocks.filter(s => s.is_near) : []);
      
      renderList('list-buy', 'count-buy', allBuys);
      renderList('list-near', 'count-near', allNears);

      // 3. 渲染 3 大面板表格
      const all = data.stocks || [];
      const broadItems = all.filter(x => (x.category === 'broad') || ['QQQ', 'SPY', 'SCHD'].includes(x.code));
      const sectorItems = all.filter(x => (x.category === 'sector') || ['SOXX', 'SMH', 'VGT', 'TQQQ'].includes(x.code));
      const techItems = all.filter(x => (x.category === 'tech') || ['AAPL', 'MSFT', 'GOOG'].includes(x.code));

      if (tableBroad) {
        tableBroad.innerHTML = broadItems.length > 0 
          ? broadItems.map(x => renderRow(x)).join('')
          : '<tr><td colspan="11" style="text-align:center;padding:20px;color:var(--text-muted)">暂无该类别数据</td></tr>';
      }
      if (tableSector) {
        tableSector.innerHTML = sectorItems.length > 0 
          ? sectorItems.map(x => renderRow(x)).join('')
          : '<tr><td colspan="11" style="text-align:center;padding:20px;color:var(--text-muted)">暂无该类别数据</td></tr>';
      }
      if (tableTech) {
        tableTech.innerHTML = techItems.length > 0 
          ? techItems.map(x => renderRow(x)).join('')
          : '<tr><td colspan="11" style="text-align:center;padding:20px;color:var(--text-muted)">暂无该类别数据</td></tr>';
      }

    } catch (err) {
      console.error(err);
      updateTimeEl.innerHTML = `❌ 加载数据失败，可能是该日期没有历史记录`;
      [tableBroad, tableSector, tableTech].forEach(t => {
        if (t) t.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:40px;color:#e03c3c">加载失败: ${err.message}</td></tr>`;
      });
      if (vixVal) vixVal.textContent = '--';
      if (vixStatus) {
        vixStatus.textContent = '加载失败';
        vixStatus.className = 'status-badge status-normal';
      }
    }
  }

  // 初始加载
  loadUsStockData();

  // 历史日期选择器事件
  historyDateInput.addEventListener('change', (e) => {
    if (e.target.value) {
      btnResetDate.style.display = 'inline-block';
      loadUsStockData(e.target.value);
    }
  });

  btnResetDate.addEventListener('click', () => {
    historyDateInput.value = '';
    btnResetDate.style.display = 'none';
    loadUsStockData();
  });
});
