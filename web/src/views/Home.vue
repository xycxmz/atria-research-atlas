<script setup>
import { ref, watch, onMounted } from 'vue'
import { getAnalysis } from '../api'
import DataState from '../components/DataState.vue'

const emit = defineEmits(['go'])

const data = ref(null)
const error = ref(null)
const lastQuery = ref(null)

async function load() {
  error.value = null
  try {
    data.value = await getAnalysis()
  } catch (e) {
    error.value = e
  }
}

onMounted(async () => {
  load()
  // 「继续上次」只从本地取最近一次已应用查询（V2-009：最近查询只保存本地）
  try {
    const raw = localStorage.getItem('nsfc_last_query')
    lastQuery.value = raw ? JSON.parse(raw) : null
  } catch (e) {
    lastQuery.value = null
  }
})

const topInst = ref(null)
watch(data, (d) => {
  const rows = (d?.top_institutions || []).filter((r) => r.institution)
  topInst.value = rows.length ? rows[0].institution : null
}, { immediate: true })
</script>

<template>
  <div>
    <div class="page-header">
      <h2>发现问题</h2>
      <span class="note">从真实数据出发的可复现入口</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data">
        <div class="hint" style="margin-bottom: 16px;">
          本站是<strong>可追溯的库内样本分析台</strong>：{{ data.meta.total_projects.toLocaleString('zh-CN') }} 条
          （批准年 {{ data.meta.year_min }}–{{ data.meta.year_max }}），不是全国全量——按结题年度采入，
          2017/2018 批准年覆盖约 93%，2021 年后不足 2%。下面的每个入口都带明确范围，点进去看到的项目与来源一一对应。
        </div>
        <div class="cards">
          <button class="card question" @click="emit('go', 'explorer', { year: '2018', dept: '医学科学部', page: '1' })">
            <div class="label">问题一 · 学科构成</div>
            <div class="value small">2018 年库内样本中，医学科学部的项目类别与关键词构成是什么？</div>
            <div class="qnote">→ 数据检索 · 已带 year=2018&amp;dept=医学科学部</div>
          </button>
          <button class="card question" @click="emit('go', 'explorer', { inst: topInst || '', page: '1' })">
            <div class="label">问题二 · 单位项目</div>
            <div class="value small">查看头部单位「{{ topInst || '加载中…' }}」在库内有哪些项目，并打开字段来源。</div>
            <div class="qnote">→ 数据检索 · 已带该单位筛选</div>
          </button>
          <button class="card question" @click="emit('go', 'coverage')">
            <div class="label">问题三 · 口径对照</div>
            <div class="value small">门户与年报的 2023 批准基数分别是多少？库内能下钻多少条？</div>
            <div class="qnote">→ 覆盖率 · 双口径并列，不相加</div>
          </button>
        </div>
        <div class="cards">
          <button class="card question" v-if="lastQuery" @click="emit('go', 'explorer', lastQuery)">
            <div class="label">继续上次</div>
            <div class="value small">恢复最近一次已应用查询（{{ lastQuery.q || lastQuery.dept || lastQuery.inst || '全部' }}）</div>
            <div class="qnote">→ 仅保存在本机 localStorage</div>
          </button>
          <button class="card question" @click="emit('go', 'national')">
            <div class="label">全国背景</div>
            <div class="value small">门户 1986–2025 全量聚合与年报口径，作为样本分析的对照背景。</div>
            <div class="qnote">→ 全国台账 / 资助率</div>
          </button>
        </div>
      </template>
    </DataState>
  </div>
</template>

<style scoped>
.card.question {
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
  /* button 原生样式重置为卡片观感（V2R2-003 键盘可达） */
  font: inherit;
  text-align: left;
  color: inherit;
  width: 100%;
}
.card.question:hover, .card.question:focus-visible {
  border-color: var(--accent);
  transform: translateY(-1px);
  outline: none;
}
.card.question:focus-visible {
  box-shadow: 0 0 0 2px var(--accent);
}
.qnote {
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--muted);
}
</style>
