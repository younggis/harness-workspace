<template>
  <el-container class="shell">
    <el-header class="topbar">
      <div class="brand" @click="router.push('/')">
        <div class="logo">H</div>
        <div class="brand-text"><b>Harness</b><span>Workspace</span></div>
      </div>
      <el-menu mode="horizontal" :default-active="route.path" router class="nav">
        <el-menu-item index="/"><el-icon><House /></el-icon>工作台</el-menu-item>
        <el-menu-item index="/admin" v-if="me?.user?.is_platform_admin || isTenantAdmin">
          <el-icon><Setting /></el-icon>管理
        </el-menu-item>
      </el-menu>
      <div class="user-area">
        <el-dropdown v-if="me" trigger="click" @command="onCommand">
          <span class="user-chip">
            <el-avatar :size="30" class="avatar">{{ (me.user.display_name || 'U').slice(0,1) }}</el-avatar>
            <span class="uname">{{ me.user.display_name }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="switch">切换租户</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-else type="primary" size="small" @click="router.push('/login')">登录</el-button>
      </div>
    </el-header>
    <el-main class="content"><router-view /></el-main>
    <el-footer class="footer">Harness Workspace · 多租户 AI 开发工作台</el-footer>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { House, Setting, ArrowDown } from '@element-plus/icons-vue'
import { api } from './api'

const router = useRouter(), route = useRoute()
const me = ref<any>(null)
const isTenantAdmin = computed(() => !!me.value?.tenants?.length)

async function loadMe() { try { me.value = await api('/api/me') } catch { me.value = null } }
async function onCommand(cmd: string) {
  if (cmd === 'logout') {
    await api('/api/auth/logout', { method: 'POST' }); me.value = null; ElMessage.success('已退出'); router.push('/login')
  } else if (cmd === 'switch') {
    if (!me.value?.tenants?.length) { ElMessage.info('当前账号没有可切换的租户'); return }
    try {
      const { value } = await ElMessageBox.prompt('输入要切换到的租户名称', '切换租户', {
        inputType: 'text', inputPlaceholder: me.value.tenants.map((t:any)=>t.name).join(' / '),
      }).catch(() => ({ value: null }))
      const t = me.value.tenants.find((x:any)=>x.name === value || x.id === value)
      if (t) { await api('/api/auth/active-tenant', { method: 'POST', body: JSON.stringify({ tenant_id: t.id }) }); await loadMe(); ElMessage.success(`已切换到 ${t.name}`); router.push('/') }
    } catch (e:any) { ElMessage.error(e.message) }
  }
}
onMounted(loadMe)
</script>

<style scoped>
.shell { min-height: 100vh; background: #f5f7fa; }
.topbar { display:flex; align-items:center; gap:24px; background:#fff; border-bottom:1px solid #e8ecf2; box-shadow:0 1px 4px rgba(16,24,40,.04); padding:0 28px; height:64px; }
.brand { display:flex; align-items:center; gap:10px; cursor:pointer; }
.logo { width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,#409eff,#7c5cff);color:#fff;display:grid;place-items:center;font-weight:800;font-size:18px; }
.brand-text { display:flex;flex-direction:column;line-height:1.1;font-size:16px; }
.brand-text span { font-size:11px;color:#909399;letter-spacing:1px; }
.nav { flex:1; border-bottom:none; height:64px; }
.user-area { margin-left:auto; }
.user-chip { display:flex;align-items:center;gap:8px;cursor:pointer;outline:none; }
.avatar { background:linear-gradient(135deg,#409eff,#7c5cff); }
.uname { font-size:13px;color:#303133; }
.content { max-width:1280px; width:100%; margin:0 auto; padding:28px; }
.footer { text-align:center;color:#a8abb2;font-size:12px;height:48px; }
</style>
