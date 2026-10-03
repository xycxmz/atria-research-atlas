<script setup>
import { ref, onMounted, computed } from 'vue'
import { getAnalysis, getAdvanced } from '../api'
import BaseChart from '../components/BaseChart.vue'
import DataState from '../components/DataState.vue'

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

const trendOption = computed(() => {
  const rows = data.value?.by_year || []
  const years = rows.map(r => r.year)
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['立项数', '资助金额(万元)'], top: 0 },
    grid: { left: '6%', right: '6%', bottom: '10%' },
    xAxis: { type: 'category', data: years },
    yAxis: [
      { type: 'value', name: '立项数', position: 'left' },
      { type: 'value', name: '金额(万元)', position: 'right' },
    ],
    series: [
      {
        name: '立项数', type: 'bar', data: rows.map(r => r.count),
        itemStyle: { color: '#4cc2ff' },
      },
      {
        name: '资助金额(万元)', type: 'line', yAxisIndex: 1,
        data: rows.map(r => Number((r.amount || 0).toFixed(1))),
        itemStyle: { color: '#f0b429' }, lineStyle: { width: 2 },
      },
    ],
  }
})

const yoyOption = computed(() => {
  const rows = (adv.value?.year_yoy || []).filter(r => r.yoy != null)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (p) => {
        const r = rows[p[0].dataIndex]
        return `${r.year}<br/>立项数 ${fmt(r.count)}<br/>环比 ${(r.yoy * 100).toFixed(1)}%`
      },
    },
    grid: { left: '8%', right: '5%', bottom: '10%' },
    xAxis: { type: 'category', data: rows.map(r => r.year) },
    yAxis: {
      type: 'value', name: '环比增长率',
      axisLabel: { formatter: (v) => (v * 100).toFixed(0) + '%' },
    },
    series: [{
      type: 'bar',
      data: rows.map(r => r.yoy),
      itemStyle: {
        color: (p) => (p.value >= 0 ? '#7ee787' : '#ff7b72'),
      },
      label: { show: true, formatter: (p) => (p.value * 100).toFixed(1) + '%' },
    }],
  }
})

const strengthOption = computed(() => {
  const rows = adv.value?.amount_strength || []
  return {
    tooltip: { trigger: 'axis', formatter: (p) => `${p[0].axisValue}<br/>${p.map(x => `${x.marker} ${x.seriesName}: ${x.value} 万元`).join('<br/>')}` },
    legend: { data: ['平均强度', '中位数'], top: 0 },
    grid: { left: '8%', right: '5%', bottom: '10%' },
    xAxis: { type: 'category', data: rows.map(r => r.year) },
    yAxis: { type: 'value', name: '万元/项' },
    series: [
      { name: '平均强度', type: 'line', data: rows.map(r => r.avg), itemStyle: { color: '#4cc2ff' } },
      { name: '中位数', type: 'line', data: rows.map(r => r.median), itemStyle: { color: '#bc8cff' } },
    ],
  }
})

const distOption = computed(() => {
  const d = adv.value?.amount_distribution || {}
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '6%', right: '5%', bottom: '12%' },
    xAxis: { type: 'category', data: d.bins || [], name: '万元', axisLabel: { rotate: 30 } },
    yAxis: { type: 'value', name: '项目数' },
    series: [{
      type: 'bar', data: d.counts || [],
      itemStyle: { color: '#7ee787' },
    }],
  }
})

const closeOption = computed(() => {
  const rows = data.value?.by_close_year || []
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (p) => `${p[0].axisValue} 年结题<br/>${fmt(p[0].value)} 条`,
    },
    grid: { left: '8%', right: '5%', bottom: '10%' },
    xAxis: { type: 'category', data: rows.map(r => r.year) },
    yAxis: { type: 'value', name: '结题项目数' },
    series: [{
      type: 'bar', data: rows.map(r => r.count),
      itemStyle: { color: '#56d4dd' },
      label: { show: true, position: 'top', formatter: (p) => fmt(p.value) },
    }],
  }
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>年份趋势</h2>
      <span class="note">立项数与资助金额双轴 · 环比 · 资助强度 · 结题年度</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data && adv">
      <div class="chart" style="margin-bottom: 16px;">
        <h3>历年立项数与资助金额（按批准年度）</h3>
        <BaseChart :option="trendOption" height="340px" />
        <div class="hint">
          曲线形状首先反映库内样本的构成（2017/2018 批准年覆盖约 93%，两端年份覆盖低），
          不能读作全国立项增减；全国分年立项数见「全国台账」。
        </div>
      </div>
      <div class="chart" style="margin-bottom: 16px;">
        <h3>按结题年度统计</h3>
        <BaseChart :option="closeOption" height="300px" />
        <div class="hint">
          立项数与结题数不是同一批项目：柱状图是按批准年度的新立项，这里是该年完成结题的项目。
          库内绝大多数记录来自结题年度 2020–2023 的门户采集（2020–2022 已收齐，
          2023 年只收到 15,140/42,153），所以这条线直接反映采集进度。
        </div>
      </div>
      <div class="grid-2">
        <div class="chart">
          <h3>年度环比增长率</h3>
          <BaseChart :option="yoyOption" />
          <div class="hint" v-if="(adv.year_yoy || []).filter(r => r.yoy != null).length === 0">
            至少需要两年数据才能计算环比
          </div>
        </div>
        <div class="chart">
          <h3>平均资助强度（万元/项）</h3>
          <BaseChart :option="strengthOption" />
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>单项金额分布</h3>
        <BaseChart :option="distOption" />
      </div>
      </template>
    </DataState>
  </div>
</template>
