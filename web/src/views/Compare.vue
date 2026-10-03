<script setup>
import { ref, onMounted, computed } from 'vue'
import { getAnalysis } from '../api'
import { getScope } from '../modules/scope'
import DataState from '../components/DataState.vue'

const data = ref(null)
const error = ref(null)
const sc = getScope()

async function load() {
  error.value = null
  try {
    data.value = await getAnalysis()
  } catch (e) {
    error.value = e
  }
}

onMounted(load)

// 最新一个两套口径都有的年份：门户 vs 年报批准数并列（V2-008 的口径护栏在此收口）
const dualBasis = computed(() => {
  const rows = (data.value?.coverage?.by_year || [])
    .filter((r) => r.portal != null && r.report != null)
    .map((r) => ({ year: r.year, portal: r.portal, report: r.report, have: r.have || 0 }))
    .sort((a, b) => b.year - a.year)
  return rows.slice(0, 3)
})

// 同范围指标表：每学部 N / 金额有效 N / 推断（缺失）率 / 金额合计
const metrics = computed(() => {
  const rows = (data.value?.by_department || []).map((r) => ({
    division: r.division_name,
    count: r.count,
    valid_n: r.valid_n ?? 0,
    amount: r.amount ?? 0,
    missing_rate: r.count ? (r.count - (r.valid_n ?? 0)) / r.count : null,
  }))
  return rows
})

const focused = computed(() => metrics.value.find((r) => r.division === sc.division) || null)
const fmt = (n, d = 0) => Number(n || 0).toLocaleString('zh-CN', { maximumFractionDigits: d })
const pct = (v) => (v == null ? '—' : (v * 100).toFixed(1) + '%')
</script>

<template>
  <div>
    <div class="page-header">
      <h2>口径对比</h2>
      <span class="note">门户聚合 vs 年报聚合 · 同范围指标 · 不相加不取平均</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data">
        <div class="hint" style="margin-bottom: 16px;">
          两套官方口径部分年份不一致（如 2023 批准），是统计范围差异而非矛盾。
          页面上并列呈现、注明来源；差异原因未逐项核定，不宣称某一方更准。
        </div>
        <div v-for="r in dualBasis" :key="r.year" class="dual">
          <h3>{{ r.year }} 年批准数对照</h3>
          <div class="dual-cards">
            <div class="card portal">
              <div class="label">门户聚合（kd.nsfc.cn）</div>
              <div class="value">{{ fmt(r.portal) }} 项</div>
              <div class="qnote">与本地行数据同源的公开统计</div>
            </div>
            <div class="card report">
              <div class="label">年报聚合（集中接收口径）</div>
              <div class="value">{{ fmt(r.report) }} 项</div>
              <div class="qnote">申请/资助/资助率口径</div>
            </div>
            <div class="card have">
              <div class="label">库内可下钻样本</div>
              <div class="value small">{{ fmt(r.have) }} 条</div>
              <div class="qnote">不是全国明细，覆盖情况见覆盖率页</div>
            </div>
          </div>
        </div>
        <div class="chart" style="margin-top: 16px;">
          <h3>学部同范围指标表（库内样本）</h3>
          <p class="hint">金额缺失不计入任何均值；缺失率 = (立项数 − 金额有效N) / 立项数。范围条选学部后聚焦该行。</p>
          <table>
            <thead>
              <tr>
                <th>学部</th>
                <th style="text-align:right">立项数</th>
                <th style="text-align:right">金额有效N</th>
                <th style="text-align:right">金额缺失率</th>
                <th style="text-align:right">金额合计(万元)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in metrics" :key="r.division" :class="{ focus: r.division === sc.division }">
                <td>{{ r.division }}</td>
                <td style="text-align:right">{{ fmt(r.count) }}</td>
                <td style="text-align:right">{{ fmt(r.valid_n) }}</td>
                <td style="text-align:right" :style="{ color: (r.missing_rate ?? 0) > 0.1 ? 'var(--warn)' : 'inherit' }">{{ pct(r.missing_rate) }}</td>
                <td style="text-align:right">{{ fmt(r.amount, 1) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </DataState>
  </div>
</template>

<style scoped>
.dual { margin-bottom: 20px; }
.dual h3 { font-size: 14px; margin-bottom: 8px; }
.dual-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}
.card .value { font-size: 24px; font-weight: 700; }
.card.portal .value { color: var(--accent); }
.card.report .value { color: var(--accent-2); }
.card.have .value { color: var(--text); }
.qnote { font-size: 11.5px; color: var(--muted); margin-top: 6px; }
tr.focus td { background: rgba(76, 194, 255, 0.08); }
</style>
