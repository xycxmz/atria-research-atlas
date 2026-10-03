<script setup>
/**
 * 统一的数据加载状态（V2-011）：加载中 / 请求失败 / 产物未就绪 / 空结果 / 正常。
 * 替换各页手写的 `v-if error / v-else-if !data` 模板；失败可重试且保留已应用条件。
 */
const props = defineProps({
  loading: { type: Boolean, default: false },
  // string | Error | ApiError（ApiError 带 kind/missing，503 时为产物未就绪）
  error: { type: [String, Error, Object], default: null },
  empty: { type: Boolean, default: false },
  emptyText: { type: String, default: '没有符合条件的结果——请放宽筛选后重试' },
  retryable: { type: Boolean, default: true },
})
const emit = defineEmits(['retry'])

function isUnready(e) {
  return typeof e === 'object' && e !== null && (e.kind === 'unavailable' || e.kind === 'missing')
}

function message(e) {
  if (!e) return ''
  if (typeof e === 'string') return e
  return e.message || String(e)
}
</script>

<template>
  <div v-if="loading" class="loading">加载中…</div>
  <div v-else-if="error" class="error">
    <template v-if="isUnready(error)">
      <strong>数据产物未就绪</strong>
      <div>{{ message(error) }}</div>
      <div class="hint" style="margin-top: 4px;">
        缺失/损坏的产物不能当空数据渲染。先在项目目录执行
        <code>python -m merge.build</code> 与 <code>python -m analysis.analyze</code>
        （聚合页另需 <code>python tools/build_national.py</code>），再点重试。
      </div>
    </template>
    <template v-else>加载失败: {{ message(error) }}</template>
    <button v-if="retryable" class="pager-btn" style="margin-top: 8px;" @click="emit('retry')">重试</button>
  </div>
  <div v-else-if="empty" class="empty">{{ emptyText }}</div>
  <slot v-else />
</template>

<style scoped>
.empty {
  padding: 24px 16px;
  color: var(--muted);
  text-align: center;
}
code {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12px;
}
.pager-btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--accent);
  border-radius: 8px;
  padding: 6px 16px;
  cursor: pointer;
  font-size: 13px;
}
.pager-btn:hover { border-color: var(--accent); }
</style>
