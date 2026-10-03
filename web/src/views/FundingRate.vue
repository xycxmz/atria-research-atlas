<script setup>
import { ref, onMounted, computed } from 'vue'
import { getRecent } from '../api'
import BaseChart from '../components/BaseChart.vue'
import DataState from '../components/DataState.vue'

const data = ref(null)
const error = ref(null)
const kind = ref('general')
const metric = ref('rate')

async function load() {
  error.value = null
  try {
    data.value = await getRecent()
  } catch (e) {
    error.value = e
  }
}

onMounted(load)

const KIND_LABEL = { general: '面上', youth: '青年 C 类', regional: '地区' }
const years = computed(() => (data.value?.RECENT_YEARS || []).filter(y => y.depts.length).map(y => y.year))

const fmt = (n, d = 0) => (n == null || n === '') ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: d })

// 分离两个职责（V2-004：此前 rate() 既要 {apply,funded} 又被传数值，
// 有效值 0.2 被当成 null 显示「—」）
// rateFromCounts: 申请/资助计数 → 比率；apply=0 或缺失返回 null
const rateFromCounts = (c) => (c && c.apply && c.funded != null && c.apply !== 0) ? c.funded / c.apply : null
// formatRate: 已是比率（含 null/0）→ 展示文本；0.0% 与缺测明确区分
const formatRate = (v) => (v == null ? '—' : (v * 100).toFixed(1) + '%')

// 选中类别 + 年度下的分学部指标
const rows = computed(() => {
  const out = []
  for (const y of data.value?.RECENT_YEARS || []) {
    if (!y.depts.length) continue
    for (const d of y.depts) {
      const c = d[kind.value]
      if (!c) continue
      const r = rateFromCounts(c)
      out.push({
        year: y.year,
        dept: d.dept,
        short: d.dept.replace('科学部', '').replace('数学物理', '数理').replace('工程与材料', '工材'),
        apply: c.apply,
        funded: c.funded,
        fundingWan: c.fundingWan,
        intensity: c.intensity ?? (c.fundingWan != null && c.funded ? c.fundingWan / c.funded : null),
        rate: r,
        approx: c.approx,
        derived: c.derived,
      })
    }
  }
  return out
})

// 资助率柱状图：按年分组，每个学部一条
const rateOption = computed(() => {
  const ys = years.value
  const rs = rows.value.filter(r => r.rate != null)
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (p) => `${p[0].axisValue}<br/>${p.map(x => `${x.marker} ${x.seriesName}: ${formatRate(x.value)}`).join('<br/>')}`,
    },
    legend: { type: 'scroll', top: 0 },
    grid: { left: '6%', right: '4%', bottom: '10%' },
    xAxis: { type: 'category', data: ys },
    yAxis: {
      type: 'value', name: '资助率',
      axisLabel: { formatter: (v) => (v * 100).toFixed(0) + '%' },
      max: 0.6,
    },
    series: (() => {
      const names = [...new Set(rs.map(r => r.short))]
      return names.map((name, i) => ({
        name, type: 'bar',
        data: ys.map(y => rs.find(r => r.short === name && r.year === y)?.rate ?? null),
        itemStyle: { color: ['#4cc2ff', '#bc8cff', '#7ee787', '#f0b429', '#ff7b72', '#56d4dd', '#d2a8ff', '#ffa657'][i % 8] },
      }))
    })(),
  }
})

// 全国面上/青年/地区 资助率时间序列
const nationalOption = computed(() => {
  const nh = data.value?.NATIONAL_HEADLINES || {}
  const ys = Object.keys(nh).map(Number).sort()
  const kinds = ['general', 'youth', 'regional']
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (p) => `${p[0].axisValue} 年<br/>${p.map(x => `${x.marker} ${x.seriesName}: ${formatRate(x.value)}`).join('<br/>')}`,
    },
    legend: { top: 0 },
    grid: { left: '7%', right: '5%', bottom: '10%' },
    xAxis: { type: 'category', data: ys },
    yAxis: {
      type: 'value', name: '资助率',
      axisLabel: { formatter: (v) => (v * 100).toFixed(0) + '%' },
    },
    series: kinds.map((k, i) => ({
      name: KIND_LABEL[k], type: 'line', smooth: true,
      data: ys.map(y => rateFromCounts(nh[y]?.[k]) ?? null),
      itemStyle: { color: ['#f0b429', '#4cc2ff', '#7ee787'][i] },
      lineStyle: { width: 2 },
    })),
  }
})

