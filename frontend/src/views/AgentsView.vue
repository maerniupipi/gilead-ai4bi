<script setup>
import NavIcon from '../components/NavIcon.vue'
</script>
<template><main class="agent-page"><h1>问数助手</h1><article><NavIcon name="agent"/><div><h2>主智能体</h2><p>将复杂问题拆成可独立取数的原子问题，在平台生成的 SQL 上筛选、比较和汇总，再根据查询结果回答。</p></div></article>
<section><div><h3>知识检索与阅读</h3><p>检索应用知识库里的业务定义和规则，阅读匹配章节并引用原文。</p><code>knowledge_search · knowledge_read</code><br><router-link to="/admin/knowledge">打开知识库</router-link></div>
<div><h3>召回实验室</h3><p>匹配数据库字段、实际取值和别名。</p><code>recall_lab</code></div>
<div><h3>生成 SQL 实验室</h3><p>按平台维护的业务口径，为每个原子问题生成只读 PostgreSQL 查询。</p><code>generate_sql</code></div></section>
<router-link to="/lab-connection">配置实验室连接</router-link></main></template>
<style scoped>.agent-page{padding:32px;max-width:900px;color:var(--ink)}h1{margin:0 0 24px}article,section>div{background:white;padding:20px;border:1px solid var(--line);border-radius:14px}article{display:flex;gap:16px;align-items:center}article svg{width:30px;height:30px;color:var(--accent)}h2,h3{margin:0;font-size:17px}p{color:var(--ink-2);font-size:14px}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:16px 0}code{font-size:12px;color:var(--accent)}a{color:var(--accent)}</style>
