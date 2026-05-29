// ETF 选股页面控制逻辑
let etfData = null;
let currentFilter = 'all'; // 'all' 或 'bullish'

document.addEventListener('DOMContentLoaded', () => {
  loadEtfData();
  initFilterButtons();
});

// 加载数据
async function loadEtfData() {
  const tableBody = document.getElementById('rankTableBody');
  try {
    const response = await fetch('data/etf_data.json');
    if (!response.ok) {
      throw new Error('未找到最新的数据文件 etf_data.json');
    }
    
    etfData = await response.json();
    renderPageData();
  } catch (error) {
    console.error('加载 ETF 数据失败:', error);
    showErrorMessage('暂无今日量化数据，请等待下午 15:00 收盘后系统自动计算发布。');
  }
}

// 按钮筛选绑定
function initFilterButtons() {
  const btnAll = document.getElementById('btnFilterAll');
  const btnBullish = document.getElementById('btnFilterBullish');
  if (!btnAll || !btnBullish) return;

  btnAll.addEventListener('click', () => {
    btnAll.classList.add('active');
    btnBullish.classList.remove('active');
    currentFilter = 'all';
    renderRankingsTable();
  });

  btnBullish.addEventListener('click', () => {
    btnBullish.classList.add('active');
    btnAll.classList.remove('active');
    currentFilter = 'bullish';
    renderRankingsTable();
  });
}

// 渲染全部页面数据
function renderPageData() {
  if (!etfData) return;

  // 1. 更新发布时间
  const updateTimeText = document.getElementById('updateTime');
  if (updateTimeText) {
    updateTimeText.textContent = `最新计算发布时间：${etfData.update_time}`;
  }

  // 2. 渲染决策卡片
  renderDecisionCard();

  // 3. 渲染排行榜
  renderRankingsTable();
}

// 渲染决策卡片
function renderDecisionCard() {
  const card = document.getElementById('decisionCard');
  if (!card) return;

  const target = etfData.today_target;
  const action = target.action || '持仓保持';
  
  // 确定决策样式主题
  let badgeClass = 'signal-empty';
  let badgeText = '持续空仓';
  
  if (action.includes('买入') || action.includes('开仓')) {
    badgeClass = 'signal-buy';
    badgeText = '🟢 买入开仓';
  } else if (action.includes('警报') || action.includes('换仓') || action.includes('更替')) {
    badgeClass = 'signal-sell';
    badgeText = '🚨 调仓换股';
  } else if (action.includes('保持') || action.includes('持有')) {
    badgeClass = 'signal-hold';
    badgeText = '★ 策略持有';
  } else if (action.includes('平仓') || action.includes('卖出变现')) {
    badgeClass = 'signal-sell';
    badgeText = '🔴 卖出空仓';
  }

  // 替换卡片内部的骨架屏与占位
  let targetNameHtml = '现金 / 黄金账户 <span class="target-asset-code">空仓观望中</span>';
  let targetPriceHtml = '--';

  if (target.code) {
    targetNameHtml = `${target.name} <span class="target-asset-code">${target.code}</span>`;
    targetPriceHtml = target.price ? `${target.price.toFixed(3)} 元` : '--';
  }

  card.innerHTML = `
    <div class="signal-status-box">
      <span class="signal-badge ${badgeClass}">${badgeText}</span>
      <span class="signal-title-text">${action}</span>
    </div>
    <p class="signal-desc-text">${target.signal_desc}</p>
    
    <div class="target-asset-card">
      <div class="target-asset-info">
        <span class="target-asset-label">当前策略推荐持仓</span>
        <div class="target-asset-name">${targetNameHtml}</div>
      </div>
      <div class="target-asset-value">
        <span class="target-asset-price">${targetPriceHtml}</span>
      </div>
    </div>
  `;
}

