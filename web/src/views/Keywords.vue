<script setup>
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { getAdvanced } from '../api'
import BaseChart from '../components/BaseChart.vue'
import DataState from '../components/DataState.vue'
import { getScope, setScope, registerApplyScope, unregisterApplyScope, host } from '../modules/scope'

const adv = ref(null)
const error = ref(null)
const scope = ref('overall')
const year = ref(0)

async function load() {
  error.value = null
  try {
    adv.value = await getAdvanced()
  } catch (e) {
    error.value = e
  }
}

onMounted(() => {
  load()
  // 本页只支持学部维度（V2R2-001）；年份/类别不作用于本页词表
  registerApplyScope((s) => { divisionName.value = s.division }, ['division'])
})
onBeforeUnmount(unregisterApplyScope)

const fmt = (n) => Number(n || 0).toLocaleString('zh-CN')

const keywordData = computed(() => adv.value?.keyword_freq || null)
const deptNames = computed(() => ['', ...(keywordData.value?.by_division?.map(d => d.division_name) || [])])
const yearList = computed(() => keywordData.value?.by_year?.map(y => y.year) || [])

// 当前选中范围下的词表
const rows = computed(() => {
  const kd = keywordData.value
  if (!kd) return []
  if (scope.value === 'overall') return kd.overall || []
  if (scope.value === 'division') {
    const d = kd.by_division?.find(x => x.division_name === divisionName.value)
    return d ? d.top : []
  }
  const y = kd.by_year?.find(x => x.year === year.value)
  return y ? y.top : []
})

const divisionName = ref('')

// 当前选中的年度条目（含 keyworded_n 与 sufficient 标记）
const yearEntry = computed(() => keywordData.value?.by_year?.find(x => x.year === year.value) || null)
const divisionEntry = computed(() => keywordData.value?.by_division?.find(x => x.division_name === divisionName.value) || null)

// adv 到达后才确定默认值（computed 已定义，此时 watch 安全）
watch(() => keywordData.value?.by_division, (ds) => {
  if (ds && ds.length && !divisionName.value) {
    divisionName.value = ds[0].division_name
  }
}, { immediate: true })

// 默认年份取最后一个「样本充分」的年度；低覆盖年主动选中才看得到缺测提示
watch(() => keywordData.value?.by_year, (ys) => {
  if (ys && ys.length && !year.value) {
    const ok = ys.filter(y => y.sufficient !== false)
    year.value = (ok.length ? ok[ok.length - 1] : ys[ys.length - 1]).year
  }
}, { immediate: true })

// W4：学部选中与全局 scope 双向同步。
// 初始默认学部不同步到 URL（userTouched 守卫），避免挂载时多生一个历史步；
// scope → divisionName 方向不受守卫限制，直链里的 division 参数能恢复。
const sc = getScope()
// immediate：带 scope 直进本页时学部选中须在挂载时同步（V2R2-001，同 Subjects）
watch(() => sc.division, (d) => { if (d && d !== divisionName.value) divisionName.value = d }, { immediate: true })
let userTouchedDivision = false
watch(divisionName, (d) => {
  if (userTouchedDivision) setScope({ division: d })
})

// V2R2-001：维度声明（供 ScopeBar 与测试核对）
const scopeSupport = ['division']

// W5：点词柱 → 带关键词转检索；分学部/分年度模式同时携带该范围（V2R2-001 同口径）
function onBarClick(e) {
  const params = { q: e.name, page: '1' }
  if (scope.value === 'division' && divisionName.value) params.dept = divisionName.value
  if (scope.value === 'year' && year.value) params.year = String(year.value)
  host.go?.('explorer', params)
}
function onDivisionChange() {
  userTouchedDivision = true
}

// 图表下载文件名带当前范围（S3）
const downloadName = computed(() => {
  if (scope.value === 'division' && divisionName.value) return '关键词Top25_' + divisionName.value
  if (scope.value === 'year' && year.value) return '关键词Top25_' + year.value + '年'
  return '关键词Top25_总榜'
})

const barOption = computed(() => {
  const rs = rows.value.slice(0, 25).reverse()
  return {
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (p) => `${p[0].name}<br/>${fmt(p[0].value)} 次出现`,
    },
    grid: { left: '24%', right: '6%' },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category', data: rs.map(r => r.keyword),
      axisLabel: { width: 130, overflow: 'truncate' },
    },
    series: [{
      type: 'bar', data: rs.map(r => r.count),
      itemStyle: { color: '#bc8cff' },
    }],
  }
})

