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
              <el-dropdown-item command="mfa">安全设置（MFA）</el-dropdown-item>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-else type="primary" size="small" @click="router.push('/login')">登录</el-button>
      </div>
    </el-header>
    <el-main class="content"><router-view /></el-main>
    <el-footer class="footer">Harness Workspace · 多租户 AI 开发工作台</el-footer>

    <el-dialog v-model="mfaDialog" title="安全设置 · 双因素验证" width="440px">
      <el-alert type="info" :closable="false" title="使用验证器 App（Google Authenticator / 1Password 等）扫描二维码或手动输入密钥" />
      <div v-if="mfaSecret" class="mfa-secret">
        <div class="hint">一次性密钥（仅显示一次）：</div>
        <el-input v-model="mfaSecret" readonly />
        <el-button size="small" @click="copySecret">复制</el-button>
      </div>
      <el-form label-width="90px" style="margin-top:16px">
        <el-form-item label="验证码"><el-input v-model="mfaCode" placeholder="验证器中的 6 位代码" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="mfaSecret" @click="confirmMfa" type="primary">确认启用</el-button>
        <el-button v-else @click="disableMfa" type="danger">关闭 MFA</el-button>
        <el-button @click="mfaDialog=false">取消</el-button>
      </template>
    </el-dialog>
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
const isTenantAdmin = computed(() => {
  const t = (me.value?.tenants || []).find((x: any) => x.id === me.value?.active_tenant_id)
  return t?.role === 'tenant_admin' || t?.role === 'admin'
})

async function loadMe() { try { me.value = await api('/api/me') } catch { me.value = null } }
async function onCommand(cmd: string) {
  if (cmd === 'logout') {
    await api('/api/auth/logout', { method: 'POST' }); me.value = null; ElMessage.success('已退出'); router.push('/login')
  } else if (cmd === 'mfa') {
    mfaSecret.value = ''; mfaCode.value = ''; mfaDialog.value = true
    await enrollMfa()
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
const mfaDialog = ref(false), mfaSecret = ref(''), mfaCode = ref('')
async function enrollMfa() {
  try { const r = await api('/api/auth/mfa/enroll', { method:'POST', body:'{}' }); mfaSecret.value = r.secret; ElMessage.success('请用验证器扫描/输入密钥后确认') }
  catch (e:any) { ElMessage.error(e.message) }
}
async function confirmMfa() {
  try { await api('/api/auth/mfa/verify', { method:'POST', body: JSON.stringify({ code:mfaCode.value }) }); ElMessage.success('MFA 已启用'); mfaDialog.value=false; mfaSecret.value='' }
  catch (e:any) { ElMessage.error(e.message) }
}
async function disableMfa() {
  try { await api('/api/auth/mfa/disable', { method:'POST', body: JSON.stringify({ code:mfaCode.value }) }); ElMessage.success('MFA 已关闭'); mfaDialog.value=false }
  catch (e:any) { ElMessage.error(e.message) }
}
function copySecret(){ navigator.clipboard?.writeText(mfaSecret.value).then(()=>ElMessage.success('已复制')) }
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
.mfa-secret { margin-top:14px;display:flex;align-items:center;gap:8px; }
.mfa-secret .hint { font-size:12px;color:#606266;white-space:nowrap; }
</style>
