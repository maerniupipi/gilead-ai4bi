<script setup>
import { computed, ref, watch } from 'vue'
import ToolCard from './ToolCard.vue'
import SubAgentMark from './SubAgentMark.vue'

const props = defineProps({
  msg: { type: Object, required: true },
  nested: { type: Boolean, default: false },
  agentName: { type: String, default: '' },
})

const TERMINAL = ['done', 'completed', 'partial', 'failed', 'client_cancelled']
const open = computed(() => {
  if (props.msg.thinkOpen != null) return props.msg.thinkOpen
  return !TERMINAL.includes(props.msg.status)
})
function toggle() { props.msg.thinkOpen = !open.value }

const steps = computed(() => props.msg.steps || [])
const ledger = computed(() => props.msg.ledger || [])
const durableLedger = computed(() =>
  ledger.value.filter(entry => entry.kind === 'scope' || entry.kind === 'time')
)
const processLedger = computed(() =>
  ledger.value.filter(entry => entry.kind !== 'scope' && entry.kind !== 'time')
)
const LEDGER_TAGS = {
  caliber: '时间',
  term: '术语',
  constant: '常量',
  qualifier: '限定',
  formula: '公式',
  scope: '已确认',
  time: '时间事实',
  fact: '事实',
  conclusion: '结论',
}

// The step trail stays open while 小英 is thinking; once the run lands it
// folds into one compact "思考过程" group the user can reopen any time.
const stepsOpen = ref(props.nested || Boolean(props.msg.keepStepsOpen) || !TERMINAL.includes(props.msg.status))
const processOpen = ref(props.nested || Boolean(props.msg.keepStepsOpen) || !TERMINAL.includes(props.msg.status))
watch(() => props.msg.status, (status) => {
  if (TERMINAL.includes(status) && !props.msg.keepStepsOpen && !props.nested) {
    stepsOpen.value = false
    processOpen.value = false
  } else {
    stepsOpen.value = true
    processOpen.value = true
  }
})
const streaming = computed(() => {
  if (props.msg.thinking?.streaming) return true
  return steps.value.some(step => step.thinking?.streaming || step.tools?.some(tool => (
    tool.state === 'running' || tool.child?.status === 'running'
  )))
})

const title = computed(() => props.agentName || props.msg.agentName || '助手')

const headText = computed(() => {
  if (props.msg.status === 'waiting_clarification') return '等你确认一下'
  if (['failed', 'client_cancelled'].includes(props.msg.status)) return props.msg.status === 'failed' ? '执行失败' : '已停止接收'
  if (['done', 'completed', 'partial'].includes(props.msg.status)) return `想好了 · ${steps.value.length} 步`
  return streaming.value ? `自己想一想 · ${props.msg.elapsed || '…'}` : `想了 ${steps.value.length} 步`
})

function toggleStep(step) { step.open = !step.open }

function stepToolItems(step) {
  const seen = new Set()
  const items = []
  for (const tool of step.tools || []) {
    if (!tool.label || seen.has(tool.label)) continue
    seen.add(tool.label)
    items.push({
      label: tool.label,
      agent: tool.kind === 'agent' || tool.tone === 'agent',
    })
  }
  return items
}
</script>

