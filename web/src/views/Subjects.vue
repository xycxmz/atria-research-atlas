<script setup>
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { getAnalysis, getAdvanced } from '../api'
import BaseChart from '../components/BaseChart.vue'
import DataState from '../components/DataState.vue'
import { getScope, setScope, registerApplyScope, unregisterApplyScope, host } from '../modules/scope'

const data = ref(null)
const adv = ref(null)
const error = ref(null)

async function load() {
  error.value = null
  try {
    const [a, b] = await Promise.all([getAnalysis(), getAdvanced()])
    data.value = a
    adv.value = b
  } catch (e) {
    error.value = e
  }
}

onMounted(() => {
  load()
  // 本页只支持学部维度（V2R2-001）；年份/类别在本页不生效，ScopeBar 会标「未应用」
  registerApplyScope((s) => { deptFilter.value = s.division }, ['division'])
})
onBeforeUnmount(unregisterApplyScope)

const fmt = (n, d = 0) => Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: d })

const l1Rows = computed(() => data.value?.top_subjects_l1 || [])
const l2Rows = computed(() => adv.value?.top_subjects_l2 || [])
const l1Meta = computed(() => data.value?.top_subjects_l1_meta || [])
const l2Meta = computed(() => adv.value?.top_subjects_l2_meta || [])
const deptFilter = ref('')

const l1Filtered = computed(() => {
  const rows = l1Rows.value
  if (!deptFilter.value) return rows
  return rows.filter(r => r.division_name === deptFilter.value)
})
const l2Filtered = computed(() => {
  const rows = l2Rows.value
  if (!deptFilter.value) return rows
  return rows.filter(r => r.division_name === deptFilter.value)
})
// 未选学部时图表按全库计数取 Top 15（全局榜）；选中后即为该学部 Top 15
const l1Shown = computed(() => [...l1Filtered.value].sort((a, b) => b.count - a.count).slice(0, 15))
const l2Shown = computed(() => [...l2Filtered.value].sort((a, b) => b.count - a.count).slice(0, 15))
const l1MetaOf = computed(() => l1Meta.value.find(m => m.scope === deptFilter.value) || null)
const l2MetaOf = computed(() => l2Meta.value.find(m => m.scope === deptFilter.value) || null)
const scopeLabel = computed(() => deptFilter.value ? '（' + deptFilter.value + '）' : '（全库）')
const deptOptions = computed(() => {
  const s = new Set()
  for (const r of l1Rows.value) if (r.division_name) s.add(r.division_name)
  for (const r of l2Rows.value) if (r.division_name) s.add(r.division_name)
  return [...s].sort()
})

// W4：本页学部筛选与全局 scope 双向同步（同值守卫防回环）。
// immediate：从检索页带 scope 进来时 sc.division 已有值，同步必须在挂载时生效，
// 否则图表停留在全库（V2R2-001 评审证据「学部变全部」）
const sc = getScope()
watch(() => sc.division, (d) => { if (d && d !== deptFilter.value) deptFilter.value = d }, { immediate: true })
watch(deptFilter, (d) => { setScope({ division: d }) })

// V2R2-001：维度声明（供 ScopeBar 与测试核对）
const scopeSupport = ['division']

// W5：点一级学科柱 → 带同口径筛选转检索；二级学科按下钻到一级（检索页只有 L1 过滤）
function onL1Click(e) {
  const row = l1Shown.value.find(r => r.subject_l1 === e.name)
  if (!row) return
  host.go?.('explorer', { subj: row.subject_l1, dept: row.division_name, page: '1' })
}
function onL2Click(e) {
  const row = l2Shown.value.find(r => r.subject_l2 === e.name)
  if (!row) return
  host.go?.('explorer', { subj: row.subject_l1, dept: row.division_name, page: '1' })
}

const l1Option = computed(() => {
  const rows = [...l1Shown.value].reverse()
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (p) => `${p[0].name}<br/>${fmt(p[0].value)} 条`,
    },
    grid: { left: '30%', right: '6%' },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: rows.map(r => `${r.subject_l1}`),
      axisLabel: { width: 140, overflow: 'truncate' },
    },
    series: [{
      type: 'bar', data: rows.map(r => r.count),
      itemStyle: { color: '#bc8cff' },
    }],
  }
})

