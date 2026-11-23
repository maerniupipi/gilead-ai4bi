const REGIONS = [
  ['华东', 1.45, 1.16, .22, ['江苏省', '浙江省'], ['南京市', '杭州市']],
  ['华南', 1.2, .83, -.08, ['广东省', '福建省'], ['广州市', '福州市']],
  ['华北', 1.05, 1.04, .1, ['北京市', '河北省'], ['北京市', '石家庄市']],
  ['华中', .9, .97, .06, ['湖北省', '湖南省'], ['武汉市', '长沙市']],
  ['西南', .8, 1.08, .16, ['四川省', '重庆市'], ['成都市', '重庆市']],
  ['西北', .6, .92, .03, ['陕西省', '甘肃省'], ['西安市', '兰州市']],
]

/** No network or random state: every presentation uses the same coherent data. */
export function createSampleReport(kind = 'ddi') {
  const rows = []
  for (let month = 1; month <= 9; month++) {
    const days = new Date(Date.UTC(2026, month, 0)).getUTCDate()
    for (let day = 1; day <= days; day++) REGIONS.forEach(([region, weight, attainment, growth, provinces, cities], index) => {
      const brandIndex = (day + index) % 3
      const channelIndex = (day + index * 2) % 3
      const price = [168, 246, 325][brandIndex]
      const targetQty = Math.round((550 + month * 16) * weight * [1, .86, .68][brandIndex])
      const wave = 1 + .11 * Math.sin(day * .46 + index) + .025 * Math.cos(day + month)
      const channelFactor = index === 1 && channelIndex === 2 ? .68 : 1
      const qty = Math.round(targetQty * attainment * wave * channelFactor * (1 + (month - 6) * .008))
      const priorQty = Math.round(qty / (1 + growth + (brandIndex - 1) * .025))
      const previousQty = Math.round(qty / (1 + growth * .45 + (month % 3) * .006))
      const provinceIndex = (Math.floor(day / 3) + brandIndex) % 2
      rows.push({
        date: `2026-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
        region, province: provinces[provinceIndex], city: cities[provinceIndex],
        brand: ['品牌A', '品牌B', '品牌C'][brandIndex],
        channel: ['医院', '零售药房', '电商平台'][channelIndex],
        hco: `${cities[provinceIndex]}示例机构${String((day % 4) + 1).padStart(2, '0')}`,
        sales_qty: qty, sales_amt: qty * price, price_latest: price,
        asp_price: Math.round(price / 7.1 * 100) / 100,
        sales_amt_usd: Math.round(qty * price / 7.1 * 100) / 100,
        target_qty: targetQty, target_amt: targetQty * price,
        target_amt_usd: Math.round(targetQty * price / 7.1 * 100) / 100,
        prior_qty: priorQty, prior_amt: priorQty * price,
        prior_amt_usd: Math.round(priorQty * price / 7.1 * 100) / 100,
        previous_qty: previousQty, previous_amt: previousQty * price,
        previous_amt_usd: Math.round(previousQty * price / 7.1 * 100) / 100,
      })
    })
  }
  const columns = [
    ['date', '业务日期'], ['region', '销售大区'], ['brand', '品牌'], ['channel', '终端渠道'],
    ['province', '省份'], ['city', '城市'], ['hco', '机构'],
    ['sales_qty', '销售数量', 'number'], ['sales_amt', '销售金额 CNY', 'money'],
    ['target_amt', '目标金额 CNY', 'money'], ['target_qty', '目标数量', 'number'],
    ['prior_amt', '同期金额 CNY', 'money'], ['previous_amt', '上期金额 CNY', 'money'],
    ['sales_amt_usd', '销售金额 USD', 'money'], ['target_amt_usd', '目标金额 USD', 'money'],
    ['price_latest', '最新价格 CNY', 'money'], ['asp_price', 'ASP价格 USD', 'money'],
  ].map(([key, label, format]) => ({ key, label, format: format || 'text' }))
  return {
    id: kind === 'ddi' ? 'sample-ddi-202609' : 'sample-commercial-202609', revision: 1,
    title: kind === 'ddi' ? 'DDI 商业表现分析' : '区域销售表现与增长归因',
    subtitle: kind === 'ddi' ? '标准报表 · 目标追踪 · 增长归因' : '从区域差异识别增长机会与经营风险',
    kind, date_field: 'date', dimension: 'region', columns, rows,
    source: { demo: true, label: 'AI4BI 商业数据仓库 · 六表口径模拟', row_count: rows.length,
      note: '2026年1—9月模拟纯销；同比为去年同期对齐值，环比为上季度同进度对齐值。每日目标已分摊，不重复累计月目标；单位为销售单位。' },
    metrics: { qty: 'sales_qty', amount: 'sales_amt', amount_usd: 'sales_amt_usd', target: 'target_amt',
      target_usd: 'target_amt_usd', qty_target: 'target_qty', prior: 'prior_amt', prior_usd: 'prior_amt_usd',
      qty_prior: 'prior_qty', previous: 'previous_amt', previous_usd: 'previous_amt_usd', qty_previous: 'previous_qty' },
    filter_fields: ['region', 'brand', 'channel'],
    visible_columns: ['date', 'region', 'brand', 'sales_qty', 'sales_amt', 'target_amt', '_achievement', '_yoy'],
    period: 'day', current_period: '2026-09', window: 'period', metric: 'amount', chart_type: 'line', filters: {},
    findings: [
      { type: '已核验事实', title: '区域表现存在明显差异', body: '通过达成对比与同比贡献定位关键大区。点击区域名称可在同一份报告内继续下钻。' },
      { type: '待验证假设', title: '关注华南电商渠道表现', body: '当前样例数据中该渠道存在销量缺口。可追问“只看华南，按终端渠道分析”检验贡献。' },
      { type: '建议行动', title: '把增长机会落实到省份与机构', body: '追问“新增省份字段和销售占比”，将当前筛选细化为可执行的区域跟进清单。' },
    ],
  }
}
