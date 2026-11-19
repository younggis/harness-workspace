<template>
  <el-card style="max-width:420px;margin:10vh auto">
    <h2>登录</h2>
    <el-form @submit.prevent="submit">
      <el-form-item label="账号"><el-input v-model="login" /></el-form-item>
      <el-form-item label="密码"><el-input v-model="password" type="password" show-password /></el-form-item>
      <el-button type="primary" native-type="submit" :loading="busy">登录</el-button>
    </el-form>
    <el-alert v-if="error" type="error" :title="error" style="margin-top:12px" />
  </el-card>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
const login = ref(''), password = ref(''), busy = ref(false), error = ref('')
const router = useRouter()
async function submit() {
  busy.value = true; error.value = ''
  try { await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ login: login.value, password: password.value }) }); router.push('/') }
  catch (e: any) { error.value = e.message } finally { busy.value = false }
}
</script>
