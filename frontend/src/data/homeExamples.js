/** Empty-state starter questions for 问数 / 洞察. Copied from DDI 业务知识样本. */

export const ASK_HOME_EXAMPLES = [
  {
    id: 'sales',
    title: '销售表现',
    icon: 'chart',
    questions: [
      '最近完整月全国销售金额是多少？',
      '2025年1月至10月，全国销售金额逐月如何变化？',
    ],
  },
  {
    id: 'attainment',
    title: '目标达成',
    icon: 'target',
    questions: [
      '2025年10月全国金额达成率是多少？',
      '2025年10月各品牌的实际金额和目标金额是多少？',
    ],
  },
  {
    id: 'rank',
    title: '区域排名',
    icon: 'rank',
    questions: [
      '2025年10月销售金额最高的十个省份是哪些？',
      '2025年10月广州、成都、武汉的销售金额分别是多少？',
    ],
  },
]
export const INSIGHT_HOME_EXAMPLES = [
  {
    id: 'diagnose',
    title: '达成诊断',
    icon: 'target',
    questions: [
      '分析全国金额达成，并指出低于 80% 的省份',
      '分析模拟品牌03 最近的金额、指标与达成',
    ],
  },
  {
    id: 'growth',
    title: '增长拆解',
    icon: 'chart',
    questions: [
      '分析全国销售金额同比与环比的主要驱动',
      '对比 2026Q2 相对 Q1 的全国金额季度环比',
    ],
  },
  {
    id: 'structure',
    title: '结构洞察',
    icon: 'rank',
    questions: [
      '从大区与品牌拆解本月销售金额结构',
      '使用DDI分析与html模板，生成可筛选的商业表现报告',
    ],
  },
]

export function homeExamplesForMode(insightMode) {
  return insightMode ? INSIGHT_HOME_EXAMPLES : ASK_HOME_EXAMPLES
}

export function homeExamplesForChatbot(bot, insightMode) {
  if (bot?.personal_uploads) return [
    { id: 'moc-overview', title: '经营总览', icon: 'chart', questions: ['查看最新月份的销售金额、销售数量和目标达成率，生成柱线复合图', '展示最近12个月的金额、目标与达成趋势，顶部列出关键数字'] },
    { id: 'moc-diagnosis', title: '达成与增长', icon: 'target', questions: ['分析哪些城市贡献了主要目标缺口，继续按渠道和产品下钻', '分析最新月份销售同比变化，区分金额与数量的主要贡献'] },
    { id: 'moc-structure', title: '结构与明细', icon: 'rank', questions: ['用堆叠柱图展示各城市的渠道销售结构，并显示图表数据', '比较各城市的金额、数量、达成与毛利，生成多指标复合图'] },
  ]
  if (!bot || bot.category === 'ddi' || (!bot.workbook_ids?.length && bot.lab_ids?.includes('actual'))) return homeExamplesForMode(insightMode)
  if (bot.category !== 'behavior') return [
    { id: 'overview', title: '认识数据', icon: 'chart', questions: ['当前工作簿有哪些字段和可用的分析指标？', '核验当前数据的记录数和日期范围'] },
    { id: 'analysis', title: '业务分析', icon: 'target', questions: ['分析最新一期核心指标，按主要维度对比差异', '找出当前数据中最值得关注的变化，并下钻分析'] },
    { id: 'report', title: '可视化呈现', icon: 'rank', questions: ['用图表展示当前数据的主要结构', '基于当前数据生成一份可筛选的分析报告'] },
  ]
  return insightMode ? [
    { id: 'diagnose', title: '转化诊断', icon: 'target', questions: ['分析最近一个月转化率，主动下钻区域和渠道解释主要差异', '分析华南最近两个月转化率下降的主要贡献渠道'] },
    { id: 'growth', title: '活跃增长', icon: 'chart', questions: ['分析活跃用户的月度趋势，定位增长贡献最大的渠道', '比较华东与华北的活跃和复访表现'] },
    { id: 'structure', title: '路径洞察', icon: 'rank', questions: ['按渠道对比访问、活跃与转化人数，并用图表展示', '分析最近一个月复访率，指出值得继续验证的原因'] },
  ] : [
    { id: 'visits', title: '访问与活跃', icon: 'chart', questions: ['最近一个月各渠道的访问人数和活跃用户是多少？', '展示2026年1至9月的活跃用户趋势'] },
    { id: 'conversion', title: '转化表现', icon: 'target', questions: ['最近一个月各区域的转化率是多少？', '华南线上活动渠道最近三个月的转化表现如何？'] },
    { id: 'retention', title: '复访分析', icon: 'rank', questions: ['按渠道比较最近一个月的复访率', '对比华东与华南最近一个月的活跃和转化表现'] },
  ]
}
