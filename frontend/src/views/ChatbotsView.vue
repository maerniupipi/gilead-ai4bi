<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/backend.js'
import ChatbotMark from '../components/ChatbotMark.vue'
import NavIcon from '../components/NavIcon.vue'
import { chooseChatbot, loadChatbots, openChatbotChooser, showToast, store } from '../store.js'

const router = useRouter()
const bots = ref([])
const labs = ref([])
const users = ref([])
const search = ref('')
const loading = ref(true)
const loadError = ref('')
const editorOpen = ref(false)
const editingId = ref('')
const saving = ref(false)
const uploading = ref(false)
const formError = ref('')
const fileInput = ref(null)
const editor = ref(null)
const nameInput = ref(null)
const form = reactive(emptyForm())
const roles = [{ id: 'user', name: '业务用户' }, { id: 'admin', name: '管理员' }, { id: 'knowledge_reviewer', name: '知识审核员' }, { id: 'data_source_admin', name: '数据源管理员' }]
let returnFocus = null

function emptyForm() {
  return { name: '', description: '', category: 'general', enabled: true, access: 'all', roles: [], user_ids: [], lab_ids: [], workbook_ids: [], workbooks: [], sample: false }
}
const filtered = computed(() => bots.value.filter(bot => `${bot.name} ${bot.description}`.toLowerCase().includes(search.value.toLowerCase())))
const workbookCount = computed(() => new Set(bots.value.flatMap(bot => bot.workbook_ids)).size)
const enabledCount = computed(() => bots.value.filter(bot => bot.enabled).length)
const selectedPeople = computed(() => form.access === 'users' ? `${form.user_ids.length} 个账号` : form.access === 'roles' ? `${form.roles.length} 类角色` : '所有已登录用户')

