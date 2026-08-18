document.addEventListener('DOMContentLoaded', () => {
  const updateTimeEl = document.getElementById('updateTime');
  const tableUsStocks = document.getElementById('table-us-stocks');
  const vixVal = document.getElementById('vix-val');
  const vixStatus = document.getElementById('vix-status');
  
  const dateInput = document.getElementById('historyDateInput');
  const btnReset = document.getElementById('btnResetDate');

  function showLoading() {
    updateTimeEl.innerHTML = '<span class="loading-spinner"></span> 正在加载美股数据...';
    tableUsStocks.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:40px;color:var(--text-muted)">获取中...</td></tr>';
  }

  function renderRow(item) {
    const chgColor = item.change_pct > 0 ? '#07c160' : (item.change_pct < 0 ? '#e03c3c' : 'inherit');
    const chgSign = item.change_pct > 0 ? '+' : '';
    
    // Calculate drawdowns
    const dropFromHigh = ((item.price - item.high_52w) / item.high_52w * 100).toFixed(2);
    const dropFromMa = item.ma120 ? ((item.price - item.ma120) / item.ma120 * 100).toFixed(2) : '-';
    
    const statusText = item.is_buy ? '触发买入' : '正常';
    const statusClass = item.is_buy ? 'status-buy' : 'status-normal';
    
    return `
      <tr>
        <td><span style="color:var(--text-muted);font-size:0.8rem">${item.code}</span></td>
        <td style="font-weight:600">${item.name}</td>
        <td style="text-align:right;font-weight:700">${item.price.toFixed(2)}</td>
        <td style="text-align:right;color:${chgColor}">${chgSign}${item.change_pct.toFixed(2)}%</td>
        <td style="text-align:right">${item.high_52w.toFixed(2)}</td>
        <td style="text-align:right;color:${dropFromHigh <= -10 ? '#07c160' : 'inherit'}">${dropFromHigh}%</td>
        <td style="text-align:right">${item.ma120 ? item.ma120.toFixed(2) : '-'}</td>
        <td style="text-align:right;color:${dropFromMa <= -5 ? '#07c160' : 'inherit'}">${dropFromMa}%</td>
        <td style="text-align:center"><span class="status-badge ${statusClass}">${statusText}</span></td>
      </tr>
    `;
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
      updateTimeEl.innerHTML = `✅ 数据基准时间: <strong style="color:var(--text-primary)">${data.update_time}</strong>`;
      
      // Render VIX
      const vix = data.vix;
      if(vix) {
          vixVal.textContent = vix.price.toFixed(2);
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
      
      // Render Stocks
      const stocks = data.stocks || [];
      tableUsStocks.innerHTML = stocks.map(x => renderRow(x)).join('');

    } catch (err) {
      console.error(err);
      updateTimeEl.innerHTML = `❌ 加载数据失败，可能是该日期没有历史记录`;
      tableUsStocks.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:40px;color:#e03c3c">加载失败: ${err.message}</td></tr>`;
      vixVal.textContent = '--';
      vixStatus.textContent = '加载失败';
      vixStatus.className = 'status-badge status-normal';
    }
  }

  // Initial load
  loadUsStockData();

  // Date picker events
  dateInput.addEventListener('change', (e) => {
    if (e.target.value) {
      btnReset.style.display = 'inline-block';
      loadUsStockData(e.target.value);
    }
  });

  btnReset.addEventListener('click', () => {
    dateInput.value = '';
    btnReset.style.display = 'none';
    loadUsStockData();
  });
});
