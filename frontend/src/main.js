import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router.js'
import { loadBranding, restoreSession } from './store.js'
import './styles/global.css'

async function bootstrap() {
  await loadBranding()
  await restoreSession()
  createApp(App).use(router).mount('#app')
}

bootstrap()