// 剪刀差：资助份额 − 申请份额（负值表示相对申请更难）
const scissorRows = computed(() => {
  const out = []
  const byYear = {}
  for (const r of rows.value) {
    if (r.apply == null) continue
    (byYear[r.year] ??= []).push(r)
  }
  for (const y of years.value) {
    const rs = byYear[y] || []
    const applySum = rs.reduce((s, r) => s + r.apply, 0)
    const fundedSum = rs.reduce((s, r) => s + (r.funded ?? 0), 0)
    for (const r of rs) {
      const applyShare = applySum ? r.apply / applySum : null
      const fundedShare = fundedSum && r.funded != null ? r.funded / fundedSum : null
      out.push({ ...r, gap: applyShare != null && fundedShare != null ? fundedShare - applyShare : null })
    }
  }
  return out
})

const latestYear = computed(() => years.value[years.value.length - 1])
const scissorLatest = computed(() => scissorRows.value.filter(r => r.year === latestYear.value).sort((a, b) => (a.gap ?? 0) - (b.gap ?? 0)))
</script>

<template>
  <div>
    <div class="page-header">
      <h2>资助率分析</h2>
      <span class="note">年度报告 / 集中接收口径 · 申请数与资助率合并库无法反推</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data">
      <div class="hint" style="margin-bottom: 16px;">
        这套数据来自基金委年度报告与项目指南的官方口径：申请数、资助项数、经费与资助率。
        与知识门户的项目清单不同源——门户给的是历年批准明细，这里给的是当年度申请竞争的汇总。
        资助率 = 资助项数 / 申请项数，不是库内项目数占比。
      </div>
      <div class="filters">
        <span style="align-self: center; font-size: 13px; color: var(--muted);">类别</span>
        <button v-for="(label, k) in KIND_LABEL" :key="k" :class="{ active: kind === k }" @click="kind = k">{{ label }}</button>
      </div>
      <div class="chart" style="margin-bottom: 16px;">
        <h3>全国三类项目资助率（2022–2026）</h3>
        <BaseChart :option="nationalOption" height="300px" />
      </div>
      <div class="chart" style="margin-bottom: 16px;">
        <h3>分学部「{{ KIND_LABEL[kind] }}」资助率</h3>
        <BaseChart :option="rateOption" height="340px" />
      </div>
      <div class="grid-2">
        <div class="chart">
          <h3>剪刀差：资助份额 − 申请份额（{{ latestYear }}）</h3>
          <p class="hint">负值表示该学部获批份额低于申请份额，相对更难。</p>
          <table>
            <thead>
              <tr><th>学部</th><th style="text-align:right">申请</th><th style="text-align:right">资助</th><th style="text-align:right">资助率</th><th style="text-align:right">差额</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in scissorLatest" :key="r.dept">
                <td>{{ r.short }}</td>
                <td style="text-align:right" class="tabular-nums">{{ fmt(r.apply) }}</td>
                <td style="text-align:right" class="tabular-nums">{{ fmt(r.funded) }}</td>
                <td style="text-align:right" class="tabular-nums">{{ r.rate == null ? '—' : (r.rate * 100).toFixed(1) + '%' }}</td>
                <td style="text-align:right; font-size: 12px;" :style="{ color: (r.gap ?? 0) < 0 ? 'var(--warn)' : 'var(--text)' }">
                  {{ r.gap == null ? '—' : (r.gap > 0 ? '+' : '') + (r.gap * 100).toFixed(1) + 'pt' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="chart">
          <h3>经费与强度（{{ latestYear }} · {{ KIND_LABEL[kind] }}）</h3>
          <p class="hint">经费单位万元；强度 = 经费 / 项数。</p>
          <table>
            <thead>
              <tr><th>学部</th><th style="text-align:right">经费(万元)</th><th style="text-align:right">强度</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in scissorLatest" :key="r.dept">
                <td>{{ r.short }}</td>
                <td style="text-align:right" class="tabular-nums">{{ fmt(r.fundingWan) }}</td>
                <td style="text-align:right" class="tabular-nums">{{ fmt(r.intensity, 1) }}</td>
              </tr>
            </tbody>
          </table>
          <div class="hint" style="margin-top: 8px;" v-if="scissorLatest.some(r => r.approx || r.derived)">
            标记 approx 的经费是报告里的约数；derived 的项数由官方同比增减推算，不是直接给出的绝对数。
          </div>
        </div>
      </div>
      </template>
    </DataState>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  align-items: center;
}
.filters button {
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 13px;
  cursor: pointer;
}
.filters button:hover { border-color: var(--accent); }
.filters button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.tabular-nums { font-variant-numeric: tabular-nums; }
</style>