function accessLabel(bot) {
  return bot.access === 'all' ? '所有用户' : bot.access === 'roles' ? `${bot.roles.length} 类角色` : `${bot.user_ids.length} 个账号`
}
async function reload() {
  loading.value = true
  loadError.value = ''
  try {
    const [items, documents, accounts] = await Promise.all([api.adminChatbots(), api.labPairs(), api.users()])
    bots.value = items
    labs.value = documents.pairs.map(pair => ({ lab_id: pair.id, name: pair.name, blurb: '召回实验室 + SQL 实验室' }))
    users.value = (accounts.items || []).filter(user => user.is_active)
  } catch (error) { loadError.value = error.message }
  finally { loading.value = false }
}
async function edit(bot = null) {
  returnFocus = document.activeElement
  editingId.value = bot?.id || ''
  Object.assign(form, emptyForm(), bot ? JSON.parse(JSON.stringify(bot)) : {})
  formError.value = ''
  editorOpen.value = true
  await nextTick()
  nameInput.value?.focus()
}
function close() {
  if (saving.value || uploading.value) return
  editorOpen.value = false
  returnFocus?.focus?.()
}
function onKey(event) {
  if (!editorOpen.value) return
  if (event.key === 'Escape') { event.preventDefault(); close() }
  if (event.key !== 'Tab') return
  const elements = [...(editor.value?.querySelectorAll('button:not(:disabled), input:not(:disabled):not([type=hidden]), select, textarea, summary, [tabindex="0"]') || [])].filter(el => el.offsetParent !== null)
  const first = elements[0], last = elements.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
async function upload(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  if (!files.length) return
  if (form.workbook_ids.length + files.length > 10) { formError.value = '每个 Chatbot 最多绑定 10 个工作簿'; return }
  uploading.value = true
  formError.value = ''
  try {
    for (const file of files) {
      if (!file.name.toLowerCase().endsWith('.xlsx')) throw new Error('请上传 .xlsx 格式的工作簿')
      if (file.size > 10 * 1024 * 1024) throw new Error('单个文件不能超过 10 MB')
      const workbook = await api.uploadChatbotWorkbook(file)
      form.workbook_ids.push(workbook.id)
      form.workbooks.push(workbook)
    }
  } catch (error) { formError.value = error.message }
  finally { uploading.value = false }
}
function removeBook(id) {
  form.workbook_ids = form.workbook_ids.filter(value => value !== id)
  form.workbooks = form.workbooks.filter(value => value.id !== id)
}
async function save() {
  if (saving.value || uploading.value) return
  formError.value = ''
  if (form.enabled && !form.lab_ids.length && !form.workbook_ids.length) { formError.value = '请选择实验室或上传 XLSX 工作簿'; return }
  if (form.access === 'roles' && !form.roles.length) { formError.value = '请选择至少一个开放角色'; return }
  if (form.access === 'users' && !form.user_ids.length) { formError.value = '请选择至少一个开放账号'; return }
  saving.value = true
  try {
    const body = Object.fromEntries(Object.keys(emptyForm()).filter(key => key !== 'workbooks').map(key => [key, form[key]]))
    if (editingId.value) await api.updateChatbot(editingId.value, body)
    else await api.createChatbot(body)
    showToast(editingId.value ? 'Chatbot 配置已保存' : 'Chatbot 已创建，可在业务入口选择')
    editorOpen.value = false
    await Promise.all([reload(), loadChatbots()])
    returnFocus?.focus?.()
  } catch (error) { formError.value = error.message }
  finally { saving.value = false }
}
async function enter(bot) {
  try { await loadChatbots(); if (await chooseChatbot(bot.id)) await router.push('/') }
  catch (error) { showToast(error.message) }
}

onMounted(() => { void reload(); document.addEventListener('keydown', onKey) })
onUnmounted(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="page-shell wide-page chatbot-admin">
    <header class="chatbots-head"><div><div class="eyebrow">WORKSPACE / 管理</div><h1>Chatbot 管理<span>业务助手，为不同团队而建</span></h1><p>为每个业务场景配置独立入口、使用对象和数据来源。</p></div><button class="btn-p" @click="edit()"><NavIcon name="plus" />新建 Chatbot</button></header>
    <section class="bot-overview" aria-label="Chatbot 概览"><div><span>业务助手</span><b>{{ bots.length.toString().padStart(2, '0') }}</b></div><div><span>已启用</span><b>{{ enabledCount.toString().padStart(2, '0') }}<i class="overview-dot"></i></b></div><div><span>已绑定工作簿</span><b>{{ workbookCount.toString().padStart(2, '0') }}</b></div><button @click="openChatbotChooser">查看业务入口 <span>↗</span></button></section>
    <div class="bot-list-toolbar"><h2>全部 Chatbot <span>{{ bots.length }}</span></h2><input v-model="search" class="bot-search-input" aria-label="搜索 Chatbot 配置" placeholder="搜索名称或用途…" /></div>
    <div v-if="loadError" class="admin-empty" role="alert">{{ loadError }} <button class="btn-text" @click="reload">重试</button></div>
    <div v-else-if="loading && !bots.length" class="admin-empty">正在加载配置…</div>
    <div v-else class="admin-bot-grid">
      <article v-for="bot in filtered" :key="bot.id" class="admin-bot-card" :class="{ disabled: !bot.enabled }">
        <div class="admin-bot-top"><ChatbotMark :category="bot.category" /><span class="bot-status" :class="{ enabled: bot.enabled }"><i></i>{{ bot.enabled ? '已启用' : '已停用' }}</span></div>
        <h3>{{ bot.name }}<span v-if="store.chatbotId === bot.id" class="current-bot">当前</span></h3><p class="bot-description">{{ bot.description || '尚未填写业务简介' }}</p>
        <div class="bot-facts"><div><NavIcon name="users" /><span>开放对象</span><b>{{ accessLabel(bot) }}</b></div><div><NavIcon name="lab" /><span>实验室</span><b>{{ bot.lab_ids.length ? bot.lab_ids.map(id => labs.find(lab => lab.lab_id === id)?.name || id).join('、') : '未绑定' }}</b></div><div><NavIcon name="source" /><span>XLSX 数据</span><b>{{ bot.workbooks.length ? `${bot.workbooks.length} 个文件 · ${bot.workbooks.reduce((n, b) => n + b.row_count, 0).toLocaleString()} 行` : '未上传' }}</b></div></div>
        <div class="admin-bot-foot"><span v-if="bot.personal_uploads" class="muted">文件在个人对话页管理</span><button v-else class="bot-edit" @click="edit(bot)">配置助手 <span>→</span></button><button class="btn-text" :disabled="!bot.enabled" :aria-label="`使用${bot.name}`" @click="enter(bot)">进入对话 ↗</button></div>
      </article>
      <button v-if="!search" class="add-bot-card" @click="edit()"><span>＋</span><b>创建新的业务助手</b><small>连接数据，开放给你的团队</small></button>
    </div>
    <p v-if="search && !filtered.length" class="admin-empty">没有找到匹配的 Chatbot。</p>

    <Teleport to="body">
      <div v-if="editorOpen" class="bot-editor-veil" @click.self="close">
        <form ref="editor" class="bot-editor" role="dialog" aria-modal="true" aria-labelledby="bot-editor-title" @submit.prevent="save">
          <header class="bot-editor-head"><div><span>CHATBOT CONFIGURATION</span><h2 id="bot-editor-title">{{ editingId ? '配置业务助手' : '新建业务助手' }}</h2></div><button type="button" aria-label="关闭配置" :disabled="saving || uploading" @click="close">×</button></header>
          <div class="bot-editor-body">
            <section class="bot-form-section"><h3><span>01</span>基本信息</h3><div class="bot-form-basics"><ChatbotMark :category="form.category" /><label class="field"><span>Chatbot 名称</span><input ref="nameInput" v-model="form.name" required maxlength="48" placeholder="例如：区域经营分析" /></label></div><div class="bot-form-columns"><label class="field"><span>业务类型</span><select v-model="form.category"><option value="general">业务分析</option><option value="ddi">DDI 商业分析</option><option value="behavior">行为数据分析</option></select></label><label class="field"><span>使用状态</span><select v-model="form.enabled"><option :value="true">启用 · 在入口中显示</option><option :value="false">停用 · 暂不开放</option></select></label></div><label class="field"><span>业务简介</span><textarea v-model="form.description" rows="2" maxlength="280" placeholder="描述这个助手能为团队解决什么问题" /></label></section>

            <section class="bot-form-section"><h3><span>02</span>开放给谁<em>{{ selectedPeople }}</em></h3><div class="access-options"><label v-for="option in [{id:'all',name:'所有用户',hint:'已登录的业务账号'},{id:'roles',name:'按角色开放',hint:'按岗位权限分配'},{id:'users',name:'指定账号',hint:'仅向所选账号开放'}]" :key="option.id" :class="{ selected: form.access === option.id }"><input v-model="form.access" type="radio" name="bot-access" :value="option.id" /><b>{{ option.name }}</b><small>{{ option.hint }}</small></label></div><div v-if="form.access === 'roles'" class="bot-check-grid"><label v-for="role in roles" :key="role.id"><input v-model="form.roles" type="checkbox" :value="role.id" />{{ role.name }}</label></div><div v-if="form.access === 'users'" class="bot-user-list"><label v-for="user in users" :key="user.id"><input v-model="form.user_ids" type="checkbox" :value="user.id" /><span><b>{{ user.display_name || user.username }}</b><small>{{ user.username }}</small></span><em>{{ roles.find(role => role.id === user.role)?.name || user.role }}</em></label><p v-if="!users.length">暂无可用账号，请先在账号管理中创建。</p></div><p class="bot-field-note">管理员可以配置全部助手；助手内的数据权限继续遵循数据源的授权。</p></section>

            <section class="bot-form-section"><h3><span>03</span>数据来源<em>支持组合绑定</em></h3><div class="source-section-title"><NavIcon name="lab" /><b>实验室</b><span>沿用已有连接与业务口径</span></div><div class="bot-lab-list"><label v-for="lab in labs" :key="lab.lab_id" :class="{ checked: form.lab_ids.includes(lab.lab_id) }"><input v-model="form.lab_ids" type="checkbox" :value="lab.lab_id" /><span><b>{{ lab.name }}</b><small>{{ lab.blurb || lab.lab_id.toUpperCase() }}</small></span><em>{{ lab.lab_id.toUpperCase() }}</em></label><p v-if="!labs.length" class="bot-field-note">暂无实验室目录，可先上传 XLSX 工作簿。</p></div>
              <div class="source-section-title upload-title"><NavIcon name="source" /><b>XLSX 工作簿</b><span>导入自己的业务数据</span></div>
              <input ref="fileInput" type="file" accept=".xlsx" multiple hidden @change="upload" />
              <button class="bot-upload" type="button" :disabled="uploading || saving || form.workbooks.length >= 10" @click="fileInput?.click()"><span class="upload-icon">↑</span><b>{{ uploading ? '正在读取工作簿…' : '选择 XLSX 文件' }}</b><small>最多 10 个文件 · 每个 10 MB 以内 · 每个最多 5 个 sheet</small></button>
              <div v-for="book in form.workbooks" :key="book.id" class="bot-workbook"><div class="workbook-head"><span class="xlsx-icon">X</span><div><b>{{ book.filename }}</b><small>{{ book.sheets.length }} 个工作表 · {{ book.row_count.toLocaleString() }} 行<span v-if="book.sample"> · 样例数据</span></small></div><button type="button" :disabled="uploading || saving" :aria-label="`移除${book.filename}`" @click="removeBook(book.id)">移除</button></div><details v-for="sheet in book.sheets" :key="sheet.table" class="sheet-preview"><summary>{{ sheet.name }}<span>{{ sheet.columns.length }} 个字段 · 预览前 {{ sheet.preview.length }} 行</span></summary><div class="preview-scroll"><table><thead><tr><th v-for="column in sheet.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, ri) in sheet.preview" :key="ri"><td v-for="(value, ci) in row" :key="ci">{{ value ?? '—' }}</td></tr></tbody></table></div></details></div>
              <label class="sample-toggle"><input v-model="form.sample" type="checkbox" />将此助手的数据标记为样例数据</label><p class="bot-field-note">工作簿读取已保存的单元格数值，不计算公式。保存配置后，助手可以查询已绑定的实验室与文件。</p>
            </section>
          </div>
          <footer class="bot-editor-footer"><p v-if="formError" role="alert" class="form-error">{{ formError }}</p><div><span>{{ form.lab_ids.length }} 个实验室 · {{ form.workbook_ids.length }} 个工作簿</span><button class="btn-text" type="button" :disabled="saving || uploading" @click="close">取消</button><button class="btn-p" type="submit" :disabled="saving || uploading">{{ saving ? '正在保存…' : editingId ? '保存配置' : '创建 Chatbot' }}</button></div></footer>
        </form>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.chatbot-admin{max-width:1280px;margin:auto;color:#30313c;padding-bottom:60px}.chatbots-head{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:30px}.chatbots-head h1{font-size:27px;letter-spacing:-.8px;margin:10px 0}.chatbots-head h1 span{font-size:11px;font-weight:400;color:#a09aa7;margin-left:18px;letter-spacing:0}.chatbots-head p{color:#92909b;font-size:12px;margin:0}.chatbots-head>.btn-p{display:flex;align-items:center;gap:7px;white-space:nowrap;font-size:12px}.bot-overview{display:grid;grid-template-columns:repeat(3,1fr) auto;gap:24px;border:1px solid #eae7ee;background:linear-gradient(120deg,#fff,#fbf9fb);border-radius:18px;padding:22px 27px;margin-bottom:35px}.bot-overview>div{display:flex;flex-direction:column;gap:9px;border-right:1px solid #ede9ef}.bot-overview span{font-size:10px;color:#96909f}.bot-overview b{font-size:26px;letter-spacing:-1px;line-height:1.15;font-weight:600;display:flex;align-items:center;gap:10px}.overview-dot{width:6px;height:6px;background:#6c9b82;border-radius:50%;display:inline-block}.bot-overview>button{border:0;background:transparent;color:#af2440;font-size:11px;cursor:pointer;padding-left:15px}.bot-overview>button span{color:inherit;margin-left:18px}.bot-list-toolbar{display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:18px}.bot-list-toolbar h2{font-size:14px;margin:0;font-weight:600}.bot-list-toolbar h2 span{display:inline-block;font-size:10px;color:#a69baa;background:#f2eef4;border-radius:5px;padding:3px 6px;margin-left:7px;font-weight:500}.bot-search-input{border:1px solid #e5e1e9;border-radius:10px;padding:9px 13px;font-size:11px;background:#fff;width:210px;max-width:50%}.admin-bot-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px}.admin-bot-card{background:#fff;border:1px solid #e9e5ed;border-radius:20px;padding:23px;min-width:0;box-shadow:0 7px 18px #33213803;transition:border-color .2s,box-shadow .2s}.admin-bot-card:hover{border-color:#d9cbd4;box-shadow:0 10px 25px #33213807}.admin-bot-top{display:flex;align-items:center;justify-content:space-between}.admin-bot-top :deep(.bot-mark){height:43px;width:43px;border-radius:14px}.admin-bot-top :deep(.bot-mark svg){height:26px;width:26px}.bot-status{font-size:9px;color:#9b929f;display:flex;align-items:center;gap:5px}.bot-status i{height:5px;width:5px;border-radius:50%;background:#b0a9b5}.bot-status.enabled{color:#708c7a}.bot-status.enabled i{background:#7aa18b}.admin-bot-card h3{font-size:17px;margin:21px 0 9px;letter-spacing:-.3px;display:flex;align-items:center;gap:7px}.current-bot{font-size:8px;background:#faeaf0;color:#b83b55;border-radius:4px;padding:3px 5px;font-weight:400}.bot-description{font-size:11px;line-height:1.9;color:#96909c;margin:0 0 23px;min-height:42px}.bot-facts{display:flex;flex-direction:column;gap:12px}.bot-facts>div{display:flex;align-items:center;gap:7px;font-size:10px;min-width:0}.bot-facts .nav-icon{width:14px;height:14px;color:#a19aa8}.bot-facts span{color:#9b94a1}.bot-facts b{font-weight:500;margin-left:auto;color:#6b6275;max-width:60%;text-align:right;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.admin-bot-foot{margin-top:22px;padding-top:15px;border-top:1px solid #f0edf3;display:flex;justify-content:space-between;align-items:center;gap:10px}.bot-edit{font-size:11px;border:0;background:transparent;color:#b02643;font-weight:600;cursor:pointer;padding:5px 0}.bot-edit span{margin-left:16px}.admin-bot-foot .btn-text{font-size:10px;color:#9b90a1;padding:5px 0}.add-bot-card{min-height:290px;border:1px dashed #dcd4e1;background:#fcfafc;color:#9a8ca2;border-radius:20px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:11px;cursor:pointer}.add-bot-card>span{display:grid;place-items:center;background:#f2edf4;width:43px;height:43px;border-radius:14px;font-size:22px;color:#a38ba7;margin-bottom:4px}.add-bot-card b{font-size:12px;font-weight:500}.add-bot-card small{font-size:10px;color:#b1a6b6}.admin-empty{text-align:center;padding:50px 15px;color:#98909f;font-size:12px}.bot-editor-veil{position:fixed;inset:0;background:#211f2855;backdrop-filter:blur(5px);z-index:1500;display:flex;justify-content:flex-end}.bot-editor{width:650px;max-width:100%;height:100dvh;background:#fafafa;box-shadow:-18px 0 65px #25202c20;display:flex;flex-direction:column;box-sizing:border-box;color:#36343c}.bot-editor *{box-sizing:border-box}.bot-editor-head{display:flex;align-items:center;justify-content:space-between;padding:27px 31px 22px;background:#ffffffc7;border-bottom:1px solid #e8e5e9;flex-shrink:0}.bot-editor-head span{font-size:8px;letter-spacing:2px;color:#9a8d94}.bot-editor-head h2{font-size:21px;font-weight:600;margin:9px 0 0;letter-spacing:-.6px}.bot-editor-head>button{border:1px solid #e6e2e6;border-radius:10px;background:#fff;width:30px;height:30px;font-size:20px;color:#928990;cursor:pointer}.bot-editor-body{padding:26px 31px 10px;overflow-y:auto;flex:1;min-height:0}.bot-form-section{margin-bottom:30px}.bot-form-section h3{display:flex;align-items:center;font-size:13px;font-weight:600;gap:10px;margin:0 0 20px}.bot-form-section h3>span{font-size:9px;font-weight:500;color:#be99a6;letter-spacing:.5px}.bot-form-section h3 em{font-size:9px;color:#a796ac;margin-left:auto;font-style:normal;font-weight:400}.bot-form-basics{display:flex;align-items:center;gap:16px}.bot-form-basics>.field{flex:1}.bot-editor .field{margin-bottom:14px;display:flex;flex-direction:column;gap:8px;font-size:11px}.bot-editor .field>span{font-size:10px;color:#847b83}.bot-editor input:not([type=checkbox]):not([type=radio]),.bot-editor select,.bot-editor textarea{padding:11px 12px;border:1px solid #e2dce1;border-radius:10px;background:#fff;color:#4e4650;font:inherit;min-width:0;width:100%;font-size:12px;outline-color:#c5203f66;line-height:1.5}.bot-editor textarea{resize:vertical;min-height:75px}.bot-editor input[type=checkbox],.bot-editor input[type=radio]{accent-color:#c5203f;flex:none;width:14px;height:14px;margin:0}.bot-form-columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}.access-options{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}.access-options>label{position:relative;background:#fff;border:1px solid #e4dfe3;padding:14px 10px 12px 30px;border-radius:11px;cursor:pointer;min-width:0}.access-options>label.selected{border-color:#d494a4;box-shadow:0 0 0 1px #c5203f16;background:#fdf8fa}.access-options input{position:absolute;left:10px;top:15px}.access-options b{font-size:10px;font-weight:500;display:block}.access-options small{display:block;font-size:8px;color:#9d929b;margin-top:6px;white-space:nowrap}.bot-check-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;background:#fff;border:1px solid #e8e1e6;padding:15px;border-radius:10px}.bot-check-grid label{font-size:11px;display:flex;align-items:center;gap:8px;cursor:pointer}.bot-user-list{background:#fff;border:1px solid #e8e1e6;border-radius:11px;max-height:230px;overflow:auto;padding:5px 12px}.bot-user-list label{display:flex;align-items:center;gap:10px;padding:10px 0;cursor:pointer}.bot-user-list label+label{border-top:1px solid #f2edf0}.bot-user-list b{display:block;font-size:11px;font-weight:500}.bot-user-list small{font-size:9px;color:#9e909b;margin-top:3px;display:block}.bot-user-list em{margin-left:auto;font-style:normal;font-size:8px;color:#94828f}.bot-field-note{font-size:9px;line-height:1.8;color:#998995;margin:10px 0 0}.source-section-title{display:flex;align-items:center;gap:7px;margin-bottom:12px}.source-section-title .nav-icon{width:16px;height:16px;color:#a07d88}.source-section-title b{font-size:11px;font-weight:500}.source-section-title>span{font-size:9px;color:#a1949d;margin-left:auto}.upload-title{margin-top:23px}.bot-lab-list{display:grid;grid-template-columns:1fr 1fr;gap:9px}.bot-lab-list label{display:flex;align-items:center;gap:9px;padding:12px;background:#fff;border:1px solid #e5dee3;border-radius:10px;cursor:pointer;min-width:0}.bot-lab-list label.checked{background:#fcf5f8;border-color:#d9a6b2}.bot-lab-list label>span{min-width:0;flex:1}.bot-lab-list b{font-size:10px;font-weight:500;display:block}.bot-lab-list small{display:block;font-size:8px;color:#a2949d;margin-top:4px;text-overflow:ellipsis;white-space:nowrap;overflow:hidden;max-width:150px}.bot-lab-list em{font-size:8px;font-style:normal;color:#a58c96}.bot-upload{display:flex;width:100%;flex-direction:column;align-items:center;justify-content:center;gap:7px;border:1px dashed #d9c8d0;border-radius:12px;background:#faf6f7;padding:18px 10px;cursor:pointer;color:#af4058;transition:background .2s}.bot-upload:hover{background:#f8edf0}.upload-icon{font-size:22px;font-weight:300;line-height:1}.bot-upload b{font-size:11px;font-weight:500}.bot-upload small{font-size:9px;color:#a9949e}.bot-workbook{margin-top:12px;border:1px solid #e5dce1;background:#fff;border-radius:11px;overflow:hidden}.workbook-head{display:flex;align-items:center;gap:11px;padding:13px}.xlsx-icon{display:grid;place-items:center;width:31px;height:35px;background:#ebf3ee;color:#518267;border:1px solid #d5e6dc;border-radius:7px;font-size:13px;font-weight:650}.workbook-head>div{min-width:0;flex:1}.workbook-head b{font-size:11px;font-weight:500;display:block;overflow-wrap:anywhere}.workbook-head small{display:block;font-size:9px;color:#a28b97;margin-top:5px}.workbook-head>button{background:transparent;border:0;color:#b18c9a;font-size:9px;cursor:pointer;padding:5px}.sheet-preview{border-top:1px solid #f1eaee}.sheet-preview summary{font-size:10px;padding:10px 13px;cursor:pointer;color:#927582}.sheet-preview summary span{font-size:8px;color:#a38f9b;margin-left:12px}.preview-scroll{max-width:100%;overflow:auto;padding:0 12px 12px}.preview-scroll table{font-size:9px;border-collapse:collapse;white-space:nowrap;min-width:100%;text-align:left}.preview-scroll th{color:#8d7381;background:#f8f5f6;font-weight:500}.preview-scroll th,.preview-scroll td{padding:8px 10px;border-bottom:1px solid #f2ecef}.preview-scroll td{color:#877680}.sample-toggle{display:flex;align-items:center;gap:7px;font-size:10px;color:#957886;margin-top:16px;cursor:pointer}.bot-editor-footer{background:#fff;border-top:1px solid #e9e1e5;padding:14px 28px 20px;flex:none}.bot-editor-footer>div{display:flex;align-items:center;gap:18px}.bot-editor-footer>div>span{font-size:9px;color:#9d8a95;margin-right:auto}.bot-editor-footer .btn-p{font-size:11px;padding:10px 18px;white-space:nowrap}.bot-editor-footer .btn-text{font-size:11px}.bot-editor-footer .form-error{font-size:11px;margin:0 0 12px}.bot-editor button:disabled{opacity:.5;cursor:wait}@media(max-width:800px){.chatbots-head{align-items:flex-start}.chatbots-head h1{font-size:22px}.chatbots-head h1 span{display:none}.chatbots-head p{line-height:1.7;font-size:11px}.bot-overview{grid-template-columns:repeat(3,1fr);gap:15px;padding:18px}.bot-overview>button{grid-column:1/-1;text-align:left;padding:10px 0 0;border-top:1px solid #eee7f1}.bot-overview>div:nth-child(3){border:0}.bot-overview b{font-size:24px}.bot-overview span{font-size:8px}.admin-bot-grid{grid-template-columns:1fr}.chatbots-head>.btn-p{font-size:10px;padding:9px 11px}.chatbots-head>.btn-p .nav-icon{display:none}.bot-editor-body{padding:22px 19px}.bot-editor-head{padding:22px 19px}.bot-editor-footer{padding:14px 19px 20px}.access-options{gap:6px}.access-options>label{padding-left:25px;padding-right:5px}.access-options input{left:7px}.access-options small{font-size:7px;white-space:normal;line-height:1.6}.bot-lab-list{grid-template-columns:1fr}.source-section-title>span{font-size:8px}.bot-editor-footer>div{gap:10px}.bot-editor-footer>div>span{font-size:8px}}
</style>
