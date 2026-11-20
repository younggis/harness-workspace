import { createRouter, createWebHistory } from 'vue-router'
import Login from './views/Login.vue'
import { authGuard } from './authGuard'

// Route-level code splitting: heavy views (Element Plus tables, xterm) load on
// demand instead of inflating the initial bundle.
const Home = () => import('./views/Home.vue')
const Admin = () => import('./views/Admin.vue')
const Files = () => import('./views/Files.vue')
const Terminal = () => import('./views/Terminal.vue')

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
