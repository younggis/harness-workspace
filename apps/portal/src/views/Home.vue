<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1>我的工作空间</h1>
        <p class="sub">选择租户后，进入你的隔离 Linux 环境：Agent 分析、文件编辑与交互终端</p>
      </div>
      <div class="head-actions">
        <el-select v-model="active" placeholder="选择租户" style="width:200px" @change="switchTenant">
          <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
        </el-select>
        <el-button :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="16" class="stats">
      <el-col :span="8"><el-card shadow="never" class="stat"><div class="stat-label">工作空间</div><div class="stat-value">{{ workspaces.length }}</div></el-card></el-col>
      <el-col :span="8"><el-card shadow="never" class="stat"><div class="stat-label">运行中</div><div class="stat-value ok">{{ runningCount }}</div></el-card></el-col>
      <el-col :span="8"><el-card shadow="never" class="stat"><div class="stat-label">当前租户</div><div class="stat-value name">{{ currentTenantName }}</div></el-card></el-col>
    </el-row>

    <div v-loading="loading" class="grid">
      <el-card v-for="ws in workspaces" :key="ws.id" shadow="hover" class="ws-card">
        <template #header>
          <div class="card-head">
            <div class="icon-box"><el-icon><Monitor /></el-icon></div>
            <div class="title-block">
              <div class="ws-title">个人工作空间</div>
              <div class="ws-sub">{{ ws.template_version }} · #{{ ws.id.slice(0,8) }}</div>
            </div>
            <el-tag :type="stateType(ws.observed_state)" effect="light" size="small">{{ stateLabel(ws.observed_state) }}</el-tag>
          </div>
        </template>
        <div class="meta">
          <div><span>代际</span><b>{{ ws.generation }}</b></div>
          <div><span>期望状态</span><b>{{ ws.desired_state }}</b></div>
          <div><span>错误</span><b>{{ ws.error_code || '—' }}</b></div>
          <div><span>资源</span><b>{{ ws.cpu }}核 / {{ (ws.memory_bytes/1073741824).toFixed(1) }}GB / {{ ws.pids_limit }}pids</b></div>
        </div>
        <div class="card-actions">
          <el-button :disabled="!ws.actions.includes('start')" @click="act(ws,'start')">启动</el-button>
          <el-button :disabled="!ws.actions.includes('stop')" @click="act(ws,'stop')">停止</el-button>
          <el-button type="primary" :disabled="ws.observed_state!=='running'" @click="enter(ws)" :loading="entering===ws.id">
            进入工作空间 <el-icon class="el-icon--right"><Right /></el-icon>
          </el-button>
        </div>
      </el-card>

      <el-card v-if="!loading && !workspaces.length" shadow="never" class="empty">
        <el-empty description="当前租户下还没有工作空间，请联系管理员分配" />
      </el-card>
    </div>

    <el-dialog v-model="ticketDialog" title="正在进入工作空间" width="420px" :show-close="false">
      <div class="ticket-body">
        <el-icon class="is-loading" :size="26"><Loading /></el-icon>
        <p>正在兑换一次性访问票据并跳转…</p>
        <el-alert v-if="ticketError" type="error" :title="ticketError" />
      </div>
      <template #footer><el-button v-if="ticketError" type="primary" @click="ticketDialog=false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Monitor, Right, Loading } from '@element-plus/icons-vue'
import { api, enterWorkspace, newId } from '../api'

const workspaces = ref<any[]>([]), tenants = ref<any[]>([]), active = ref('')
const loading = ref(false), entering = ref(''), ticketDialog = ref(false), ticketError = ref('')
const runningCount = computed(() => workspaces.value.filter(w=>w.observed_state==='running').length)
const currentTenantName = computed(() => tenants.value.find(t=>t.id===active.value)?.name || '—')

function stateLabel(s: string) { return ({ running:'运行中', stopped:'已停止', starting:'启动中', stopping:'停止中', provisioning:'准备中', error:'异常' } as any)[s] || s }
function stateType(s: string) { return s==='running' ? 'success' : s==='error' ? 'danger' : s==='stopped' ? 'info' : 'warning' }

async function load() {
  loading.value = true
  try {
    const me = await api('/api/me'); tenants.value = me.tenants; active.value = me.active_tenant_id
    workspaces.value = await api('/api/workspaces')
  } catch (e:any) { ElMessage.error(e.message) } finally { loading.value = false }
}
async function switchTenant(id: string) {
  try { await api('/api/auth/active-tenant', { method:'POST', body: JSON.stringify({ tenant_id:id }) }); await load(); ElMessage.success('已切换租户') }
  catch (e:any) { ElMessage.error(e.message) }
}
async function act(row: any, a: string) {
  try {
    await api(`/api/workspaces/${row.id}/actions/${a}`, { method:'POST', headers:{ 'Idempotency-Key': newId() } })
    ElMessage.success(a==='start' ? '已提交启动请求' : '已提交停止请求'); await load()
  } catch (e:any) { ElMessage.error(e.message) }
}
async function enter(row: any) {
  entering.value = row.id; ticketError.value = ''; ticketDialog.value = true
  try {
    const t = await api(`/api/workspaces/${row.id}/entry-tickets`, { method:'POST', body: JSON.stringify({ target:'agent' }) })
    enterWorkspace(t.workspace_host, t.ticket, t.target)
  } catch (e:any) { ticketError.value = e.message; ElMessage.error(e.message) }
  finally { entering.value = '' }
}
onMounted(load)
</script>

<style scoped>
.page { max-width:1100px;margin:0 auto; }
.page-head { display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px; }
h1 { margin:0 0 6px;font-size:24px;font-weight:700;color:#1d2129; }
.sub { margin:0;color:#86909c;font-size:13px; }
.head-actions { display:flex;gap:10px; }
.stats { margin-bottom:18px; }
.stat { border-radius:12px; }
.stat-label { color:#86909c;font-size:12px; }
.stat-value { font-size:26px;font-weight:700;margin-top:4px; }
.stat-value.ok { color:#67c23a; }
.stat-value.name { font-size:18px; }
.grid { display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px; }
.ws-card { border-radius:14px; }
.card-head { display:flex;align-items:center;gap:12px; }
.icon-box { width:38px;height:38px;border-radius:10px;background:#ecf5ff;color:#409eff;display:grid;place-items:center;font-size:18px; }
.title-block { flex:1; }
.ws-title { font-weight:600;color:#303133; }
.ws-sub { font-size:11px;color:#a8abb2;margin-top:2px; }
.meta { display:flex;justify-content:space-between;color:#86909c;font-size:12px;padding:4px 0 12px; }
.meta div { display:flex;flex-direction:column;gap:2px; }
.meta b { color:#303133;font-size:13px; }
.card-actions { display:flex;gap:8px;justify-content:flex-end;border-top:1px solid #f0f2f5;padding-top:12px; }
.empty { grid-column:1/-1;border-radius:14px; }
.ticket-body { text-align:center;padding:10px 0; }
.ticket-body p { color:#606266; }
</style>
