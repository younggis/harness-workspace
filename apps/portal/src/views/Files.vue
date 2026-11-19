<template>
  <el-card>
    <template #header>文件管理</template>
    <el-table :data="items" @row-dblclick="open">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="type" label="类型" />
      <el-table-column prop="size" label="大小" />
    </el-table>
    <el-alert v-if="error" type="error" :title="error" />
  </el-card>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'
const items = ref<any[]>([]), error = ref('')
async function load() { try { items.value = (await api('/_platform/files')).items } catch (e: any) { error.value = e.message } }
async function open(row: any) { if (row.type === 'dir') error.value = '目录导航待联调' }
onMounted(load)
</script>
