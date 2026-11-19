<template>
  <div>
    <el-card>
      <template #header>租户</template>
      <el-form :inline="true" @submit.prevent="createTenant">
        <el-form-item><el-input v-model="slug" placeholder="slug" /></el-form-item>
        <el-form-item><el-input v-model="name" placeholder="名称" /></el-form-item>
        <el-button type="primary" native-type="submit">创建</el-button>
      </el-form>
      <el-table :data="tenants"><el-table-column prop="slug" label="slug" /><el-table-column prop="name" label="名称" /><el-table-column prop="status" label="状态" /></el-table>
    </el-card>
    <el-card style="margin-top:16px">
      <template #header>创建用户</template>
      <el-form :inline="true" @submit.prevent="createUser">
        <el-form-item><el-input v-model="ulogin" placeholder="账号" /></el-form-item>
        <el-form-item><el-input v-model="uname" placeholder="姓名" /></el-form-item>
        <el-form-item><el-input v-model="upw" type="password" placeholder="密码(≥12)" /></el-form-item>
        <el-button type="primary" native-type="submit">创建</el-button>
      </el-form>
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'
const tenants = ref<any[]>([]), slug = ref(''), name = ref(''), ulogin = ref(''), uname = ref(''), upw = ref('')
async function load() { tenants.value = (await api('/api/admin/tenants')).items }
async function createTenant() { await api('/api/admin/tenants', { method: 'POST', body: JSON.stringify({ slug: slug.value, name: name.value }) }); load() }
async function createUser() { await api('/api/admin/users', { method: 'POST', body: JSON.stringify({ login: ulogin.value, display_name: uname.value, password: upw.value }) }) }
onMounted(load)
</script>