// 渲染排行榜表格
function renderRankingsTable() {
  const tableBody = document.getElementById('rankTableBody');
  if (!tableBody || !etfData || !etfData.all_etfs) return;

  // 清空内容
  tableBody.innerHTML = '';

  let listToRender = etfData.all_etfs;

  // 仅显示多头
  if (currentFilter === 'bullish') {
    listToRender = listToRender.filter(item => !item.is_filtered);
  }

  if (listToRender.length === 0) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 40px 0;">
          当前没有符合 EMA 多头趋势且流动性充裕的标的。
        </td>
      </tr>
    `;
    return;
  }

  listToRender.forEach((item, index) => {
    const tr = document.createElement('tr');
    
    // 设置行类样式：是否为目标持仓、是否被过滤
    if (item.is_target) {
      tr.classList.add('row-target');
    } else if (item.is_filtered) {
      tr.classList.add('row-filtered');
    }

    // 趋势球
    const isBull = item.trend === '多头';
    const trendHtml = `<span class="trend-dot ${isBull ? 'trend-bullish' : 'trend-bearish'}"></span>${item.trend}`;

    // 推荐/过滤徽章
    let badgeHtml = '';
    if (item.is_target) {
      badgeHtml = `<span class="badge-target">★ 策略选中</span>`;
    } else if (item.is_filtered) {
      // 区分原因
      const filterReason = !item.liquid ? '流动性低' : '均线空头';
      badgeHtml = `<span class="badge-filtered">${filterReason}</span>`;
    }

    // 得分进度条
    const maxScoreVal = 15; // 作为最大值百分比锚点以使进度条更饱满
    const absVal = Math.min(Math.abs(item.score), maxScoreVal);
    const pct = (absVal / maxScoreVal) * 100;
    const isPos = item.score >= 0;
    
    const progressBarHtml = `
      <div class="score-container">
        <span class="score-num" style="color: ${isPos ? 'var(--accent)' : 'var(--text-muted)'};">${item.score > 0 ? '+' : ''}${item.score.toFixed(2)}</span>
        <div class="score-bar-bg">
          <div class="score-bar-fill ${isPos ? 'fill-positive' : 'fill-negative'}" style="width: ${pct}%;"></div>
        </div>
      </div>
    `;

    // 涨跌幅染色
    const chg1 = item.pct_1 !== undefined ? item.pct_1 : null;
    const colorChg1 = chg1 > 0 ? '#e03c3c' : (chg1 < 0 ? '#07c160' : 'inherit');
    const chg5 = item.pct_5 !== undefined ? item.pct_5 : null;
    const colorChg5 = chg5 > 0 ? '#e03c3c' : (chg5 < 0 ? '#07c160' : 'inherit');
    const chg20 = item.pct_20;
    const colorChg20 = chg20 > 0 ? '#e03c3c' : (chg20 < 0 ? '#07c160' : 'inherit');

    const chg1Text = chg1 !== null ? `${chg1 > 0 ? '+' : ''}${chg1.toFixed(2)}%` : '--';
    const chg5Text = chg5 !== null ? `${chg5 > 0 ? '+' : ''}${chg5.toFixed(2)}%` : '--';

    tr.innerHTML = `
      <td style="font-weight: 700;">${index + 1}</td>
      <td style="font-family: monospace;">${item.code}</td>
      <td>${item.name}${badgeHtml}</td>
      <td style="text-align: right; font-weight: 600;">${item.price.toFixed(3)}</td>
      <td style="text-align: right; color: ${colorChg1};">${chg1Text}</td>
      <td style="text-align: right; color: ${colorChg5};">${chg5Text}</td>
      <td style="text-align: right; color: ${item.bias > 0 ? '#e03c3c' : (item.bias < 0 ? '#07c160' : 'inherit')};">${item.bias > 0 ? '+' : ''}${item.bias.toFixed(2)}%</td>
      <td style="text-align: right; color: ${colorChg20}; font-weight: 600;">${chg20 > 0 ? '+' : ''}${chg20.toFixed(2)}%</td>
      <td><div style="display: flex; justify-content: center;">${progressBarHtml}</div></td>
      <td style="text-align: center;">${trendHtml}</td>
    `;

    tableBody.appendChild(tr);
  });
}

// 错误处理与提示
function showErrorMessage(message) {
  const card = document.getElementById('decisionCard');
  if (card) {
    card.innerHTML = `
      <div class="signal-status-box">
        <span class="signal-badge signal-empty">⚠️ 提示</span>
        <span class="signal-title-text">今日数据同步中</span>
      </div>
      <p class="signal-desc-text" style="color: var(--text-muted);">${message}</p>
    `;
  }

  const tableBody = document.getElementById('rankTableBody');
  if (tableBody) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="10" style="text-align: center; color: var(--text-muted); padding: 60px 0;">
          等待每日最新收盘行情导入...
        </td>
      </tr>
    `;
  }
}
