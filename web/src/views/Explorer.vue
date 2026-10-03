<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, watch, computed } from 'vue'
import { getProjects, getHealth } from '../api'
import { readUrl, writeUrl, onPopState } from '../modules/urlState'
import { createLatest } from '../modules/latestGuard'
import { setScope, registerApplyScope, unregisterApplyScope } from '../modules/scope'
import { buildSummaryMarkdown } from '../modules/exportAnalysis'
import { downloadText, downloadBlob, safeName } from '../modules/download'
import DataState from '../components/DataState.vue'
import ProjectDetail from './ProjectDetail.vue'

const PAGE_KEY = 'explorer'

// 草稿：只绑定输入框；「检索」后才生成不可变的 appliedQuery 快照（V2-010）
const q = ref('')
const year = ref('')
const dept = ref('')
const inst = ref('')
const type = ref('')
const subj = ref('')
const size = ref(20)
const page = ref(1)
const detailNo = ref(null)

const applied = ref(null)  // 已应用查询快照：请求与导出的唯一来源
const result = ref(null)
// result 对应的查询快照（V2R2-002）：显示中的行属于哪个查询，导出就绑哪个
const resultQuery = ref(null)
const error = ref(null)
const loading = ref(false)
const totalPages = ref(0)
const guard = createLatest()

// 旧结果与新查询不一致：UI 必须明示（不能默默让导出名套到旧行上）
const staleDisplay = computed(() => {
  if (!resultQuery.value || !applied.value) return false
  return JSON.stringify(resultQuery.value) !== JSON.stringify(applied.value)
})
const queryLabel = (v) => {
  if (!v) return '—'
  const parts = [v.q, v.year, v.dept, v.inst, v.type, v.subj].filter(Boolean)
  return parts.join(' · ') || '全部'
}

const fmt = (n, d = 0) => (n == null || n === '') ? '-' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: d })

function sourceTags(raw) {
  if (!raw) return []
  try { return JSON.parse(raw) } catch (e) { return [String(raw)] }
}

function draftQuery(nextPage) {
  return {
    q: q.value, year: year.value, dept: dept.value,
    inst: inst.value, type: type.value, subj: subj.value,
    page: nextPage ?? page.value, size: size.value,
  }
}

function paintDraft(v) {
  // dept 与 division 是同一条件的页面态/规范态命名（V2R2-001）
  q.value = v.q || ''
  year.value = v.year || ''
  dept.value = v.dept || v.division || ''
  inst.value = v.inst || ''
  type.value = v.type || ''
  subj.value = v.subj || ''
  page.value = Number(v.page) || 1
  size.value = Number(v.size) || 20
}

function saveLast(v) {
  try { localStorage.setItem('nsfc_last_query', JSON.stringify(v)) } catch (e) { /* 无痕模式 */ }
}

function loadLast() {
  try {
    const raw = localStorage.getItem('nsfc_last_query')
    return raw ? JSON.parse(raw) : null
  } catch (e) { return null }
}

// 导出一律绑 resultQuery（正在显示的结果的查询），不读 live applied（V2R2-002）
function exportCSV() {
  if (!result.value || !resultQuery.value) return
  const v = resultQuery.value
  const parts = [v.q, v.year, v.dept, v.inst, v.type, v.subj].filter(Boolean)
  downloadBlob(`nsfc_${safeName(parts.join('_') || 'all')}_p${v.page || 1}.csv`, buildCsvBlob(result.value.rows))
}

async function exportSummary() {
  if (!result.value || !resultQuery.value) return
  // 快照哈希尽力而为：取不到就标 —（摘要仍可由复现链接重建）
  let snapshot = null
  try {
    snapshot = (await getHealth()).snapshot
  } catch (e) {
    snapshot = null
  }
  const md = buildSummaryMarkdown({
    applied: resultQuery.value,
    result: result.value,
    snapshot,
    generatedAt: new Date().toISOString(),
  })
  const parts = [resultQuery.value.q, resultQuery.value.year, resultQuery.value.dept,
                 resultQuery.value.inst, resultQuery.value.type, resultQuery.value.subj].filter(Boolean)
  downloadText(`nsfc_摘要_${safeName(parts.join('_') || 'all')}_p${resultQuery.value.page || 1}.md`, md, 'text/markdown')
}

