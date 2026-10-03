<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  option: { type: Object, required: true },
  height: { type: String, default: '320px' },
  // 传了名字才显示下载按钮；文件名应带范围信息（S3 / V2-014）
  downloadName: { type: String, default: '' },
})

// 图表点击转发（W5）：点击柱/单元格带着维度信息跳转检索
const emit = defineEmits(['click'])

const el = ref(null)
let chart = null
let ro = null

function render() {
  if (!el.value || !props.option) return
  if (!chart) {
    chart = echarts.init(el.value, 'dark')
    chart.on('click', (e) => emit('click', e))
  }
  chart.setOption(props.option, true)
}

function resize() {
  chart && chart.resize()
}

// 标签页从隐藏恢复可见时窗口不会 resize，但图表是在 0 宽容器里初始化的，
// 不手动重绘会一直空白（V2-013）
function onVisibilityChange() {
  if (document.visibilityState === 'visible') resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
  document.addEventListener('visibilitychange', onVisibilityChange)
  // 容器尺寸变化（折叠面板、窗口分屏）也触发重绘
  if (typeof ResizeObserver !== 'undefined' && el.value) {
    ro = new ResizeObserver(() => resize())
    ro.observe(el.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  ro && ro.disconnect()
  chart && chart.dispose()
  chart = null
})

watch(() => props.option, render, { deep: true })

// 下载 PNG（S3 / V2-014）：图表与口径信息通过文件名一起带走
function downloadImage() {
  if (!chart) return
  const url = chart.getDataURL({
    type: 'png', pixelRatio: 2, backgroundColor: '#0f1419',
  })
  const a = document.createElement('a')
  a.href = url
  a.download = (props.downloadName || 'chart') + '.png'
  a.click()
}
defineExpose({ downloadImage })
</script>

<template>
  <div class="chart-wrap" :style="{ position: 'relative' }">
    <div ref="el" class="chart-container" :style="{ height }"></div>
    <button v-if="downloadName" class="chart-download" @click="downloadImage"
            title="下载该图（PNG，文件名含当前范围）">⤓ 图</button>
  </div>
</template>

<style scoped>
.chart-download {
  position: absolute;
  top: 6px;
  right: 8px;
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  z-index: 5;
}
.chart-download:hover { color: var(--accent); border-color: var(--accent); }
</style>
