<script setup>
import { ref, onMounted, computed } from 'vue'
import { getNational } from '../api'
import BaseChart from '../components/BaseChart.vue'
import DataState from '../components/DataState.vue'

const data = ref(null)
const error = ref(null)
const tab = ref('trend')

async function load() {
  error.value = null
  try {
    data.value = await getNational()
  } catch (e) {
    error.value = e
  }
}

onMounted(load)

const fmt = (n, d = 0) => Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: d })

// 历年资助 + 结题双线（两条线不是同一批项目）
const trendOption = computed(() => {
  const g = data.value?.grants || []
  const closeBy = new Map((data.value?.conclusions || []).map(r => [r.year, r.count]))
  const years = g.map(r => r.year)
  return {
    tooltip: {
      trigger: 'axis',
      formatter: (p) => `${p[0].axisValue} 年<br/>${p.map(x => `${x.marker} ${x.seriesName}: ${fmt(x.value)}`).join('<br/>')}`,
    },
    legend: { data: ['批准立项', '当年结题'], top: 0 },
    grid: { left: '7%', right: '5%', bottom: '10%' },
    xAxis: { type: 'category', data: years, axisLabel: { interval: 3 } },
    yAxis: { type: 'value', name: '项数' },
    series: [
      { name: '批准立项', type: 'line', data: g.map(r => r.count), smooth: true, itemStyle: { color: '#f0b429' }, lineStyle: { width: 2 } },
      {
        name: '当年结题', type: 'line', data: years.map(y => closeBy.get(y) ?? null),
        smooth: true, itemStyle: { color: '#4cc2ff' }, lineStyle: { width: 2 }, connectNulls: false,
      },
    ],
  }
})

// 分学部堆叠柱状图（2009–2023）
const DEPTS = ['数理科学部', '化学科学部', '生命科学部', '地球科学部', '工程与材料科学部', '信息科学部', '管理科学部', '医学科学部']
const DEPT_COLORS = ['#4cc2ff', '#bc8cff', '#7ee787', '#f0b429', '#ff7b72', '#56d4dd', '#d2a8ff', '#ffa657']

const deptOption = computed(() => {
  const rows = data.value?.yearDept || []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { type: 'scroll', top: 0 },
    grid: { left: '6%', right: '4%', bottom: '10%' },
    xAxis: { type: 'category', data: rows.map(r => r.year) },
    yAxis: { type: 'value', name: '项数' },
    series: DEPTS.map((dept, i) => ({
      name: dept, type: 'bar', stack: 'a',
      data: rows.map(r => r.items.find(x => x.name === dept)?.count ?? 0),
      itemStyle: { color: DEPT_COLORS[i] },
    })),
  }
})

// 类别累计构成
const typeRows = computed(() => [...(data.value?.typeTotals || [])].sort((a, b) => b.count - a.count))
const typeTotal = computed(() => typeRows.value.reduce((s, r) => s + r.count, 0))

// 131 个二级学科（可搜索）
const query = ref('')
const disciplineRows = computed(() => {
  const rows = [...(data.value?.disciplines || [])].sort((a, b) => b.count - a.count)
  const q = query.value.trim()
  if (!q) return rows
  return rows.filter(r => r.code.toLowerCase().includes(q.toLowerCase()) || r.name.includes(q) || r.dept.includes(q))
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>全国立项台账</h2>
      <span class="note">基金委知识门户公开统计 · 与本地库同源 · 快照 {{ data?.snapshot }}</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data">
      <div class="cards">
        <div class="card">
          <div class="label">累计批准立项</div>
          <div class="value">{{ fmt(data.totals.fundedProjects) }}</div>
        </div>
        <div class="card">
          <div class="label">累计结题</div>
          <div class="value">{{ fmt(data.totals.conclusions) }}</div>
        </div>
        <div class="card">
          <div class="label">结题报告</div>
          <div class="value">{{ fmt(data.totals.reports) }}</div>
        </div>
        <div class="card">
          <div class="label">成果记录</div>
          <div class="value small">{{ fmt(data.totals.achievements) }}</div>
        </div>
      </div>
      <div class="filters">
        <button :class="{ active: tab === 'trend' }" @click="tab = 'trend'">历年规模</button>
        <button :class="{ active: tab === 'dept' }" @click="tab = 'dept'">分学部</button>
        <button :class="{ active: tab === 'type' }" @click="tab = 'type'">类别构成</button>
        <button :class="{ active: tab === 'disc' }" @click="tab = 'disc'">二级学科</button>
      </div>

      <div v-if="tab === 'trend'" class="chart">
        <h3>批准立项与当年结题（1986–2025）</h3>
        <BaseChart :option="trendOption" height="360px" />
        <div class="hint">
          两条线不是同一批项目：金线是批准年度的新立项，蓝线是该年完成结题的项目。
          本地合并库 {{ fmt(165200) }} 条是其中的可下钻样本（结题年度 2020–2023 为主）。
        </div>
      </div>

      <div v-else-if="tab === 'dept'" class="chart">
        <h3>分学部立项（2009–2023）</h3>
        <BaseChart :option="deptOption" height="360px" />
        <div class="hint">2009 年以前门户只给总数，没有分学部明细。</div>
      </div>

      <div v-else-if="tab === 'type'" class="chart">
        <h3>资助类别累计（全部年份）</h3>
        <table>
          <thead>
            <tr><th>类别</th><th style="text-align:right">累计项数</th><th style="text-align:right">占比</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in typeRows" :key="r.name">
              <td>{{ r.name }}</td>
              <td style="text-align:right" class="tabular-nums">{{ fmt(r.count) }}</td>
              <td style="text-align:right; color: var(--muted)">{{ (r.count / typeTotal * 100).toFixed(1) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else class="chart">
        <h3>二级申请代码（门户旭日图，{{ data.disciplines.length }} 个）</h3>
        <p class="hint">数量是累计资助项，不是单年清单。</p>
        <input v-model="query" placeholder="搜代码或名称，例如 A01、肿瘤" style="width: 280px; margin-bottom: 10px;" />
        <p class="hint">{{ fmt(disciplineRows.length) }} 个代码</p>
        <div style="max-height: 480px; overflow: auto; border: 1px solid var(--border); border-radius: 8px;">
          <table>
            <thead style="position: sticky; top: 0; background: var(--panel-2);">
              <tr><th>代码</th><th>名称</th><th>学部</th><th style="text-align:right">累计项数</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in disciplineRows" :key="r.code">
                <td class="tabular-nums">{{ r.code }}</td>
                <td>{{ r.name }}</td>
                <td style="color: var(--muted)">{{ r.dept }}</td>
                <td style="text-align:right" class="tabular-nums">{{ fmt(r.count) }}</td>
              </tr>
            </tbody>
          </table>
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
  margin: 16px 0;
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
