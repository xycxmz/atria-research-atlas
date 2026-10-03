<script setup>
import { ref, onMounted, computed } from 'vue'
import { getAnalysis, getAdvanced } from '../api'
import BaseChart from '../components/BaseChart.vue'
import DataState from '../components/DataState.vue'
import { host } from '../modules/scope'

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

onMounted(load)

const fmt = (n, d = 0) => Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: d })

const deptRows = computed(() => data.value?.by_department || [])

const amountOption = computed(() => {
  const rows = deptRows.value.slice().sort((a, b) => (b.amount || 0) - (a.amount || 0))
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '20%', right: '6%' },
    xAxis: { type: 'value', name: '万元' },
    yAxis: { type: 'category', data: rows.map(r => r.division_name).reverse() },
    series: [{
      type: 'bar', data: rows.map(r => Number((r.amount || 0).toFixed(1))).reverse(),
      itemStyle: { color: '#f0b429' },
    }],
  }
})

// 学部 × 年份 堆叠柱状图
const stackOption = computed(() => {
  const m = adv.value?.dept_year_matrix || {}
  const depts = m.departments || []
  const years = m.years || []
  const colors = ['#4cc2ff', '#7ee787', '#f0b429', '#ff7b72', '#bc8cff',
                  '#79c0ff', '#d2a8ff', '#ffa657', '#56d4dd', '#f778ba']
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const y = params[0].axisValue
        const total = params.reduce((s, p) => s + p.value, 0)
        return `${y} 年 · 合计 ${fmt(total)} 条<br/>` +
          params.map(p => `${p.marker} ${p.seriesName}: ${fmt(p.value)}`).join('<br/>')
      },
    },
    legend: { type: 'scroll', bottom: 0, data: depts },
    grid: { left: '7%', right: '5%', bottom: '14%' },
    xAxis: { type: 'category', data: years },
    yAxis: { type: 'value', name: '立项数' },
    series: depts.map((d, i) => ({
      name: d, type: 'bar', stack: 'total',
      data: (m.counts || [])[i] || [],
      itemStyle: { color: colors[i % colors.length] },
    })),
  }
})

// 结题年度 × 批准年度 矩阵热力图：揭示采集结构（结题年 2020–2023 覆盖哪些批准年）
const closeHeatOption = computed(() => {
  const m = adv.value?.close_award_matrix || {}
  const closeYears = m.close_years || []
  const awardYears = m.award_years || []
  const seriesData = []
  let maxV = 0
  ;(m.counts || []).forEach((row, i) => {
    row.forEach((v, j) => {
      seriesData.push([j, i, v])
      if (v > maxV) maxV = v
    })
  })
  return {
    tooltip: {
      position: 'top',
      formatter: (p) => `${awardYears[p.value[0]]} 批准 · ${closeYears[p.value[1]]} 结题<br/>${fmt(p.value[2])} 条`,
    },
    grid: { left: '9%', right: '6%', bottom: '12%', top: '8%' },
    xAxis: { type: 'category', data: awardYears, name: '批准年度', splitArea: { show: true } },
    yAxis: { type: 'category', data: closeYears, name: '结题年度', splitArea: { show: true } },
    visualMap: {
      min: 0, max: maxV, calculable: true, orient: 'horizontal',
      left: 'center', bottom: 0,
      inRange: { color: ['#1a2129', '#1f6feb', '#4cc2ff', '#7ee787'] },
    },
    series: [{
      type: 'heatmap', data: seriesData,
      label: { show: true, fontSize: 10 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
    }],
  }
})

// 学部 × 资助类别 构成对比（青年:面上比反映学科人员年龄结构）
const typeStackOption = computed(() => {
  const m = adv.value?.dept_type_matrix || {}
  const depts = m.departments || []
  const types = m.types || []
  const counts = m.counts || []
  const colors = ['#4cc2ff', '#bc8cff', '#7ee787', '#f0b429']
  // counts 按 [学部][类别] 存放，序列需要转置成 [类别][学部]
  const seriesData = (ti) => depts.map((_, di) => (counts[di] || [])[ti] || 0)
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const d = params[0].axisValue
        const ratio = (m.youth_ratio || [])[params[0].dataIndex]
        const total = params.reduce((s, p) => s + p.value, 0)
        return `${d} · 合计 ${fmt(total)} 条<br/>` +
          params.map(p => `${p.marker} ${p.seriesName}: ${fmt(p.value)}`).join('<br/>') +
          (ratio != null ? `<br/>青年:面上 = ${ratio}` : '')
      },
    },
    legend: { type: 'scroll', bottom: 0 },
    grid: { left: '10%', right: '5%', bottom: '14%' },
    xAxis: { type: 'category', data: depts, axisLabel: { interval: 0, rotate: 20 } },
    yAxis: { type: 'value', name: '立项数' },
    series: types.map((t, i) => ({
      name: t, type: 'bar', stack: 't',
      data: seriesData(i),
      itemStyle: { color: colors[i % colors.length] },
    })),
  }
})

