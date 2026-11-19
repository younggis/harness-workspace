<template>
  <div>
    <el-space style="margin-bottom:16px">
      <span>当前租户：</span>
      <el-select :model-value="active" @change="switchTenant" style="width:220px">
        <el-option v-for="t in tenants" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>
    </el-space>
    <el-table :data="workspaces">
      <el-table-column prop="template_version" label="模板" />
      <el-table-column prop="observed_state" label="状态" />
      <el-table-column prop="generation" label="代际" />
      <el-table-column label="操作">
        <template #default="{ row }">
          <el-button size="small" :disabled="!row.actions.includes('start')" @click="act(row,'start')">启动</el-button>
          <el-button size="small" :disabled="!row.actions.includes('stop')" @click="act(row,'stop')">停止</el-button>
          <el-button size="small" type="primary" :disabled="row.observed_state!=='running'" @click="enter(row)">进入</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api, enterWorkspace } from '../api'
const workspaces = ref<any[]>([]), tenants = ref<any[]>([]), active = ref('')
async function load() {
  const me = await api('/api/me'); tenants.value = me.tenants; active.value = me.active_tenant_id
  workspaces.value = await api('/api/workspaces')
}
async function switchTenant(id: string) { await api('/api/auth/active-tenant', { method: 'POST', body: JSON.stringify({ tenant_id: id }) }); load() }
async function act(row: any, a: string) {
  await api(`/api/workspaces/${row.id}/actions/${a}`, { method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() } }); load()
}
async function enter(row: any) {
  const t = await api(`/api/workspaces/${row.id}/entry-tickets`, { method: 'POST', body: JSON.stringify({ target: 'agent' }) })
  enterWorkspace(t.workspace_host, t.ticket, t.target)
}
onMounted(load)
</script>
