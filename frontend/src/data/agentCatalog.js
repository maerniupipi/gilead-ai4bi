/** Preview catalog for the agent / tool admin screens.

  Tools exist only in code. Agents pick a subset. A sub-agent is just
  another selectable capability: the parent calls it like a tool, and
  the child runs its own loop with its own tools.
*/

const STORAGE_KEY = 'xy-agent-catalog-preview'

export const TOOLS = [
  {
    name: 'ask_lab',
    label: '实验室',
    group: 'lab',
    description: '把一个原子化的查数问题交给指定实验室，产出候选 SQL。返回的 SQL 必须再用 query_db 执行后才能作为事实。',
    parameters: [
      { name: 'question', required: true, text: '原子化问题：单一意图，含产品 / 时间 / 口径' },
      { name: 'lab_id', required: true, text: '目标实验室：actual / demand / ext_simple / ext_complex' },
      { name: 'remark', required: false, text: '可选补充备注' },
      { name: 'attach_upstream', required: false, text: '以上一跳已核验结果为过滤条件时为 true' },
    ],
  },
  {
    name: 'inspect_schema',
    label: '表结构',
    group: 'lab',
    description: '读取已勾选表的结构：表名、字段、类型、注释。生成 SQL 前先调用。',
    parameters: [
      { name: 'tables', required: false, text: '可选。只看这些表；留空表示已勾选的全部表' },
    ],
  },
  {
    name: 'generate_sql',
    label: 'SQL生成',
    group: 'lab',
    description: '根据表结构和参考信息在本地生成候选 SQL，不执行。',
    parameters: [
      { name: 'question', required: true, text: '原子化查数问题' },
      { name: 'lab_id', required: false, text: '目标实验室，可选' },
      { name: 'context', required: false, text: '已召回的参考信息' },
    ],
  },
  {
    name: 'validate_sql',
    label: 'SQL校验',
    group: 'lab',
    description: '用 SQLGlot 校验一条 SELECT 的语法、只读性，以及表字段是否存在。',
    parameters: [
      { name: 'sql', required: true, text: '待校验的只读 SELECT' },
    ],
  },
  {
    name: 'query_db',
    label: '数据库查询',
    group: 'data',
    configurable: true,
    description: '对已配置的本地数据源执行一条只读 SELECT，返回列与数据行。模型上下文只看前 30 行。',
    parameters: [
      { name: 'sql', required: true, text: '一条完整的只读 SELECT 语句' },
    ],
  },
  {
    name: 'export_xlsx',
    label: 'xlsx导出',
    group: 'data',
    description: '把最近一次成功的 query_db 完整结果写成工作簿，并返回下载链接。',
    parameters: [
      { name: 'title', required: true, text: '问题标题，写入工作簿第一行' },
      { name: 'summary', required: false, text: '结果的简要说明' },
    ],
  },
  {
    name: 'knowledge_search',
    label: '知识检索',
    group: 'knowledge',
    description: '按语义召回业务知识、实验室文档与个人记忆。',
    parameters: [
      { name: 'query', required: true, text: '检索词：指标名、产品名、口径描述等' },
    ],
  },
  {
    name: 'bailian_recall',
    label: '百炼召回',
    group: 'knowledge',
    description: '远程知识 API。未配置时自动改走本地字段/取值召回。',
    parameters: [
      { name: 'query', required: true, text: '用户原问题全文，或某个短词' },
      { name: 'lab_type', required: true, text: '对应实验室名称，与 ask_lab 的 lab_id 相同' },
    ],
  },
  {
    name: 'field_recall',
    label: '字段召回',
    group: 'knowledge',
    description: '把用户问题匹配到已勾选表的字段名和注释。只返回字段含义。',
    parameters: [
      { name: 'query', required: true, text: '用户原问题全文，或某个短词' },
      { name: 'lab_type', required: false, text: '对应实验室名称，可选' },
    ],
  },
  {
    name: 'value_recall',
    label: '取值召回',
    group: 'knowledge',
    description: '在已勾选表上探测字段取值（DISTINCT + LIKE）。只返回候选值。',
    parameters: [
      { name: 'query', required: true, text: '用户原问题全文，或某个短词' },
      { name: 'table', required: false, text: '可选。限定一张表' },
      { name: 'column', required: false, text: '可选。限定一个字段' },
    ],
  },
  {
    name: 'knowledge_read',
    label: '知识阅读',
    group: 'knowledge',
    description: 'path 为空时列出知识目录；传相对路径时返回该文档全文。',
    parameters: [
      { name: 'path', required: false, text: '知识目录内的相对路径；留空表示列出目录' },
    ],
  },
  {
    name: 'memory_save',
    label: '知识沉淀',
    group: 'memory',
    description: '把用户声明的默认口径、偏好或指标定义持久化为可复用知识。',
    parameters: [
      { name: 'scope', required: true, text: 'personal=仅该用户；review=提交共享审核' },
      { name: 'content', required: true, text: '完整口径描述' },
    ],
  },
  {
    name: 'ask_user',
    label: '澄清',
    group: 'dialog',
    description: '问题存在口径歧义或缺少关键信息时，提出 1–3 个问题并给出选项，然后暂停循环。',
    parameters: [
      { name: 'questions', required: true, text: '1–3 个澄清问题' },
    ],
  },
  {
    name: 'update_ledger',
    label: '台账',
    group: 'dialog',
    description: '把对问题要素的理解记成一条，用户会在进度台账里实时看到。',
    parameters: [
      { name: 'key', required: true, text: '条目主体，同 key 会被覆盖' },
      { name: 'kind', required: true, text: 'term / constant / qualifier / formula / scope / time' },
      { name: 'text', required: true, text: '简短结论' },
    ],
  },
]

