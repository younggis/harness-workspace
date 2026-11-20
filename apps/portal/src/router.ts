import { createRouter, createWebHistory } from 'vue-router'
import Login from './views/Login.vue'
import Home from './views/Home.vue'
import Admin from './views/Admin.vue'
import Files from './views/Files.vue'
import Terminal from './views/Terminal.vue'
import { authGuard } from './authGuard'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Home, meta: { auth: true } },
    { path: '/login', component: Login },
    { path: '/admin', component: Admin, meta: { auth: true } },
    { path: '/_platform/ui/files', component: Files, meta: { auth: true } },
    { path: '/_platform/ui/terminal', component: Terminal, meta: { auth: true } },
  ],
})

// Never render a protected view without a session (prevents the
// "click 工作台 while logged out → 无权限" error).
router.beforeEach(authGuard)

export default router
