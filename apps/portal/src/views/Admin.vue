<template>
  <div>
    <el-alert type="info" :closable="false" style="margin-bottom:12px">
      关系：用户是全局身份；同一用户可属于多个租户（membership 决定角色/状态）；空间归属于“租户 + 该租户的成员”。
      密码为 Argon2id 单向哈希，创建后不可查看，只能重置。
    </el-alert>

    <el-row :gutter="12">
      <el-col :span="10">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>租户</span><el-button size="small" @click="tenantDialog=true">新建租户</el-button>
            </div>
          </template>
          <el-table :data="tenants" highlight-current-row @current-change="selectTenant"
                    v-loading="loading.tenants">
            <el-table-column prop="slug" label="slug" />
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="status" label="状态">
              <template #default="{row}"><el-tag :type="row.status==='active'?'success':'info'">{{ row.status }}</el-tag></template>
            </el-table-column>
            <el-table-column label="操作">
              <template #default="{row}">
                <el-button link size="small" @click.stop="toggleTenant(row)">
                  {{ row.status==='active' ? '停用' : '启用' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card style="margin-top:12px">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>用户</span><el-button size="small" @click="userDialog=true">新建用户</el-button>
            </div>
          </template>
          <el-table :data="users" v-loading="loading.users" size="small">
            <el-table-column prop="login_norm" label="账号" />
            <el-table-column prop="display_name" label="姓名" />
            <el-table-column label="平台管理员">
              <template #default="{row}">{{ row.is_platform_admin ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column label="操作">
              <template #default="{row}">
                <el-button link size="small" @click="resetPw(row)">重置密码</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="14">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>{{ selected ? `成员与空间 · ${selected.name}` : '成员与空间（请先选择租户）' }}</span>
            </div>
          </template>
          <template v-if="selected">
            <el-tabs v-model="tab">
              <el-tab-pane label="成员" name="members">
                <el-form :inline="true">
                  <el-form-item><el-select v-model="member.login" filterable placeholder="选择用户" style="width:220px">
                    <el-option v-for="u in users" :key="u.id" :label="`${u.login_norm} (${u.display_name})`" :value="u.id" />
                  </el-select></el-form-item>
                  <el-form-item><el-select v-model="member.role" style="width:130px">
                    <el-option label="租户管理员" value="tenant_admin" />
                    <el-option label="成员" value="member" />
                  </el-select></el-form-item>
                  <el-form-item><el-button type="primary" @click="addMember">添加/更新成员</el-button></el-form-item>
                </el-form>
                <el-table :data="members" v-loading="loading.members" size="small">
                  <el-table-column prop="login_norm" label="账号" />
                  <el-table-column prop="display_name" label="姓名" />
                  <el-table-column prop="role" label="角色" />
                  <el-table-column prop="status" label="状态" />
                  <el-table-column label="操作">
                    <template #default="{row}">
                      <el-button link size="small" @click="toggleMember(row)">
                        {{ row.status==='active' ? '停用' : '启用' }}
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>

              <el-tab-pane label="工作空间" name="workspaces">
                <el-form :inline="true">
                  <el-form-item><el-select v-model="ws.owner_id" filterable placeholder="选择所有者（本租户成员）" style="width:240px">
                    <el-option v-for="m in members.filter(x=>x.status==='active')" :key="m.user_id"
                               :label="m.login_norm" :value="m.user_id" />
                  </el-select></el-form-item>
                  <el-form-item><el-select v-model="ws.template_version" style="width:160px">
                    <el-option v-for="t in templates" :key="t.version" :label="t.version" :value="t.version" />
                  </el-select></el-form-item>
                  <el-form-item label="CPU"><el-input-number v-model="ws.cpu" :min="1" :max="32" style="width:110px" /></el-form-item>
                  <el-form-item label="内存GB"><el-input-number v-model="ws.memory_gb" :min="0.25" :max="64" :step="0.5" :precision="2" style="width:110px" /></el-form-item>
                  <el-form-item><el-button type="primary" @click="allocateWs">分配空间</el-button></el-form-item>
                  <div class="hint" style="width:100%">资源留空则继承该租户的单空间规格（当前默认 {{ selected?.cpu_per_space }} 核 / {{ gb(selected?.memory_per_space_bytes) }} GB）。</div>
                </el-form>
                <el-table :data="workspaces" v-loading="loading.workspaces" size="small">
                  <el-table-column prop="owner_login" label="所有者" />
                  <el-table-column prop="template_version" label="模板" />
                  <el-table-column label="资源" width="150">
                    <template #default="{row}">{{ row.cpu }}核 / {{ gb(row.memory_bytes) }}GB / {{ row.pids_limit }}pids</template>
                  </el-table-column>
                  <el-table-column prop="observed_state" label="状态" />
                  <el-table-column prop="generation" label="代际" />
                </el-table>
              </el-tab-pane>

              <el-tab-pane label="用量与审计" name="usage">
                <el-descriptions :column="2" border size="small">
                  <el-descriptions-item label="每日 token 预算">{{ selected.daily_token_budget }}</el-descriptions-item>
                  <el-descriptions-item label="运行 / 空间上限">{{ selected.max_running }} / {{ selected.max_workspaces }}</el-descriptions-item>
                  <el-descriptions-item label="单空间资源">{{ selected.cpu_per_space }}核 / {{ gb(selected.memory_per_space_bytes) }}GB / {{ selected.pids_per_space }}pids</el-descriptions-item>
                  <el-descriptions-item label="运行态总量上限">{{ selected.max_total_cpu }}核 / {{ gb(selected.max_total_memory_bytes) }}GB / {{ selected.max_total_pids }}pids</el-descriptions-item>
                </el-descriptions>
                <h4>模型用量</h4>
                <el-table :data="usage.items" size="small">
                  <el-table-column prop="model" label="模型" />
                  <el-table-column prop="requests" label="请求数" />
                  <el-table-column prop="input_tokens" label="输入 token" />
                  <el-table-column prop="output_tokens" label="输出 token" />
                </el-table>
                <div class="audit-head"><h4>审计事件</h4><el-button size="small" @click="exportAudit">导出 CSV</el-button></div>
                <el-table :data="audit" size="small">
                  <el-table-column prop="occurred_at" label="时间" />
                  <el-table-column prop="action" label="动作" />
                  <el-table-column prop="result" label="结果" />
                </el-table>
              </el-tab-pane>
            </el-tabs>
          </template>
          <el-empty v-else description="从左侧选择一个租户" />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="tenantDialog" title="新建租户" width="460px">
      <el-form label-width="100px">
        <el-form-item label="slug"><el-input v-model="newTenant.slug" placeholder="小写字母/数字/连字符" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="newTenant.name" /></el-form-item>
        <el-form-item label="运行上限"><el-input-number v-model="newTenant.max_running" :min="0" /></el-form-item>
        <el-form-item label="空间上限"><el-input-number v-model="newTenant.max_workspaces" :min="0" /></el-form-item>
        <el-form-item label="日 token 预算"><el-input-number v-model="newTenant.daily_token_budget" :min="0" :step="100000" /></el-form-item>
        <el-divider content-position="left">单空间资源</el-divider>
        <el-form-item label="CPU 核数"><el-input-number v-model="newTenant.cpu_per_space" :min="1" :max="32" /></el-form-item>
        <el-form-item label="内存 (GB)"><el-input-number v-model="newTenant.memory_gb" :min="0.25" :max="64" :step="0.5" :precision="2" /></el-form-item>
        <el-form-item label="PIDS 上限"><el-input-number v-model="newTenant.pids_per_space" :min="64" :max="4096" :step="64" /></el-form-item>
        <el-divider content-position="left">运行态总量上限</el-divider>
        <el-form-item label="CPU 总量"><el-input-number v-model="newTenant.max_total_cpu" :min="1" :max="256" /></el-form-item>
        <el-form-item label="内存总量 (GB)"><el-input-number v-model="newTenant.max_total_memory_gb" :min="1" :max="512" :step="1" /></el-form-item>
        <el-form-item label="PIDS 总量"><el-input-number v-model="newTenant.max_total_pids" :min="1" :max="65536" :step="256" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="tenantDialog=false">取消</el-button><el-button type="primary" @click="createTenant">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="userDialog" title="新建用户" width="460px">
      <el-form label-width="90px">
        <el-form-item label="账号"><el-input v-model="newUser.login" /></el-form-item>
        <el-form-item label="姓名"><el-input v-model="newUser.display_name" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="newUser.password" :type="showPw ? 'text' : 'password'">
            <template #append><el-button @click="showPw=!showPw">{{ showPw ? '隐藏' : '显示' }}</el-button></template>
          </el-input>
          <div class="hint">留空将自动生成强密码；创建后仅显示一次，无法再查看。</div>
        </el-form-item>
        <el-form-item label="平台管理员"><el-switch v-model="newUser.is_platform_admin" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="userDialog=false">取消</el-button><el-button type="primary" @click="createUser">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="pwDialog" title="一次性密码（仅显示一次）" width="460px">
      <el-alert type="warning" :closable="false" title="请立即复制保存；关闭后无法再查看（Argon2id 单向哈希）。" />
      <el-input v-model="shownPassword" :type="showPw ? 'text' : 'password'" readonly style="margin-top:12px">
        <template #append>
          <el-button @click="showPw=!showPw">{{ showPw ? '隐藏' : '显示' }}</el-button>
          <el-button @click="copyPw">复制</el-button>
        </template>
      </el-input>
      <template #footer><el-button type="primary" @click="pwDialog=false">我已保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { api, newId, csrf } from '../api'

const tenants = ref<any[]>([]), users = ref<any[]>([]), members = ref<any[]>([])
const workspaces = ref<any[]>([]), templates = ref<any[]>([])
const selected = ref<any>(null), tab = ref('members')
const usage = ref<any>({ items: [] }), audit = ref<any[]>([])
const loading = reactive({ tenants: false, users: false, members: false, workspaces: false })
const tenantDialog = ref(false), userDialog = ref(false), pwDialog = ref(false)
const showPw = ref(false), shownPassword = ref('')

const GB = 1024 * 1024 * 1024
const gb = (bytes?: number) => bytes ? (bytes / GB).toFixed(bytes % GB ? 2 : 0) : '1'
const newTenant = reactive({
  slug: '', name: '', max_running: 2, max_workspaces: 10, daily_token_budget: 1000000,
  cpu_per_space: 1, memory_gb: 1, pids_per_space: 256,
  max_total_cpu: 4, max_total_memory_gb: 4, max_total_pids: 1024,
})
const newUser = reactive({ login: '', display_name: '', password: '', is_platform_admin: false })
const member = reactive({ login: '', role: 'member' })
const ws = reactive({ owner_id: '', template_version: '', cpu: undefined as number | undefined, memory_gb: undefined as number | undefined })

function genPassword() {
  const a = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%'
  return Array.from({ length: 16 }, () => a[Math.floor(Math.random() * a.length)]).join('')
}
async function run(fn: () => Promise<void>, ok: string) {
  try { await fn(); if (ok) ElMessage.success(ok) }
  catch (e: any) { ElMessage.error(e.message || '操作失败') }
}
async function loadTenants() { loading.tenants = true; try { tenants.value = (await api('/api/admin/tenants')).items } finally { loading.tenants = false } }
async function loadUsers() { loading.users = true; try { users.value = (await api('/api/admin/users')).items } finally { loading.users = false } }
async function loadTemplates() { templates.value = await api('/api/templates') }
async function selectTenant(row: any) {
  if (!row) return
  selected.value = row
  member.login = ''; ws.owner_id = ''
  ws.cpu = undefined; ws.memory_gb = undefined
  if (templates.value.length) ws.template_version = templates.value[0].version
  await Promise.all([loadMembers(), loadWorkspaces(), loadUsage(), loadAudit()])
}
async function loadMembers() { if (!selected.value) return; loading.members = true; try { members.value = (await api(`/api/admin/tenants/${selected.value.id}/members`)).items } finally { loading.members = false } }
async function loadWorkspaces() { if (!selected.value) return; loading.workspaces = true; try { workspaces.value = (await api(`/api/admin/tenants/${selected.value.id}/workspaces`)).items } finally { loading.workspaces = false } }
async function loadUsage() { if (!selected.value) return; usage.value = await api(`/api/admin/tenants/${selected.value.id}/usage`) }
async function loadAudit() { if (!selected.value) return; audit.value = (await api(`/api/admin/tenants/${selected.value.id}/audit`)).items }
async function exportAudit() {
  await run(async () => {
    const res = await fetch(`/api/admin/audit/export?limit=5000`, { credentials: 'same-origin', headers: { 'X-CSRF-Token': csrf() } })
    if (!res.ok) throw new Error((await res.json()).error?.message || '导出失败')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'harness-audit.csv'; a.click()
    URL.revokeObjectURL(url)
  }, '审计已导出')
}

async function createTenant() {
  await run(async () => {
    const { memory_gb, max_total_memory_gb, ...rest } = newTenant
    await api('/api/admin/tenants', { method: 'POST', body: JSON.stringify({
      ...rest,
      memory_per_space_bytes: Math.round(memory_gb * GB),
      max_total_memory_bytes: Math.round(max_total_memory_gb * GB),
    }) })
    tenantDialog.value = false; await loadTenants()
  }, '租户已创建')
}
async function createUser() {
  await run(async () => {
    const password = newUser.password || genPassword()
    const u = await api('/api/admin/users', { method: 'POST', body: JSON.stringify({
      login: newUser.login, display_name: newUser.display_name,
      password, is_platform_admin: newUser.is_platform_admin,
    }) })
    userDialog.value = false; newUser.password = ''; await loadUsers()
    await nextTick()
    shownPassword.value = password; showPw.value = true; pwDialog.value = true
    ElMessage.success(`用户 ${u.login_norm} 已创建`)
  }, '')
}
async function resetPw(row: any) {
  await run(async () => {
    const password = genPassword()
    await api(`/api/admin/users/${row.id}/password`, { method: 'POST', body: JSON.stringify({ password }) })
    shownPassword.value = password; showPw.value = true; pwDialog.value = true
  }, '密码已重置')
}
function copyPw() { navigator.clipboard?.writeText(shownPassword.value).then(() => ElMessage.success('已复制')) }
async function toggleTenant(row: any) {
  await run(async () => {
    await api(`/api/admin/tenants/${row.id}`, { method: 'PATCH', body: JSON.stringify({ status: row.status === 'active' ? 'disabled' : 'active' }) })
    await loadTenants()
  }, '状态已更新')
}
async function addMember() {
  if (!selected.value || !member.login) { ElMessage.warning('请选择用户'); return }
  await run(async () => {
    await api(`/api/admin/tenants/${selected.value.id}/members/${member.login}`, { method: 'PUT', body: JSON.stringify({ role: member.role, status: 'active' }) })
    await loadMembers()
  }, '成员已保存')
}
async function toggleMember(row: any) {
  await run(async () => {
    await api(`/api/admin/tenants/${selected.value.id}/members/${row.user_id}`, { method: 'PUT', body: JSON.stringify({ role: row.role, status: row.status === 'active' ? 'disabled' : 'active' }) })
    await loadMembers()
  }, '成员状态已更新')
}
async function allocateWs() {
  if (!selected.value || !ws.owner_id || !ws.template_version) { ElMessage.warning('请选择所有者和模板'); return }
  await run(async () => {
    const body: any = { owner_id: ws.owner_id, template_version: ws.template_version }
    if (ws.cpu !== undefined) body.cpu = ws.cpu
    if (ws.memory_gb !== undefined) body.memory_bytes = Math.round(ws.memory_gb * GB)
    await api(`/api/admin/tenants/${selected.value.id}/workspaces`, { method: 'POST', headers: { 'Idempotency-Key': newId() }, body: JSON.stringify(body) })
    ws.cpu = undefined; ws.memory_gb = undefined
    await loadWorkspaces()
  }, '空间已分配（可在“我的空间”启动）')
}
onMounted(async () => { await Promise.all([loadTenants(), loadUsers(), loadTemplates()]) })
</script>
<style scoped>
.audit-head { display:flex; align-items:center; justify-content:space-between; }
.hint { font-size: 12px; color: #909399; margin-top: 4px; }
</style>
