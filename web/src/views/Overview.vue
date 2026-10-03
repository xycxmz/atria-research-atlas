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

const meta = computed(() => data.value?.meta || {})
const fmt = (n, d = 0) => Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: d })
const strengthRows = computed(() => (adv.value?.strength_by_type || []).slice(0, 8))

const deptOption = computed(() => {
  const rows = data.value?.by_department || []
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} 条 ({d}%)' },
    legend: { type: 'scroll', bottom: 0 },
    series: [{
      type: 'pie',
      radius: ['38%', '66%'],
      avoidLabelOverlap: true,
      label: { show: false },
      data: rows.map(r => ({ name: r.division_name, value: r.count })),
    }],
  }
})

const typeOption = computed(() => {
  const rows = (data.value?.by_grant_type || []).slice(0, 8)
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '18%', right: '5%' },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: rows.map(r => r.grant_type).reverse() },
    series: [{
      type: 'bar',
      data: rows.map(r => r.count).reverse(),
      itemStyle: { color: '#4cc2ff' },
    }],
  }
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>总览</h2>
      <span class="note">库内 {{ fmt(meta.total_projects) }} 条 · {{ meta.year_min }}–{{ meta.year_max }}</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data">
      <div class="hint" style="margin-bottom: 16px;">
        本页全部统计是<strong>库内样本</strong>（{{ fmt(meta.total_projects) }} 条，批准年
        {{ meta.year_min }}–{{ meta.year_max }}），不是全国全量：按结题年度采入的样本在
        2017/2018 批准年覆盖约 93%，2021 年以后不足 2%（见覆盖率页）。全国分年总数请看「全国台账」。
      </div>
      <div class="cards">
        <div class="card">
          <div class="label">项目总数</div>
          <div class="value">{{ fmt(meta.total_projects) }}</div>
        </div>
        <div class="card">
          <div class="label">覆盖年份</div>
          <div class="value small">{{ meta.year_min }}–{{ meta.year_max }}</div>
        </div>
        <div class="card">
          <div class="label">总资助金额</div>
          <div class="value">{{ fmt(meta.total_amount_wan, 1) }} 万元</div>
        </div>
        <div class="card">
          <div class="label">依托单位</div>
          <div class="value small">{{ fmt(meta.distinct_institutions) }} 家</div>
        </div>
        <div class="card">
          <div class="label">项目负责人（去重姓名）</div>
          <div class="value small">{{ fmt(meta.distinct_pis) }} 个</div>
          <div class="label" style="margin-top: 6px;">按姓名去重，同名不同人会并算</div>
        </div>
        <div class="card">
          <div class="label">数据来源</div>
          <div class="value small">
            <span v-for="(count, src) in (data.by_source?.contributions || {})" :key="src" class="badge">
              {{ src }} {{ fmt(count) }}
            </span>
          </div>
          <div class="label" style="margin-top: 6px;">多来源重叠 {{ fmt(data.by_source?.multi_source_projects || 0) }} 条</div>
        </div>
      </div>
      <div class="grid-2">
        <div class="chart">
          <h3>学部分布</h3>
          <BaseChart :option="deptOption" />
        </div>
        <div class="chart">
          <h3>项目类型 Top 8</h3>
          <BaseChart :option="typeOption" />
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>类型 × 资助强度（万元/项）</h3>
        <p class="hint">均值受少数大额项目拉高（如联合基金 avg 144 vs 中位数 65），看分布要看中位数。</p>
        <table>
          <thead>
            <tr><th>类型</th><th style="text-align:right">项目数</th><th style="text-align:right">均值</th><th style="text-align:right">中位数</th><th style="text-align:right">合计(万元)</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in strengthRows" :key="r.grant_type">
              <td>{{ r.grant_type }}</td>
              <td style="text-align:right" class="tabular-nums">{{ fmt(r.count) }}</td>
              <td style="text-align:right" class="tabular-nums">{{ fmt(r.avg, 1) }}</td>
              <td style="text-align:right" class="tabular-nums">{{ fmt(r.median, 1) }}</td>
              <td style="text-align:right" class="tabular-nums">{{ fmt(r.total, 1) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      </template>
    </DataState>
  </div>
</template>