const DEFAULT_AGENTS = [
  {
    id: 'main',
    name: '主智能体',
    code: 'main',
    kind: 'primary',
    required: true,
    enabled: true,
    blurb: '用户对话从这里开始。勾选的工具和子智能体会出现在它的循环里。',
    toolNames: [
      'knowledge_search',
      'knowledge_read',
      'memory_save',
      'ask_user',
      'update_ledger',
      'query_db',
      'export_xlsx',
    ],
    agentNames: ['lab_sql', 'bailian'],
  },
  {
    id: 'lab_sql',
    name: '实验室智能体',
    code: 'lab_sql',
    kind: 'sub',
    required: false,
    enabled: true,
    blurb: '被主智能体当工具调用。内部自己跑一轮循环，专门生成候选 SQL。',
    toolNames: ['inspect_schema', 'generate_sql', 'validate_sql', 'knowledge_search', 'knowledge_read', 'update_ledger'],
    agentNames: [],
  },
  {
    id: 'bailian',
    name: '召回智能体',
    code: 'bailian',
    kind: 'sub',
    required: false,
    enabled: true,
    blurb: '被其他智能体当工具调用。先读表字段含义，再把用户词落到字段和取值。不出 SQL、不算数。',
    toolNames: ['inspect_schema', 'field_recall', 'value_recall', 'update_ledger'],
    agentNames: [],
  },
]

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

export function toolByName(name) {
  return TOOLS.find(item => item.name === name) || null
}

export function loadAgents() {
  const agents = clone(DEFAULT_AGENTS)
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
    if (!Array.isArray(saved)) return agents
    const byId = new Map(saved.map(item => [item.id, item]))
    for (const agent of agents) {
      const next = byId.get(agent.id)
      if (!next) continue
      if (!agent.required) agent.enabled = Boolean(next.enabled)
      if (Array.isArray(next.toolNames)) agent.toolNames = next.toolNames.filter(name => TOOLS.some(tool => tool.name === name))
      if (Array.isArray(next.agentNames)) agent.agentNames = next.agentNames.filter(id => id !== agent.id)
    }
  } catch {
    /* preview storage is best-effort */
  }
  return agents
}

export function saveAgents(agents) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(agents.map(agent => ({
    id: agent.id,
    enabled: agent.enabled,
    toolNames: agent.toolNames,
    agentNames: agent.agentNames,
  }))))
}

export function agentsUsingTool(agents, toolName) {
  return agents.filter(agent => agent.toolNames.includes(toolName))
}

export function agentsUsingAgent(agents, agentId) {
  return agents.filter(agent => agent.agentNames.includes(agentId))
}

function previewTool(partial) {
  return {
    arguments: {},
    state: 'done',
    ok: true,
    output: '',
    preview: null,
    open: false,
    kind: 'tool',
    child: null,
    ...partial,
  }
}

