import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  base: './', // portal UI on workspace host must not collide with dsh's /assets/
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules')) {
            if (id.includes('@element-plus') || id.includes('element-plus')) return 'element-plus'
            if (id.includes('@xterm')) return 'xterm'
            if (id.includes('vue') || id.includes('@vue')) return 'vue-vendor'
            return 'vendor'
          }
        },
      },
    },
  },
})
