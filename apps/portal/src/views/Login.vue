<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <div class="logo">H</div>
        <div><h1>Harness Workspace</h1><p>多租户 AI 开发工作台</p></div>
      </div>
      <el-divider />
      <h2>登录</h2>
      <p class="tip">使用管理员分配的账号登录，进入你的隔离工作空间</p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="账号"><el-input v-model="login" size="large" placeholder="请输入账号" :prefix-icon="User" /></el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" size="large" show-password placeholder="请输入密码" :prefix-icon="Lock" @keyup.enter="submit" />
        </el-form-item>
        <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" style="margin-bottom:12px" />
        <el-button type="primary" size="large" class="submit" native-type="submit" :loading="busy">登录</el-button>
      </el-form>
      <div class="foot">登录即表示你同意遵循平台的使用与审计规范</div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { api } from '../api'
const login = ref(''), password = ref(''), busy = ref(false), error = ref('')
const router = useRouter()
async function submit() {
  busy.value = true; error.value = ''
  try { await api('/api/auth/login', { method:'POST', body: JSON.stringify({ login:login.value, password:password.value }) }); router.push('/') }
  catch (e:any) { error.value = e.message || '登录失败' }
  finally { busy.value = false }
}
</script>
<style scoped>
.login-page { min-height:calc(100vh - 112px);display:grid;place-items:center;background:radial-gradient(circle at 20% 20%,#eaf2ff,transparent 45%),radial-gradient(circle at 80% 80%,#f3ecff,transparent 45%); }
.login-card { width:420px;background:#fff;border-radius:18px;padding:32px;box-shadow:0 12px 40px rgba(16,24,40,.10); }
.brand { display:flex;align-items:center;gap:12px; }
.logo { width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#409eff,#7c5cff);color:#fff;display:grid;place-items:center;font-size:22px;font-weight:800; }
h1 { margin:0;font-size:18px; }
.brand p { margin:2px 0 0;color:#909399;font-size:12px; }
h2 { margin:0 0 4px;font-size:22px; }
.tip { color:#909399;font-size:12px;margin:0 0 18px; }
.submit { width:100%;margin-top:6px; }
.foot { text-align:center;color:#c0c4cc;font-size:11px;margin-top:18px; }
</style>
