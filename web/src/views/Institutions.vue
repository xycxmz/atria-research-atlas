<script setup>
import { ref, onMounted, computed } from 'vue'
import { getAnalysis, getAdvanced } from '../api'
import BaseChart from '../components/BaseChart.vue'
import DataState from '../components/DataState.vue'

const data = ref(null)
const adv = ref(null)
const error = ref(null)
const topN = ref(20)

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

onMounted(load)

const fmt = (n, d = 0) => Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: d })

const instRows = computed(() => (data.value?.top_institutions || []).slice(0, topN.value))

const instOption = computed(() => {
  const rows = instRows.value.slice().reverse()
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (p) => `${p[0].name}<br/>立项 ${fmt(p[0].value)} 条 · ${fmt(p[0].data?.amount ?? 0, 1)} 万元`,
    },
    grid: { left: '24%', right: '8%' },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: rows.map(r => r.institution) },
    series: [{
      type: 'bar',
      data: rows.map(r => ({ value: r.count, amount: r.amount })),
      itemStyle: { color: '#4cc2ff' },
    }],
  }
})

const instDeptRows = computed(() => adv.value?.top_institution_dept || [])

// TOP 单位年度趋势：看头部单位的立项节奏而非只看存量
const trendOption = computed(() => {
  const m = adv.value?.top_institution_years || {}
  const insts = m.institutions || []
  const years = m.years || []
  const colors = ['#4cc2ff', '#bc8cff', '#7ee787', '#f0b429', '#ff7b72',
                  '#56d4dd', '#d2a8ff', '#ffa657', '#f778ba', '#79c0ff']
  return {
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0, data: insts },
    grid: { left: '7%', right: '5%', bottom: '12%' },
    xAxis: { type: 'category', data: years.map(String) },
    yAxis: { type: 'value', name: '立项数' },
    series: insts.map((name, i) => ({
      name, type: 'line', smooth: true,
      data: (m.counts || [])[i] || [],
      itemStyle: { color: colors[i % colors.length] },
      lineStyle: { width: 1.8 },
    })),
  }
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>单位排行</h2>
      <span class="note">依托单位立项数 Top {{ topN }}</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data && adv">
      <div class="filters">
        <label style="color: var(--text-dim); font-size: 13px;">显示数量</label>
        <select v-model.number="topN">
          <option :value="10">Top 10</option>
          <option :value="20">Top 20</option>
          <option :value="30">Top 30</option>
        </select>
      </div>
      <div class="grid-2">
        <div class="chart">
          <h3>单位立项数排行</h3>
          <BaseChart :option="instOption" :height="Math.max(320, topN * 24) + 'px'" />
        </div>
        <div class="chart">
          <h3>单位 × 主导学部 Top 15</h3>
          <table>
            <thead>
              <tr><th>单位</th><th>学部</th><th style="text-align:right">立项数</th></tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in instDeptRows" :key="i">
                <td>{{ r.institution }}</td>
                <td><span class="badge">{{ r.division_name }}</span></td>
                <td style="text-align:right">{{ fmt(r.count) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>Top 10 单位年度立项趋势</h3>
        <BaseChart :option="trendOption" height="340px" />
        <div class="hint">
          按批准年度。曲线的高低不等于单位强弱——受采集范围约束
          （库内 2017/2018 批准年样本最齐，两端年份覆盖低，详见覆盖率页）。
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>单位明细</h3>
        <table>
          <thead>
            <tr><th>#</th><th>单位</th><th style="text-align:right">立项数</th><th style="text-align:right">资助金额(万元)</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in instRows" :key="r.institution">
              <td style="color: var(--text-dim)">{{ i + 1 }}</td>
              <td>{{ r.institution }}</td>
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