const l2Option = computed(() => {
  const rows = [...l2Shown.value].reverse()
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (p) => {
        const r = rows[p[0].dataIndex]
        return `${r.division_name} / ${r.subject_l1} / ${r.subject_l2}<br/>${fmt(r.count)} 条 · ${fmt(r.amount, 1)} 万元`
      },
    },
    grid: { left: '30%', right: '6%' },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: rows.map(r => r.subject_l2),
      axisLabel: { width: 140, overflow: 'truncate' },
    },
    series: [{
      type: 'bar', data: rows.map(r => r.count),
      itemStyle: { color: '#56d4dd' },
    }],
  }
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>学科分布</h2>
      <span class="note">每学部 Top 15 · 先按学部范围排名（V2-003）</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data && adv">
      <div class="hint" style="margin-bottom: 16px;">
        学科名由申请代码映射而来（2019 学科树 + 门户现行一级代码），
        仅 1,845 条来自来源页面原文，其余为代码推导，未映射的代码（如 C1307、H3302 等门户新增二级代码）留空。
      </div>
      <div class="filters" style="margin-bottom: 16px;">
        <span style="font-size: 13px; color: var(--muted);">学部</span>
        <select v-model="deptFilter" style="background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 6px 10px; font-size: 13px;">
          <option value="">全部</option>
          <option v-for="d in deptOptions" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
      <div v-if="deptFilter" class="hint" style="margin-bottom: 16px;">
        <template v-if="l1MetaOf">
          一级学科：{{ deptFilter }} 共 {{ l1MetaOf.candidates }} 个名称，展示前 {{ l1MetaOf.shown }} 个（合计 {{ fmt(l1MetaOf.shown_count) }} 条项目）；
          其余 {{ l1MetaOf.candidates - l1MetaOf.shown }} 个名称合计 {{ fmt(l1MetaOf.other_count) }} 条；
          另有 {{ fmt(l1MetaOf.unknown_count) }} 条项目无一级学科名。
        </template>
        <template v-if="l2MetaOf">
          二级学科：{{ l2MetaOf.candidates }} 个名称中展示前 {{ l2MetaOf.shown }} 个，未展示名称合计 {{ fmt(l2MetaOf.other_count) }} 条项目。
        </template>
      </div>
      <div class="hint" v-else style="margin-bottom: 16px;">
        未选学部时图表为全库计数 Top 15；选择学部后即为该学部范围内 Top 15，并可按下方明细对账。
      </div>
      <div class="grid-2">
        <div class="chart">
          <h3>一级学科 Top 15{{ scopeLabel }}</h3>
          <BaseChart :option="l1Option" height="380px" @click="onL1Click"
                     :download-name="'一级学科Top15_' + (deptFilter || '全库')" />
        </div>
        <div class="chart">
          <h3>二级学科 Top 15{{ scopeLabel }}</h3>
          <BaseChart :option="l2Option" height="380px" @click="onL2Click"
                     :download-name="'二级学科Top15_' + (deptFilter || '全库')" />
          <div class="hint">点击二级学科柱会<b>扩大到父级（一级学科）范围</b>转检索——检索页过滤粒度是一级学科，不是同粒度下钻。</div>
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>二级学科明细（按学部 Top 15）</h3>
        <table>
          <thead>
            <tr><th>学部</th><th>一级学科</th><th>二级学科</th><th style="text-align:right">立项数</th><th style="text-align:right">金额(万元)</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in l2Filtered" :key="i">
              <td><span class="badge">{{ r.division_name }}</span></td>
              <td>{{ r.subject_l1 }}</td>
              <td>{{ r.subject_l2 }}</td>
              <td style="text-align:right">{{ fmt(r.count) }}</td>
              <td style="text-align:right">{{ fmt(r.amount, 1) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      </template>
    </DataState>
  </div>
</template>
