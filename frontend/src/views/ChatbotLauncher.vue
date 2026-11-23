<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import ChatbotMark from '../components/ChatbotMark.vue'
import { chooseChatbot, currentChatbot, loadChatbots, logout, showToast, store } from '../store.js'

const router = useRouter()
const search = ref('')
const entering = ref('')
const current = computed(currentChatbot)
const filtered = computed(() => store.chatbots.filter(bot => `${bot.name} ${bot.description}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const categories = { ddi: '商业智能', behavior: '用户行为', general: '业务分析' }
const labCount = bot => bot.lab_ids?.length ?? bot.lab_count ?? 0
const bookCount = bot => bot.workbook_ids?.length ?? bot.workbook_count ?? 0

async function enter(bot) {
  if (entering.value) return
  entering.value = bot.id
  try {
    if (await chooseChatbot(bot.id)) await router.push('/')
  } catch (error) { showToast(error.message) }
  finally { entering.value = '' }
}
function manage() {
  store.chatbotChooserOpen = false
  void router.push('/chatbots')
}
</script>

<template>
  <main class="launcher">
    <header class="launcher-nav">
      <div class="launcher-brand"><img :src="store.branding.logo_url || '/brand/gilead-bi.svg'" alt="Gilead BI" /><span><b>{{ store.branding.character_name || 'Gilead BI' }}</b><small>智能业务工作台</small></span></div>
      <div class="launcher-actions">
        <span v-if="store.token" class="launcher-person">{{ store.user?.display_name || store.user?.username }}</span>
        <button v-if="store.token" class="launcher-link" @click="store.chatbotChooserOpen=false; router.push('/workspace')">看板 <span>↗</span></button>
        <button v-if="store.user?.role === 'admin'" class="launcher-link" @click="manage">管理 Chatbot <span>↗</span></button>
        <button v-if="store.token" class="launcher-link quiet" @click="logout">退出登录</button>
        <button v-else class="launcher-link" @click="store.pendingChatbotId = ''; store.loginOpen = true">账号登录 <span>↗</span></button>
      </div>
    </header>

    <div class="launcher-content">
      <div class="launcher-intro">
        <div class="launcher-kicker"><span></span> GILEAD INTELLIGENCE</div>
        <h1>选择你的<span>业务助手</span></h1>
        <p>从一个问题开始，让数据成为下一步行动的依据。</p>
      </div>
      <div class="launcher-toolbar"><span>业务空间 <b>{{ store.chatbots.length.toString().padStart(2, '0') }}</b></span><label class="bot-search"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></svg><input v-model="search" aria-label="搜索 Chatbot" placeholder="搜索业务助手" /></label></div>
      <div v-if="store.chatbotError" class="launcher-empty" role="alert"><p>{{ store.chatbotError }}</p><button class="btn-p" @click="loadChatbots">重新加载</button></div>
      <div v-else-if="store.chatbotLoading && !store.chatbots.length" class="launcher-empty">正在准备业务助手…</div>
      <div v-else class="launcher-grid">
        <button v-for="(bot, index) in filtered" :key="bot.id" class="launcher-card" :class="bot.category" :style="{ '--card-order': index }" :disabled="Boolean(entering)" :aria-label="`进入${bot.name}`" @click="enter(bot)">
          <div class="bot-card-top"><ChatbotMark :category="bot.category" /><span class="bot-type">{{ categories[bot.category] || '业务分析' }}</span></div>
          <h2>{{ bot.name }}</h2><p>{{ bot.description }}</p>
          <div class="bot-card-graphic" aria-hidden="true">
            <template v-if="bot.category === 'behavior'"><div class="funnel-row"><span>访问</span><i style="--bar:100%"></i></div><div class="funnel-row"><span>活跃</span><i style="--bar:76%"></i></div><div class="funnel-row"><span>转化</span><i style="--bar:43%"></i></div><span class="graphic-note">理解路径 · 发现机会</span></template>
            <template v-else><div class="spark-label"><span>从趋势到归因</span><span>↗</span></div><svg viewBox="0 0 400 75" preserveAspectRatio="none"><path d="M0 67H400M0 34H400" class="spark-grid" /><path d="M0 64 45 51 90 57 135 28 180 36 225 18 270 25 315 9 360 17 400 3" class="spark-line" /><path d="m0 67 45-11 45 7 45-23 45 7 45-18 45 10 45-13 45 3 40-10" class="spark-baseline" /></svg><div class="graphic-bottom"><span>问数</span></div></template>
          </div>
          <div class="bot-card-source"><span class="source-dot"></span>{{ labCount(bot) ? `${labCount(bot)} 个实验室` : 'XLSX 工作簿' }}<span v-if="bookCount(bot) && labCount(bot)">＋ {{ bookCount(bot) }} 个工作簿</span><small v-if="bot.sample">样例数据</small></div>
          <div class="bot-card-foot"><span>{{ entering === bot.id ? '正在进入…' : '进入 Chatbot' }}</span><span class="bot-card-arrow">↗</span></div>
        </button>
      </div>
      <div v-if="!filtered.length && !store.chatbotLoading && !store.chatbotError" class="launcher-empty">{{ search ? '没有匹配的业务助手，换个关键词试试。' : '当前账号还没有可用助手，请联系管理员开放权限。' }}</div>
      <div class="launcher-bottom"><span><svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m10 2 6 2v5c0 4-6 8-6 8S4 13 4 9V4l6-2Z" /><path d="m7 9 2 2 4-4" /></svg>{{ store.token ? '仅显示当前账号可用的业务助手' : '选择业务助手后，登录你的账号' }}</span><button v-if="current" class="launcher-link" @click="store.chatbotChooserOpen = false">返回 {{ current.name }} →</button></div>
    </div>
    <footer class="launcher-footer"><span>GILEAD · BUSINESS INTELLIGENCE</span><span>以数据，支持每一个业务决定</span></footer>
  </main>
</template>

<style scoped>
.launcher{height:100dvh;overflow:auto;background:radial-gradient(ellipse at 8% 5%,#f9e9ed66,transparent 38%),radial-gradient(ellipse at 94% 95%,#e7edf666,transparent 38%),#f6f6f8;color:#292b34;padding:0 5vw;box-sizing:border-box;display:flex;flex-direction:column}.launcher *{box-sizing:border-box}.launcher-nav{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:28px 0;border-bottom:1px solid #e5e5eaaa}.launcher-brand{display:flex;align-items:center;gap:12px}.launcher-brand img{width:41px;height:41px;border-radius:13px}.launcher-brand b{font-size:18px;letter-spacing:-.5px;display:block}.launcher-brand small{display:block;color:#85858f;font-size:11px;margin-top:3px;letter-spacing:1px}.launcher-actions{display:flex;align-items:center;gap:24px}.launcher-person{color:#676974;font-size:12px}.launcher-link{background:transparent;border:0;font-size:12px;color:#a31b35;cursor:pointer;padding:9px 0;display:inline-flex;align-items:center;gap:10px}.launcher-link.quiet{color:#858590}.launcher-content{max-width:1020px;width:100%;margin:auto;flex:1;padding:60px 0 30px}.launcher-intro{margin-bottom:48px}.launcher-kicker{display:flex;align-items:center;gap:8px;font-size:10px;font-weight:700;letter-spacing:2.5px;color:#8d8490;margin-bottom:20px}.launcher-kicker span{width:6px;height:6px;background:#c5203f;border-radius:50%;box-shadow:0 0 0 4px #f6e2e7}.launcher-intro h1{font-size:40px;font-weight:650;letter-spacing:-1.8px;margin:0 0 16px;line-height:1.25}.launcher-intro h1 span{color:#bb203d;margin-left:5px}.launcher-intro p{margin:0;color:#81818c;font-size:14px;letter-spacing:.2px}.launcher-toolbar{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:18px;color:#72737d;font-size:12px}.launcher-toolbar b{font-size:10px;font-weight:500;margin-left:8px;color:#aaaab2}.bot-search{display:flex;align-items:center;gap:9px;background:#ffffffa6;border:1px solid #e4e4e9;border-radius:11px;padding:8px 12px}.bot-search svg{width:14px;height:14px;stroke:#96969e;stroke-width:1.7}.bot-search input{font-size:11px;border:0;background:transparent;width:155px;outline:0;color:#444653}.bot-search:focus-within{outline:2px solid #c5203f55}.launcher-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}.launcher-card{font:inherit;text-align:left;border:1px solid #e5e4e9;border-radius:24px;background:#fff;box-shadow:0 4px 8px #2a243b03,0 20px 40px #2a243b03;padding:28px;cursor:pointer;display:flex;flex-direction:column;min-width:0;position:relative;transition:transform .25s,box-shadow .25s,border-color .25s;animation:bot-appear .5s both;animation-delay:calc(var(--card-order)*65ms)}.launcher-card:hover{transform:translateY(-5px);box-shadow:0 18px 44px #34253510;border-color:#dfc6ce}.launcher-card:focus-visible{outline:3px solid #c5203f66;outline-offset:4px}.bot-card-top{display:flex;align-items:center;justify-content:space-between}.bot-type{background:#f6f5f8;border:1px solid #ededf1;color:#8a8792;font-size:10px;padding:5px 9px;border-radius:7px}.launcher-card h2{font-size:23px;letter-spacing:-.6px;font-weight:650;margin:24px 0 11px}.launcher-card>p{font-size:12px;color:#84828d;line-height:1.9;margin:0;min-height:46px;max-width:345px}.bot-card-graphic{margin:25px 0 23px;min-height:136px;background:linear-gradient(135deg,#fbf8f9,#fafafb);border:1px solid #f3edf0;border-radius:13px;padding:14px 16px;color:#9d626f}.spark-label{display:flex;align-items:center;justify-content:space-between;font-size:9px;color:#9d8490;margin-bottom:8px}.bot-card-graphic svg{width:100%;height:65px;overflow:visible}.spark-grid{stroke:#ede7eb;stroke-width:1;stroke-dasharray:3 5;fill:none}.spark-line{stroke:#c5203f;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;fill:none;stroke-dasharray:700;animation:bot-draw 1.5s both}.spark-baseline{stroke:#d6b5bf;stroke-width:1.4;stroke-dasharray:4 5;fill:none}.graphic-bottom{display:flex;justify-content:space-between;font-size:9px;color:#aa96a0;margin-top:7px}.behavior .bot-card-graphic{background:linear-gradient(135deg,#f4f9fa,#f8fafb);border-color:#e8eff1;padding:16px}.funnel-row{display:flex;align-items:center;gap:14px;height:25px;font-size:9px;color:#7c9298}.funnel-row span{width:25px;flex:none}.funnel-row i{display:block;max-width:calc(100% - 45px);height:10px;width:var(--bar);border-radius:3px;background:#82b7c3}.funnel-row:nth-child(2) i{background:#4b93a5}.funnel-row:nth-child(3) i{background:#246b7d}.graphic-note{display:block;font-size:9px;color:#9aabb0;margin-top:12px;text-align:right}.bot-card-source{display:flex;align-items:center;gap:7px;font-size:10px;color:#98939d;margin-bottom:22px;flex-wrap:wrap}.source-dot{height:5px;width:5px;border-radius:50%;background:#8ca99d}.bot-card-source small{margin-left:auto;font-size:9px;border:1px solid #ece9ee;padding:3px 5px;border-radius:4px;color:#a39aa6}.bot-card-foot{display:flex;justify-content:space-between;align-items:center;padding-top:17px;border-top:1px solid #f0edf1;color:#aa1b37;font-size:12px;font-weight:600;margin-top:auto}.bot-card-arrow{height:27px;width:27px;background:#fbedf0;border-radius:9px;display:grid;place-items:center;font-size:17px}.behavior .bot-card-foot{color:#276d7c}.behavior .bot-card-arrow{background:#edf5f7}.launcher-bottom{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-top:22px;font-size:10px;color:#a2a0aa}.launcher-bottom>span{display:flex;align-items:center;gap:7px}.launcher-bottom svg{height:14px;width:14px;stroke:#9e9ba7;stroke-width:1.2}.launcher-footer{font-size:9px;color:#b1adb7;letter-spacing:1.3px;padding:24px 0;display:flex;justify-content:space-between;border-top:1px solid #e9e7ed}.launcher-empty{padding:45px 20px;text-align:center;font-size:13px;color:#85828e}.launcher-empty .btn-p{margin-top:15px}@keyframes bot-appear{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}@keyframes bot-draw{from{stroke-dashoffset:700}to{stroke-dashoffset:0}}@media(max-width:680px){.launcher{padding:0 24px}.launcher-nav{padding:23px 0}.launcher-actions{gap:12px}.launcher-person,.launcher-footer span:last-child{display:none}.launcher-content{padding:40px 0 25px}.launcher-intro{margin-bottom:32px}.launcher-intro h1{font-size:30px;letter-spacing:-1.3px}.launcher-intro p{font-size:12px;line-height:1.8;max-width:265px}.launcher-grid{grid-template-columns:1fr;gap:18px}.launcher-card{padding:24px}.bot-search input{width:105px}.launcher-bottom{flex-wrap:wrap}.launcher-link{font-size:10px}.launcher-brand b{font-size:16px}.launcher-brand small{font-size:9px}.launcher-footer{font-size:8px}}@media(prefers-reduced-motion:reduce){.launcher-card,.spark-line{animation:none;transition:none}}
</style>
