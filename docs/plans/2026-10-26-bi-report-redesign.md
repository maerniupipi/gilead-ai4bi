# 洞察链路统一与交互报告实施计划

目标：洞察与查数共用 AgentRunService，仅由系统提示词改变分析深度；用 DDI 分析和 HTML 模板技能生成可筛选、可继续修改的正式商务报告。

架构：移除 application/insight 的 DAG、子 Run、专用澄清和沉淀接口。保留 normal/insight 模式及历史数据库列以兼容已存会话；新任务统一走 durable job → AgentRunService。新增通用 render_report 工具，直接读取已核验 query_db 数据并保存带版本的报告 artifact。报告前端与 HTML 下载共用一份本地渲染模板，不执行模型提供的任意 HTML。

1. 修改 bootstrap/jobs.py、bootstrap/container.py、agent_run/loop.py，统一执行、恢复和提示词加载，移除专用洞察实现及对应失效测试。
2. 在 modules/skill_packs/templates 中创建 DDI分析、html模板 SKILL.md，幂等预置到技能目录；DDI 固化按日/月/季/年、数量/金额、达成与同比环比以及六表关联规则。
3. 新增 agent_run/report_tool.py：查询数据不经模型重抄；支持原报告样式与字段补丁、同会话复用数据、缺字段时明确要求补查，保存来源和修订号。
4. 新增前端 reports/template.js、ReportFrame.vue，统一筛选、指标重算、趋势、目标达成、贡献图、可排序明细、字段显示、HTML/CSV 导出和追问上下文。移除旧 insight.node UI。
5. 生成并装载可复现的数仓样例数据，在真实业务对话中验证，涵盖查数→下钻→DDI→筛选→自然语言修改，以及非 DDI 洞察。标明模拟数据，独立于共享业务库。
6. 改为深蓝白色商务主题、几何 BI 标识、正式首页与导航，兼容现有自定义品牌设置并迁移旧默认形象。
7. 验证：后端路由/工具/恢复/权限回归，前端单测与构建，浏览器验证筛选数字联动、字段增加、导出、刷新、窄屏和空数据；保存演示 HTML 与说明。

验收口径：比率均由汇总后分子/分母计算；无历史值不得伪造同比；DDI金额遵循 CNY=数量×price_latest、USD=数量×asp_price；月销售不得混加 Daily/Monthly；筛选仅缩小当前授权返回数据范围。样例数据在来源处标识；所有操作使用真实业务对话和查询链路。
