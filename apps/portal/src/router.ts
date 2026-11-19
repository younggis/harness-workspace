import { createRouter, createWebHistory } from 'vue-router'
import Login from './views/Login.vue'
import Home from './views/Home.vue'
import Admin from './views/Admin.vue'
import Files from './views/Files.vue'
import Terminal from './views/Terminal.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: Home, meta: { auth: true } },
    { path: '/login', component: Login },
    { path: '/admin', component: Admin, meta: { auth: true } },
    { path: '/_platform/ui/files', component: Files },
    { path: '/_platform/ui/terminal', component: Terminal },
  ],
})