<template>
  <section v-if="steps.length || msg.thinking?.text" class="trace" :class="{ nested }">
    <button class="trace-h" type="button" @click="toggle">
      <span class="pulse-dot" :class="{ live: streaming }"></span>
      {{ title }}
      <span v-if="nested" class="agent-kind"><SubAgentMark />子智能体</span>
      <span class="dur">{{ headText }}</span>
      <span class="chev">{{ open ? '收起 −' : '展开 +' }}</span>
    </button>
    <div v-show="open" class="trace-b">
      <div v-if="msg.thinking?.text && !steps.length" class="think-chunk">
        <pre>{{ msg.thinking.text }}</pre>
      </div>
      <div v-if="steps.length" class="steps-group">
        <button v-if="!nested" class="steps-h" type="button" @click="stepsOpen = !stepsOpen">
          <span class="steps-title">思考过程</span>
          <span class="step-detail">{{ steps.length }} 步</span>
          <span class="step-chev">{{ stepsOpen ? '−' : '+' }}</span>
        </button>
        <div v-show="nested || stepsOpen">
        <div v-for="step in steps" :key="step.step || 'x'" class="step-block">
        <button class="step-row" type="button" @click="toggleStep(step)">
          <span class="step-tag">第 {{ step.step || '·' }} 步</span>
          <span class="step-title">
            <template v-if="step.tools?.length">{{ step.tools.length }} 次工具调用</template>
            <template v-else-if="step.content">模型回应</template>
            <template v-else>深度思考</template>
          </span>
          <span v-if="stepToolItems(step).length" class="step-tools">
            <i v-for="tag in stepToolItems(step)" :key="tag.label" :class="{ agent: tag.agent }">
              <SubAgentMark v-if="tag.agent" />{{ tag.label }}
            </i>
          </span>
          <span v-if="step.usage" class="step-detail">tokens {{ step.usage.total_tokens ?? '—' }}</span>
          <span class="step-chev">{{ step.open ? '−' : '+' }}</span>
        </button>
        <div v-if="step.open" class="step-body">
          <div v-if="step.thinking?.text" class="think-chunk">
            <b>思考</b>
            <pre>{{ step.thinking.text }}<span v-if="step.thinking.streaming" class="caret"></span></pre>
          </div>
          <ToolCard v-for="tool in step.tools" :key="tool.callId" :tool="tool" />
          <p v-if="step.content" class="step-content">{{ step.content }}</p>
        </div>
      </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.trace {
  background: #f6f3f4;
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 0 14px;
}
.trace.nested {
  background: #f3f8f8;
  border-left: 2px solid var(--cyan);
  margin: 2px 0 4px;
  padding: 0 12px;
}
.trace.nested .trace-h { color: #245e61; }
.trace.nested .dur { color: #5a8f91; }
.trace.nested .trace-h:hover .dur,
.trace.nested .trace-h:hover .chev { color: #2d7a7c; }
.agent-kind {
  align-items: center;
  background: rgba(76, 166, 168, .16);
  border-radius: 4px;
  color: #2d7a7c;
  display: inline-flex;
  font: 700 9px var(--mono-font);
  gap: 4px;
  letter-spacing: .08em;
  padding: 1px 6px 1px 4px;
}
.trace-h {
  align-items: center;
  background: transparent;
  border: 0;
  color: var(--ink);
  cursor: pointer;
  display: flex;
  font-size: 12.5px;
  font-weight: 650;
  gap: 8px;
  justify-content: flex-start;
  min-height: 40px;
  min-width: 0;
  padding: 0;
  text-align: left;
  white-space: nowrap;
  width: 100%;
}
.trace-h:hover .dur, .trace-h:hover .chev { color: var(--accent); }
.trace-h:focus-visible { border-radius: 8px; outline: 2px solid color-mix(in srgb, var(--accent) 45%, transparent); outline-offset: 2px; }
.pulse-dot { background: var(--ink-3); border-radius: 50%; flex: 0 0 7px; height: 7px; width: 7px; }
.pulse-dot.live { animation: tracePulse 1.1s ease-in-out infinite; background: var(--accent); }
@keyframes tracePulse { 50% { opacity: .3; transform: scale(.75); } }
.dur { color: var(--ink-2); flex: 0 1 auto; font-size: 13px; font-weight: 500; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.chev { color: var(--ink-3); flex: 0 0 auto; flex-shrink: 0; font-size: 12px; font-weight: 600; margin-left: auto; }
.trace-b { border-top: 1px dashed var(--line); padding: 8px 0 10px; }
.ledger { background: var(--surface); border: 1px solid var(--line); border-left: 2px solid var(--accent); border-radius: 12px; margin: 4px 0 8px; padding: 8px 10px; }
.ledger > b { color: var(--ink-3); display: block; font: 700 9px var(--mono-font); letter-spacing: .12em; margin-bottom: 4px; }
.ledger ul { list-style: none; margin: 0; padding: 0; }
.ledger li { color: var(--ink-2); font-size: 12px; line-height: 1.7; padding: 1px 0; word-break: break-word; }
.ledger-tag { border-radius: 4px; display: inline-block; font: 700 9px var(--mono-font); letter-spacing: .08em; margin-right: 6px; padding: 1px 5px; vertical-align: 1px; }
.ledger li[data-kind="caliber"] .ledger-tag { background: var(--accent-soft); color: var(--accent); }
.ledger li[data-kind="term"] .ledger-tag { background: var(--accent-soft); color: var(--accent); }
.ledger li[data-kind="constant"] .ledger-tag { background: rgba(37, 99, 235, .12); color: #1d4ed8; }
.ledger li[data-kind="qualifier"] .ledger-tag { background: rgba(217, 119, 6, .14); color: #b45309; }
.ledger li[data-kind="formula"] .ledger-tag { background: rgba(124, 58, 237, .12); color: #6d28d9; }
.ledger li[data-kind="time"] .ledger-tag { background: rgba(14, 116, 144, .14); color: #0e7490; }
.ledger li[data-kind="scope"] .ledger-tag { background: rgba(16, 122, 87, .12); color: #0e7a53; }
.ledger li[data-kind="fact"] .ledger-tag { background: rgba(120, 113, 108, .14); color: var(--ink-2); }
.ledger-process { margin-top: 6px; }
.ledger-process-h { align-items: center; background: transparent; border: 0; color: var(--ink-3); cursor: pointer; display: flex; font: 700 9px var(--mono-font); gap: 6px; letter-spacing: .08em; padding: 2px 0; width: 100%; }
.ledger-process-h span { margin-left: auto; }
.ledger li[data-kind="conclusion"] .ledger-tag { background: rgba(120, 113, 108, .14); color: var(--ink-2); }
.ledger-process { margin-top: 6px; }
.ledger-process-h { align-items: center; background: transparent; border: 0; color: var(--ink-3); cursor: pointer; display: flex; font: 700 9px var(--mono-font); gap: 6px; letter-spacing: .08em; padding: 2px 0; width: 100%; }
.ledger-process-h span { margin-left: auto; }
.step-block { margin: 8px 0; }
.steps-group { margin: 4px 0; }
.steps-h { align-items: baseline; background: transparent; border: 0; cursor: pointer; display: flex; gap: 8px; padding: 4px 0; text-align: left; width: 100%; }
.steps-title { color: var(--ink); font-size: 12px; font-weight: 700; }
.step-row { align-items: baseline; background: transparent; border: 0; cursor: pointer; display: flex; gap: 8px; padding: 3px 0; text-align: left; width: 100%; }
.step-tag { color: var(--accent); font-size: 11px; font-weight: 650; }
.step-title { color: var(--ink); font-size: 12px; font-weight: 650; }
.step-tools { display: inline-flex; flex-wrap: wrap; gap: 4px; }
.step-tools i {
  align-items: center;
  background: var(--accent-soft); border-radius: 5px; color: var(--accent);
  display: inline-flex; font: 600 9px var(--mono-font); font-style: normal; gap: 3px; padding: 1px 6px;
}
.step-tools i.agent {
  background: rgba(76, 166, 168, .16);
  color: #2d7a7c;
}
.step-detail { color: var(--ink-3); font: 500 10px var(--mono-font); }
.step-chev { color: var(--ink-3); font: 700 12px var(--mono-font); margin-left: auto; }
.step-body { padding: 2px 0 4px 2px; }
.think-chunk { margin: 4px 0; }
.think-chunk > b { color: var(--ink-3); display: block; font: 700 9px var(--mono-font); letter-spacing: .12em; margin-bottom: 3px; }
.think-chunk pre { background: var(--surface); border: 1px solid var(--line); border-left: 2px solid var(--accent-soft); border-radius: 12px; color: var(--ink-2); font-size: 12px; line-height: 1.7; margin: 0; max-height: 300px; overflow: auto; padding: 8px 10px; white-space: pre-wrap; word-break: break-word; }
.step-content { color: var(--ink); font-size: 13px; line-height: 1.7; margin: 6px 0 2px; white-space: pre-wrap; }
.caret { animation: caretBlink 1s steps(1) infinite; background: var(--accent); display: inline-block; height: 12px; width: 6px; }
@keyframes caretBlink { 50% { opacity: 0; } }
</style>