export function buildPreviewConversation() {
  const labChild = {
    role: 'a',
    status: 'done',
    agentName: '实验室智能体',
    elapsed: '4.8s',
    thinkOpen: true,
    thinking: { open: true, streaming: false, text: '' },
    ledger: [
      { kind: 'scope', key: 'product', text: '倍择瑞' },
      { kind: 'qualifier', key: 'channel', text: '院外 = ddi_category in (From Link Pharmacy, From DTP, From ETP)' },
    ],
    steps: [
      {
        kind: 'step',
        step: 1,
        open: true,
        thinking: {
          streaming: false,
          text: '这是一个 Actual 实验室的销量问题。先核对「院外」口径，再把原子问题交给实验室生成 SQL。',
        },
        content: '',
        tools: [
          previewTool({
            callId: 'lab-ks',
            name: 'knowledge_search',
            label: '知识检索',
            tone: 'knowledge',
            summary: '检索知识：倍择瑞 院外 口径',
            arguments: { query: '倍择瑞 院外 口径' },
            output: '命中 Actual 实验室口径：院外对应 ddi_category 的三个取值。',
          }),
        ],
        usage: { total_tokens: 612 },
      },
      {
        kind: 'step',
        step: 2,
        open: true,
        thinking: {
          streaming: false,
          text: '口径已对齐，调用 ask_lab 生成候选 SQL。',
        },
        content: '',
        tools: [
          previewTool({
            callId: 'lab-ask',
            name: 'ask_lab',
            label: '实验室',
            tone: 'lab',
            open: true,
            summary: '调用实验室 actual：倍择瑞院外今年销量',
            arguments: { question: '倍择瑞院外今年销量多少？', lab_id: 'actual' },
            output: '实验室返回 1 条候选 SQL。',
            preview: {
              lab_session_id: 'lab_session_preview_01',
              sql: "SELECT SUM(sales_val) AS sales\nFROM actual_sales\nWHERE brand = '倍择瑞'\n  AND ddi_category IN ('From Link Pharmacy', 'From DTP', 'From ETP')\n  AND year = YEAR(CURDATE())",
              candidates: [
                { candidate_no: 1, sql: "SELECT SUM(sales_val) AS sales FROM actual_sales WHERE brand = '倍择瑞' AND ddi_category IN ('From Link Pharmacy', 'From DTP', 'From ETP') AND year = YEAR(CURDATE())" },
              ],
            },
          }),
        ],
        usage: { total_tokens: 1488 },
      },
    ],
    answer: { md: '', done: true, streaming: false, draft: '', usage: null, finishReason: '' },
    clarify: null,
    clarifyHistory: [],
    failure: '',
  }

  return [
    { role: 'u', text: '倍择瑞院外今年销量多少？' },
    {
      role: 'a',
      status: 'done',
      agentName: '小英',
      elapsed: '12.4s',
      thinkOpen: true,
      keepStepsOpen: true,
      thinking: { open: true, streaming: false, text: '' },
      ledger: [
        { kind: 'scope', key: 'product', text: '倍择瑞' },
        { kind: 'time', key: 'year', text: '今年' },
        { kind: 'qualifier', key: 'channel', text: '院外' },
        { kind: 'conclusion', key: 'result', text: '院外今年销量 1,284.6 万' },
      ],
      steps: [
        {
          kind: 'step',
          step: 1,
          open: false,
          thinking: {
            streaming: false,
            text: '先拆问题：产品 = 倍择瑞，渠道 = 院外，时间 = 今年。取数 SQL 交给实验室智能体，我这边负责执行和回答。',
          },
          content: '',
          tools: [
            previewTool({
              callId: 'main-ks',
              name: 'knowledge_search',
              label: '知识检索',
              tone: 'knowledge',
              summary: '检索知识：倍择瑞 院外',
              arguments: { query: '倍择瑞 院外' },
              output: '命中产品与渠道口径说明。',
            }),
          ],
          usage: { total_tokens: 940 },
        },
        {
          kind: 'step',
          step: 2,
          open: true,
          thinking: {
            streaming: false,
            text: '口径清楚了。把原子问题委托给实验室智能体，让它内部完成 SQL 生成。',
          },
          content: '',
          tools: [
            previewTool({
              callId: 'main-lab',
              name: 'agent_lab_sql',
              label: '实验室智能体',
              tone: 'agent',
              kind: 'agent',
              summary: '委托实验室智能体：生成倍择瑞院外今年销量 SQL',
              arguments: { question: '倍择瑞院外今年销量多少？', lab_id: 'actual' },
              output: '实验室智能体返回 1 条候选 SQL，口径已覆盖院外。',
              preview: {
                sql: "SELECT SUM(sales_val) AS sales\nFROM actual_sales\nWHERE brand = '倍择瑞'\n  AND ddi_category IN ('From Link Pharmacy', 'From DTP', 'From ETP')\n  AND year = YEAR(CURDATE())",
              },
              open: true,
              child: labChild,
            }),
          ],
          usage: { total_tokens: 2210 },
        },
        {
          kind: 'step',
          step: 3,
          open: false,
          thinking: {
            streaming: false,
            text: '候选 SQL 已核验，执行查询后给出答案。',
          },
          content: '',
          tools: [
            previewTool({
              callId: 'main-sql',
              name: 'query_db',
              label: '查询',
              tone: 'sql',
              summary: '执行只读 SQL 查询',
              arguments: { sql: "SELECT SUM(sales_val) AS sales FROM actual_sales WHERE brand = '倍择瑞'" },
              output: '查询成功，共 1 行。',
              preview: {
                columns: ['sales'],
                rows: [['1284.6']],
                row_count: 1,
                sql: "SELECT SUM(sales_val) AS sales FROM actual_sales WHERE brand = '倍择瑞' AND ddi_category IN ('From Link Pharmacy', 'From DTP', 'From ETP') AND year = YEAR(CURDATE())",
              },
            }),
          ],
          usage: { total_tokens: 1680 },
        },
      ],
      answer: {
        md: '倍择瑞院外今年销量为 **1,284.6 万**（Actual，院外三个渠道合计）。',
        done: true,
        streaming: false,
        draft: '',
        usage: { total_tokens: 6120 },
        finishReason: 'stop',
      },
      clarify: null,
      clarifyHistory: [],
      failure: '',
    },
  ]
}