const heatOption = computed(() => {
  const m = adv.value?.dept_year_matrix || {}
  const depts = m.departments || []
  const years = m.years || []
  const seriesData = []
  let maxV = 0
  depts.forEach((d, i) => {
    (m.counts || [])[i]?.forEach((v, j) => {
      seriesData.push([j, i, v])
      if (v > maxV) maxV = v
    })
  })
  return {
    tooltip: { position: 'top', formatter: (p) => `${years[p.value[0]]} × ${depts[p.value[1]]}<br/>${fmt(p.value[2])} 条<br/><span style="color:#8b98a8">点击转检索</span>` },
    grid: { left: '16%', right: '8%', bottom: '12%', top: '8%' },
    xAxis: { type: 'category', data: years, splitArea: { show: true } },
    yAxis: { type: 'category', data: depts, splitArea: { show: true } },
    visualMap: {
      min: 0, max: maxV, calculable: true, orient: 'horizontal',
      left: 'center', bottom: 0,
      inRange: { color: ['#1a2129', '#1f6feb', '#4cc2ff', '#7ee787'] },
    },
    series: [{
      type: 'heatmap', data: seriesData,
      label: { show: true, fontSize: 11 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
    }],
  }
})

// W5：热力图单元格 = 学部 × 批准年，带同口径转检索
function onHeatClick(e) {
  const m = adv.value?.dept_year_matrix || {}
  const dept = (m.departments || [])[e.value[1]]
  const year = (m.years || [])[e.value[0]]
  if (!dept) return
  host.go?.('explorer', { dept, year: String(year), page: '1' })
}

// 学部 × 年份 堆叠柱：点某个学部的柱（seriesName=学部，axisValue=年份）
function onStackClick(e) {
  host.go?.('explorer', { dept: e.seriesName, year: String(e.name), page: '1' })
}

// 学部 × 类别构成：点柱（axisValue=学部，seriesName=类别）
function onTypeStackClick(e) {
  host.go?.('explorer', { dept: e.name, type: e.seriesName, page: '1' })
}
</script>

<template>
  <div>
    <div class="page-header">
      <h2>学部分布</h2>
      <span class="note">立项数 · 资助金额 · 学部×年份交叉</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data && adv">
      <div class="chart" style="margin-bottom: 16px;">
        <h3>学部 × 年份 立项数（堆叠）</h3>
        <BaseChart :option="stackOption" height="360px" @click="onStackClick" download-name="学部年份堆叠" />
        <div class="hint">点击柱段按该学部 × 年份转检索（库内样本，不是全国明细）。</div>
      </div>
      <div class="grid-2">
        <div class="chart">
          <h3>学部 × 年份 热力图</h3>
          <BaseChart :option="heatOption" height="340px" @click="onHeatClick" download-name="学部年份热力图" />
        </div>
        <div class="chart">
          <h3>各学部资助金额（万元）</h3>
          <BaseChart :option="amountOption" height="340px" download-name="学部金额" />
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>学部 × 资助类别构成</h3>
        <BaseChart :option="typeStackOption" height="360px" @click="onTypeStackClick" download-name="学部类别构成" />
        <div class="hint">
          青年:面上 = 青年科学基金项目（C类）项目数 ÷ 面上项目数，只是两类项目数量的比，
          不反映学科人员的年龄或规模结构。悬停可见各学部数值。不是学科评价。
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>结题年度 × 批准年度（采集结构）</h3>
        <BaseChart :option="closeHeatOption" height="300px" />
        <div class="hint">
          这张热力图解释覆盖率的形状：库内数据按结题年度采入（2020–2023），一个批准年的项目
          分散在之后若干个结题年度里。2020 批准年的项目大多落在 close 2023+（门户接口已下线，
          无法补采），所以 2020 年覆盖只有 16.7%；2021–2023 批准年的项目处于当前采集窗口之外，
          是否结题不由本库判断——是空白而非采漏。
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>学部明细表</h3>
        <table>
          <thead>
            <tr><th>学部</th><th style="text-align:right">立项数</th><th style="text-align:right">资助金额(万元)</th><th style="text-align:right">平均强度(万元/项)</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in deptRows" :key="r.division_name">
              <td>{{ r.division_name }}</td>
              <td style="text-align:right">{{ fmt(r.count) }}</td>
              <td style="text-align:right">{{ fmt(r.amount, 1) }}</td>
              <td style="text-align:right">{{ r.valid_n ? fmt(r.amount / r.valid_n, 1) : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <div class="hint">
          平均强度 = 金额合计 ÷ 有金额的项目数（金额缺失的项目不计入分母，故可能高于
          「金额合计 ÷ 立项数」）。金额为推断值（库标记 amount_inferred=1）的项目照常计入，
          详见数据质量页与项目详情。
        </div>
      </div>
      </template>
    </DataState>
  </div>
</template>
