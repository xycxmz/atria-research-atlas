<script setup>
import { ref, onMounted, computed } from 'vue'
import { getAnalysis } from '../api'
import DataState from '../components/DataState.vue'

const data = ref(null)
const error = ref(null)

async function load() {
  error.value = null
  try {
    data.value = await getAnalysis()
  } catch (e) {
    error.value = e
  }
}

onMounted(load)

const fmt = (n, d = 0) => Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: d })

const coverageRows = computed(() => {
  const rows = data.value?.coverage?.by_year || []
  return rows
    .filter(r => r.portal || r.report || r.have)
    .map(r => ({
      year: r.year,
      have: r.have || 0,
      portal: r.portal,
      report: r.report,
      rate: r.rate_portal,
      gap: r.portal != null ? r.portal - (r.have || 0) : null,
    }))
    .sort((a, b) => a.year - b.year)
})

const overall = computed(() => {
  const rows = coverageRows.value.filter(r => r.portal != null)
  if (!rows.length) return null
  const e = rows.reduce((s, r) => s + r.portal, 0)
  const f = rows.reduce((s, r) => s + r.have, 0)
  return { expected: e, fetched: f, rate: e ? f / e : 0 }
})

// 低覆盖年（如 2023：6/51,542）不能只显示四舍五入后的 0.0%，要明示样本极少
const rateText = (r) => {
  if (r.rate == null) return '—'
  return r.rate < 0.0005 ? '<0.1%' : (r.rate * 100).toFixed(1) + '%'
}
</script>

<template>
  <div>
    <div class="page-header">
      <h2>覆盖率</h2>
      <span class="note">实采条数 vs 官方批准总数 · 两套口径并列，不相加</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data">
      <div class="cards" v-if="overall">
        <div class="card">
          <div class="label">累计覆盖率（1986–2023 门户全部立项）</div>
          <div class="value">{{ (overall.rate * 100).toFixed(1) }}%</div>
          <div class="coverage-bar"><div :style="{ width: (overall.rate * 100) + '%' }"></div></div>
        </div>
        <div class="card">
          <div class="label">实采 / 门户批准数</div>
          <div class="value small">{{ fmt(overall.fetched) }} / {{ fmt(overall.expected) }}</div>
        </div>
        <div class="card">
          <div class="label">门户累计缺口（含未采集历史年份）</div>
          <div class="value small" style="color: var(--warn)">{{ fmt(overall.expected - overall.fetched) }} 条</div>
        </div>
        <div class="card">
          <div class="label">多来源重叠</div>
          <div class="value small">{{ fmt(data.by_source?.multi_source_projects || 0) }} 条</div>
        </div>
      </div>
      <div class="chart">
        <h3>分年覆盖率</h3>
        <table>
          <thead>
            <tr>
              <th>批准年</th>
              <th style="text-align:right">实采</th>
              <th style="text-align:right">门户批准</th>
              <th style="text-align:right">年报批准</th>
              <th style="text-align:right">缺口</th>
              <th>覆盖率（门户）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in coverageRows" :key="r.year">
              <td>{{ r.year }}</td>
              <td style="text-align:right">{{ fmt(r.have) }}</td>
              <td style="text-align:right">{{ r.portal != null ? fmt(r.portal) : '—' }}</td>
              <td style="text-align:right; color: var(--muted)">{{ r.report != null ? fmt(r.report) : '—' }}</td>
              <td style="text-align:right; color: var(--warn)">{{ r.gap != null ? fmt(r.gap) : '—' }}</td>
              <td style="min-width: 180px;">
                <div style="display:flex; align-items:center; gap:8px;">
                  <div class="coverage-bar" style="flex:1; margin:0;">
                    <div :style="{ width: ((r.rate || 0) * 100) + '%' }"></div>
                  </div>
                  <span style="font-size:12px;">{{ rateText(r) }}</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="hint">
          「门户批准」来自基金委知识门户（kd.nsfc.cn，与本地行数据同源，1986–2023）；「年报批准」来自基金委年度报告（2016–2026）。
          两套口径部分年份不一致（如 2023 年门户 51,542 项、年报 52,547 项），是统计范围差异，不是矛盾，不相加、不取平均。
          累计覆盖率低不代表采错：1986–2013 不在当前采集范围内（grok 按结题年度 2020+ 推进，pkg 覆盖 2014+），
          有意义的覆盖区间是 2016–2020。<br/>
          结题年度 2023–2025 的缺口（27,013 / 45,682 / 46,955 条）目前无法补采：
          门户的结题项目检索接口已下线（2026-10-03 探测确认，详见 docs/PORTAL-PROBE-2026-10-03.md）。
        </div>
      </div>
      </template>
    </DataState>
  </div>
</template>