// 全筛选导出：任务级冻结（query/total 与独立 AbortController），循环不读 live
// 页面变量（V2R2-002）；取消、切页、开始新任务不会被旧任务 finally 覆盖
const EXPORT_CAP = 10000
const exportJob = reactive({ id: 0, active: false, fetched: 0, total: 0, error: null })
let exportAbort = null

async function exportAll() {
  if (!result.value || !resultQuery.value) return
  if (exportJob.active) return
  const total = result.value.total
  if (total > EXPORT_CAP) {
    exportJob.error = `命中 ${total.toLocaleString('zh-CN')} 条，超过全量导出上限 ${EXPORT_CAP.toLocaleString('zh-CN')} 条——请收窄筛选后再试，或先用「导出本页」。`
    return
  }
  exportJob.error = null
  const jobId = exportJob.id + 1
  exportJob.id = jobId
  exportJob.active = true
  exportJob.fetched = 0
  exportJob.total = total
  // 冻结任务查询：循环期间 applied 变了也不影响本任务
  const jobQuery = { ...resultQuery.value }
  exportAbort = new AbortController()
  const size = 100
  const pages = Math.max(1, Math.ceil(total / size))
  const allRows = []
  try {
    for (let p = 1; p <= pages; p++) {
      // 被取消或被新导出任务取代：立即停
      if (exportAbort.signal.aborted || exportJob.id !== jobId) return
      const r = await getJobsPage({ ...jobQuery, page: p, size }, exportAbort.signal)
      if (exportAbort.signal.aborted || exportJob.id !== jobId) return
      allRows.push(...r.rows)
      exportJob.fetched = allRows.length
      // 让出主线程，避免长列表导出卡住页面
      await new Promise((res) => setTimeout(res, 0))
    }
    if (exportJob.id !== jobId) return
    const blob = buildCsvBlob(allRows)
    const parts = [jobQuery.q, jobQuery.year, jobQuery.dept,
                   jobQuery.inst, jobQuery.type, jobQuery.subj].filter(Boolean)
    downloadBlob(`nsfc_全部_${safeName(parts.join('_') || 'all')}_${allRows.length}条.csv`, blob)
  } catch (e) {
    if (e.name === 'AbortError') return
    // 只有当前任务才能写错误状态（旧任务的失败不覆盖新任务）
    if (exportJob.id === jobId) exportJob.error = e.message || String(e)
  } finally {
    // 只有当前任务才能复位状态（旧任务的 finally 不覆盖新任务）
    if (exportJob.id === jobId) exportJob.active = false
    if (exportAbort && exportJob.id === jobId) exportAbort = null
  }
}

// runSidebar/quota 均不使用页面 live applied
async function getJobsPage(params, signal) {
  return getProjects(params, signal)
}

function cancelExport() {
  exportAbort && exportAbort.abort()
  // finally 的守卫会复位 active；这里立即标记任务结束
  exportJob.active = false
}

