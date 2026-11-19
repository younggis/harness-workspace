<template>
  <el-card>
    <template #header>终端 <el-tag>{{ status }}</el-tag></template>
    <div ref="target" style="height:60vh;background:#000" />
  </el-card>
</template>
<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
const target = ref<HTMLElement | null>(null), status = ref('连接中')
let ws: WebSocket | null = null
onMounted(() => {
  const term = new Terminal({ convertEol: true })
  const fit = new FitAddon(); term.loadAddon(fit)
  term.open(target.value!); fit.fit()
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  ws = new WebSocket(`${proto}://${location.host}/_platform/terminal`)
  ws.binaryType = 'arraybuffer'
  ws.onopen = () => { status.value = '已连接' }
  ws.onmessage = (e) => {
    if (typeof e.data === 'string') {
      try { const o = JSON.parse(e.data); if (o.type === 'exit') { status.value = `退出(${o.code})`; return } } catch { /* text */ }
      term.write(e.data)
    } else term.write(new Uint8Array(e.data))
  }
  ws.onclose = () => { status.value = '已断开' }
  term.onData((d) => { if (ws?.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(d)) })
  term.onResize(({ cols, rows }) => ws?.send(JSON.stringify({ type: 'resize', cols, rows })))
})
onUnmounted(() => ws?.close())
</script>