// 词云式气泡图（按词频平方根缩放，避免长尾被压扁）
const bubbleOption = computed(() => {
  const rs = rows.value.slice(0, 60)
  return {
    tooltip: { formatter: (p) => `${p.data.name}<br/>${fmt(p.data.value)} 次` },
    series: [{
      type: 'graph', layout: 'circular',
      roam: true, draggable: true,
      symbolSize: (v) => Math.sqrt(v) * 1.6 + 6,
      label: { show: true, fontSize: 12, color: '#e6edf3' },
      itemStyle: { color: '#bc8cff', borderColor: '#e6edf3', borderWidth: 0.5 },
      data: rs.map((r, i) => ({ name: r.keyword, value: r.count, id: String(i) })),
    }],
  }
})
</script>

<template>
  <div>
    <div class="page-header">
      <h2>关键词</h2>
      <span class="note" v-if="keywordData">库内 {{ fmt(keywordData.overall_rows) }} 条有关键词 · 分号切分 · 短于 2 字不计</span>
    </div>
    <DataState :loading="!adv && !error" :error="error" @retry="load">
      <template v-if="adv">
      <div class="filters">
        <button :class="{ active: scope === 'overall' }" @click="scope = 'overall'">总榜</button>
        <button :class="{ active: scope === 'division' }" @click="scope = 'division'">分学部</button>
        <button :class="{ active: scope === 'year' }" @click="scope = 'year'">分年度</button>
        <select v-if="scope === 'division'" v-model="divisionName" @change="onDivisionChange" style="margin-left: 8px;">
          <option v-for="d in deptNames.slice(1)" :key="d" :value="d">{{ d }}</option>
        </select>
        <select v-if="scope === 'year'" v-model="year" style="margin-left: 8px;">
          <option v-for="y in yearList" :key="y" :value="y">{{ y }} 年</option>
        </select>
      </div>
      <div class="hint" style="margin-bottom: 14px;">
        词频统计仅覆盖填写了关键词的项目（约 90%），每个词按出现该词的项目数计（同一项目内重复只算一次），
        中英文分号均切分，不做同义词合并（「深度学习」与「机器学习」分别计数）。
      </div>
      <!-- V2-002：低覆盖年份显示缺测，不是「热度为零」 -->
      <div v-if="scope === 'year' && yearEntry && yearEntry.sufficient === false" class="error" style="margin-bottom: 14px;">
        {{ yearEntry.year }} 年库内仅 {{ fmt(yearEntry.keyworded_n) }} 条带关键词的项目，样本不足，
        不生成词频榜——这不能读作「该年没有研究热点」。请选 2022 年或更早的充分年份。
      </div>
      <div v-if="scope === 'division' && divisionEntry" class="hint" style="margin-bottom: 14px;">
        {{ divisionEntry.division_name }}：{{ fmt(divisionEntry.keyworded_n) }} 条带关键词的项目。
      </div>
      <div class="grid-2">
        <div class="chart">
          <h3>高频词 Top 25</h3>
          <BaseChart :option="barOption" height="520px" @click="onBarClick" :download-name="downloadName" />
          <div class="hint">点击词柱按该关键词转检索（题目/负责人/批准号/关键词范围）；分学部/分年度模式下同时携带该范围。</div>
        </div>
        <div class="chart">
          <h3>词频气泡（可拖动缩放）</h3>
          <BaseChart :option="bubbleOption" height="520px" />
        </div>
      </div>
      <div class="chart" style="margin-top: 16px;">
        <h3>词表明细（Top 40）</h3>
        <table>
          <thead>
            <tr><th style="width: 60px;">#</th><th>关键词</th><th style="text-align:right">出现次数</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="r.keyword + i" class="clickable"
                @dblclick="onBarClick({ name: r.keyword })" :title="`双击按「${r.keyword}」检索项目`">
              <td class="tabular-nums" style="color: var(--muted)">{{ i + 1 }}</td>
              <td>{{ r.keyword }}</td>
              <td style="text-align:right" class="tabular-nums">{{ fmt(r.count) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      </template>
    </DataState>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
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
.filters select {
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
}
.tabular-nums { font-variant-numeric: tabular-nums; }
tbody tr.clickable { cursor: pointer; }
tbody tr.clickable:hover { background: var(--panel-2); }
</style>