function buildCsvBlob(rows) {
  const cols = ['grant_no', 'title', 'pi', 'institution', 'award_year', 'close_year',
                'grant_type', 'grant_type_raw', 'division_name', 'subject_code', 'subject_l1',
                'amount_wan', 'amount_inferred', 'begin_date', 'end_date', 'keywords',
                'abstract_zh', 'has_report', 'report_url', 'sources']
  const labels = ['批准号', '题目', '负责人', '依托单位', '批准年度', '结题年度',
                  '项目类别', '类别原文', '学部', '申请代码', '一级学科', '金额(万元)',
                  '金额推断', '起始', '结束', '关键词', '摘要', '有报告', '报告链接', '来源']
  const esc = (v) => {
    if (v == null) return ''
    const s = String(v).replace(/"/g, '""')
    return /[",\n]/.test(s) ? `"${s}"` : s
  }
  const lines = [labels.join(',')]
  for (const r of rows) {
    lines.push(cols.map(c => esc(r[c])).join(','))
  }
  return new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
}

async function load() {
  if (!applied.value) return
  loading.value = true
  error.value = null
  // 慢 A 快 B：回包到来时若已被超越则丢弃（V2-010）
  const t = guard.begin()
  // 冻结本次请求的查询：结果将与 resultQuery 绑定（V2R2-002）
  const query = { ...applied.value }
  try {
    const r = await getProjects(query)
    if (!guard.isLatest(t)) return
    result.value = r
    resultQuery.value = query
    totalPages.value = Math.ceil(r.total / r.size)
  } catch (e) {
    if (guard.isLatest(t)) error.value = e
  } finally {
    if (guard.isLatest(t)) loading.value = false
  }
}

function syncUrl() {
  const v = { ...(applied.value || {}) }
  if (v.dept) v.division = v.dept   // canonical，跨页携带时不丢学部（V2R2-001）
  if (detailNo.value) v.detail = detailNo.value
  writeUrl(PAGE_KEY, v)
}

let skipPageWatch = false

/** 用户点「检索」：生成快照、写入 URL、记忆、加载。 */
function submit() {
  // 页码重置若触发 watch 会再 load 一次：先置守卫位去重（V2-010）
  if (page.value !== 1) {
    skipPageWatch = true
    page.value = 1
  }
  applied.value = draftQuery(1)
  syncUrl()
  saveLast(applied.value)
  // 范围条跟随已应用快照（W4）
  setScope({ division: applied.value.dept || '', year: applied.value.year || '',
             grantType: applied.value.type || '' }, { silent: true })
  load()
}

/** 范围条应用范围：维度写草稿并提交（W4） */
function applyScopeParams(s) {
  if (typeof s.division === 'string') dept.value = s.division
  if (typeof s.year === 'string') year.value = s.year
  if (typeof s.grantType === 'string') type.value = s.grantType
  submit()
}

/** 从 URL 恢复（初始加载或前进后退）：静默应用，不再写回 URL。 */
function restore(v) {
  // URL 目标页与当前不同时，paintDraft 的页码改动会触发 watch(page) 二次 load——
  // 那会把 restore 自己的请求顶成「最新」再丢弃已取回的回包（V2-010 重复请求）
  if (page.value !== (Number(v.page) || 1)) {
    skipPageWatch = true
  }
  paintDraft(v)
  applied.value = draftQuery()
  detailNo.value = v.detail || null
  setScope({ division: applied.value.dept || '', year: applied.value.year || '',
             grantType: applied.value.type || '' }, { silent: true })
  load()
}

onMounted(() => {
  // 检索页支持全部三个范围维度（V2R2-001：维度声明与实际生效一致）
  registerApplyScope(applyScopeParams, ['division', 'year', 'grantType'])
  const url = readUrl()
  const fromUrl = url.page === PAGE_KEY && Object.keys(url.params).length > 0
  if (fromUrl) {
    restore(url.params)
  } else {
    // 继续上次：URL 没有查询条件时恢复最近一次已应用查询（仅存本地，V2-009）
    const last = loadLast()
    if (last) {
      restore(last)
      return
    }
    applied.value = draftQuery()
    setScope({ division: '', year: '', grantType: '' }, { silent: true })
    load()
  }
})

let offPop = onPopState(({ page, params }) => {
  if (page !== PAGE_KEY) return
  restore(params)
})
onBeforeUnmount(() => {
  offPop && offPop()
  unregisterApplyScope()
})

watch(page, () => {
  if (skipPageWatch) { skipPageWatch = false; return }
  if (!applied.value) return
  applied.value = { ...applied.value, page: page.value }
  syncUrl()
  saveLast(applied.value)
  load()
})

watch(detailNo, () => { if (applied.value) syncUrl() })
</script>

<template>
  <div>
    <div class="page-header">
      <h2>数据检索</h2>
      <span class="note">支持关键词 / 年份 / 学部 / 单位 / 类型 / 学科组合过滤 · 筛选条件在 URL 里，可刷新与后退</span>
    </div>
    <div class="filters">
      <input v-model="q" placeholder="题目 / 负责人 / 批准号" style="width: 220px" @keyup.enter="submit" />
      <input v-model="year" placeholder="年份（如 2019）" style="width: 110px" @keyup.enter="submit" />
      <input v-model="dept" placeholder="学部（如 管理）" style="width: 130px" @keyup.enter="submit" />
      <input v-model="inst" placeholder="单位" style="width: 150px" @keyup.enter="submit" />
      <input v-model="type" placeholder="项目类型" style="width: 140px" @keyup.enter="submit" />
      <input v-model="subj" placeholder="一级学科" style="width: 130px" @keyup.enter="submit" />
      <button class="pager-btn" @click="submit">检索</button>
    </div>
    <DataState :loading="loading && !result" :error="error"
               :empty="!!result && result.total === 0" empty-text="没有符合条件的项目——请调整筛选后重试"
               @retry="load">
      <template v-if="result">
        <div v-if="staleDisplay" class="stale-banner">
          当前显示的是查询「{{ queryLabel(resultQuery) }}」的结果；新查询「{{ queryLabel(applied) }}」尚未回包。
          导出按当前显示的查询执行，文件名与之配套。
        </div>
        <div class="chart">
          <h3>共 {{ fmt(result.total) }} 条（第 {{ result.page }} / {{ totalPages }} 页）</h3>
          <div class="exports">
            <button class="pager-btn" @click="exportCSV">导出本页 CSV</button>
            <button class="pager-btn" @click="exportSummary">导出分析摘要（Markdown）</button>
            <button class="pager-btn" :disabled="exportJob.active" @click="exportAll">
              导出全部命中（上限 10,000 条）
            </button>
            <template v-if="exportJob.active">
              <span class="export-progress">
                已取 {{ fmt(exportJob.fetched) }} / 预计 {{ fmt(exportJob.total) }} 条
              </span>
              <button class="pager-btn" @click="cancelExport">取消</button>
            </template>
            <div v-else-if="exportJob.error" class="export-error">{{ exportJob.error }}</div>
          </div>
          <table>
            <thead>
              <tr>
                <th>批准号</th><th>题目</th><th>负责人</th><th>单位</th><th>年份</th>
                <th>类型</th><th>学部</th><th>一级学科</th><th style="text-align:right">金额(万元)</th><th>来源</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in result.rows" :key="r.grant_no" class="clickable"
                  tabindex="0" role="button"
                  :aria-label="`查看项目 ${r.grant_no} ${r.title} 的详情`"
                  @click="detailNo = r.grant_no"
                  @keydown.enter.prevent="detailNo = r.grant_no"
                  @keydown.space.prevent="detailNo = r.grant_no">
                <td style="font-family: monospace; font-size: 12px;">{{ r.grant_no }}</td>
                <td style="max-width: 320px;">{{ r.title }}</td>
                <td>{{ r.pi }}</td>
                <td style="max-width: 130px;">{{ r.institution }}</td>
                <td>{{ r.award_year }}</td>
                <td style="max-width: 110px;">{{ r.grant_type }}</td>
                <td style="max-width: 100px;">{{ r.division_name }}</td>
                <td style="max-width: 100px;">{{ r.subject_l1 }}</td>
                <td style="text-align:right">{{ fmt(r.amount_wan, 1) }}</td>
                <td style="max-width: 130px;">
                  <span
                    v-for="tag in sourceTags(r.sources)"
                    :key="tag"
                    class="badge"
                    :style="{ fontSize: '10px' }"
                  >{{ tag }}</span>
                </td>
                <td><button class="pager-btn row-detail" @click.stop="detailNo = r.grant_no">详情</button></td>
              </tr>
            </tbody>
          </table>
          <div class="pager">
            <button :disabled="page <= 1" @click="page--">上一页</button>
            <span>第 {{ page }} 页 / 共 {{ totalPages }} 页</span>
            <button :disabled="page >= totalPages" @click="page++">下一页</button>
            <span style="margin-left: auto;">每页 {{ result.size }} 条 · 点击行看详情</span>
          </div>
        </div>
      </template>
    </DataState>
    <ProjectDetail v-if="detailNo" :grant-no="detailNo" @close="detailNo = null" />
  </div>
</template>

<style scoped>
.pager-btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--accent);
  border-radius: 8px;
  padding: 7px 18px;
  cursor: pointer;
  font-size: 13px;
}
.pager-btn:hover { border-color: var(--accent); }
.pager-btn:disabled { opacity: 0.4; cursor: not-allowed; }
tbody tr.clickable { cursor: pointer; }
tbody tr.clickable:hover, tbody tr.clickable:focus-visible { background: var(--panel-2); outline: none; }
tbody tr.clickable:focus-visible { box-shadow: inset 0 0 0 1px var(--accent); }
.row-detail { padding: 3px 10px; font-size: 12px; }
.exports {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
}
.export-progress { font-size: 12.5px; color: var(--accent); }
.export-error { font-size: 12.5px; color: var(--danger); }
.stale-banner {
  border: 1px solid rgba(240, 180, 41, 0.4);
  background: rgba(240, 180, 41, 0.08);
  color: var(--warn);
  border-radius: 10px;
  padding: 8px 14px;
  font-size: 12.5px;
  margin-bottom: 10px;
}
</style>
