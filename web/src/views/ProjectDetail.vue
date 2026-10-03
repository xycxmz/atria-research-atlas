<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { getProject } from '../api'
import { createLatest } from '../modules/latestGuard'
import DataState from '../components/DataState.vue'

const props = defineProps({ grantNo: { type: String, required: true } })
const emit = defineEmits(['close'])

const data = ref(null)
const error = ref(null)
const guard = createLatest()

const FIELD_LABELS = {
  grant_no: '批准号', title: '题目', pi: '负责人', institution: '依托单位',
  award_year: '批准年度', close_year: '结题年度', grant_type: '项目类别',
  grant_type_raw: '类别原文', division_code: '学部代码', division_name: '学部',
  subject_code: '申请代码', subject_l1: '一级学科', subject_l2: '二级学科',
  subject_l3: '三级学科', subject_names_derived: '学科名推导',
  amount_wan: '金额(万元)', amount_inferred: '金额推断',
  begin_date: '起始日期', end_date: '结束日期', keywords: '关键词',
  abstract_zh: '中文摘要', has_report: '有结题报告', sources: '数据来源',
  report_keywords: '结题报告关键词', report_url: '结题报告链接',
}

// 详情弹层里逐字段展示的顺序（其余字段在末尾追加）
const DISPLAY_ORDER = [
  'grant_no', 'title', 'pi', 'institution', 'award_year', 'close_year',
  'grant_type', 'grant_type_raw', 'division_name', 'subject_code',
  'subject_l1', 'subject_l2', 'subject_l3', 'subject_names_derived',
  'amount_wan', 'amount_inferred', 'begin_date', 'end_date', 'keywords',
  'abstract_zh', 'has_report', 'report_keywords', 'report_url', 'sources',
]

const fmt = (n, d = 1) => (n == null || n === '') ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: d })

async function load() {
  error.value = null
  data.value = null
  // 快速连开两条详情时，旧请求的回包必须丢弃（V2-010）
  const t = guard.begin()
  try {
    const d = await getProject(props.grantNo)
    if (guard.isLatest(t)) data.value = d
  } catch (e) {
    if (guard.isLatest(t)) error.value = e
  }
}

onMounted(() => {
  // 对话框语义（V2R2-003）：记录打开者焦点，进抽屉聚焦关闭按钮，Escape 关闭后还焦
  lastFocused = document.activeElement
  load()
  nextTick(() => closeBtn.value?.focus())
  window.addEventListener('keydown', onKeydown)
})
let lastFocused = null
const closeBtn = ref(null)

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (lastFocused && lastFocused.focus) lastFocused.focus()
})

function displayValue(key, v) {
  if (v == null || v === '') return '—'
  if (key === 'amount_wan') return fmt(v)
  if (key === 'has_report') return v ? '是' : '否'
  // 三态明确区分：0 是「有明确标注」，null 是「来源无此标记」（V2-005）
  if (key === 'subject_names_derived') return Number(v) === 1 ? '是（申请代码推导）' : '否（来源原文）'
  if (key === 'amount_inferred') return Number(v) === 1 ? '是（量级推断）' : '否（明确单位）'
  return String(v)
}

function parseAlternatives(c) {
  if (Array.isArray(c.alternatives)) return c.alternatives
  try { return JSON.parse(c.alternatives || '[]') } catch (e) { return [] }
}

function displayRows(project) {
  const keys = [...DISPLAY_ORDER, ...Object.keys(project).filter(k => !DISPLAY_ORDER.includes(k) && !(k in FIELD_LABELS) && !['provenance', 'grant_type_raw', 'subject_names_derived', 'sources'].includes(k))]
  return keys.map(k => ({ key: k, label: FIELD_LABELS[k] || k, value: displayValue(k, project[k]) }))
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="drawer" role="dialog" aria-modal="true" :aria-label="`项目详情 ${grantNo}`">
      <div class="drawer-header">
        <h3>项目详情 · {{ grantNo }}</h3>
        <button ref="closeBtn" class="pager-btn" @click="emit('close')">关闭</button>
      </div>
      <DataState :loading="!data && !error" :error="error" @retry="load">
        <div v-if="data && !data.found" class="error">未找到批准号 {{ grantNo }}</div>
        <template v-else-if="data">
        <div class="conflicts" v-if="data.conflicts.length">
          <h4>字段冲突（{{ data.conflicts.length }} 条）</h4>
          <table v-for="c in data.conflicts" :key="c.field" class="conflict-table">
            <thead>
              <tr><th>{{ c.field }}</th><th>值</th><th>来源</th></tr>
            </thead>
            <tbody>
              <tr class="selected">
                <td><span class="badge">选中</span></td>
                <td>{{ c.selected }}</td>
                <td>{{ c.selected_from }}</td>
              </tr>
              <tr v-for="(alt, i) in parseAlternatives(c)" :key="i" class="dropped">
                <td>落选</td>
                <td>{{ alt.value }}</td>
                <td>{{ alt.from }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <h4>完整记录</h4>
        <table class="detail-table">
          <tbody>
            <tr v-for="r in displayRows(data.project)" :key="r.key">
              <td class="field-label">{{ r.label }}</td>
              <td v-if="r.key === 'report_url' && r.value !== '—'">
                <a :href="r.value" target="_blank" rel="noopener" style="color: var(--accent); font-size: 12px;">{{ r.value }}</a>
              </td>
              <td v-else>{{ r.value }}</td>
              <td class="prov" v-if="data.project.provenance[r.key]">
                <span class="badge">{{ data.project.provenance[r.key] }}</span>
              </td>
              <td v-else></td>
            </tr>
          </tbody>
        </table>
        <!-- 两条说明互不排斥：可同时有报告关联和学科名推导（V2-005） -->
        <div class="hint" v-if="data.project.report_url">
          结题报告链接与关键词来自 NSTRS 科技报告元数据的两级关联（2,438 条）：
          provenance 标 nstrs:strict = 交付包严格关联（665 条），
          nstrs:pi_title_unit = 负责人/标题/单位三元组唯一匹配（1,773 条）。
          source_proposal_year 不是批准年，未参与关联。
        </div>
        <div class="hint" v-if="Number(data.project.subject_names_derived) === 1">
          学科名由申请代码映射推导而来（2019 学科树 + 门户现行名），非来源页面原文。
        </div>
        </template>
      </DataState>
    </div>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}
.drawer {
  width: min(620px, 92vw);
  height: 100%;
  background: var(--panel);
  border-left: 1px solid var(--border);
  padding: 20px 24px;
  overflow-y: auto;
}
.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.drawer-header h3 { margin: 0; }
.conflicts {
  background: color-mix(in srgb, var(--warn) 8%, var(--panel-2));
  border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border));
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 20px;
}
.conflicts h4 { margin: 0 0 10px 0; }
.conflict-table { width: 100%; font-size: 12px; margin-bottom: 8px; }
.conflict-table th { text-align: left; color: var(--muted); font-weight: normal; padding: 2px 8px; }
.conflict-table td { padding: 2px 8px; }
.conflict-table .selected td { color: var(--text); }
.conflict-table .dropped td { color: var(--warn); }
.detail-table { width: 100%; font-size: 13px; }
.detail-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.field-label { color: var(--muted); width: 110px; white-space: nowrap; }
.prov { width: 60px; }
.pager-btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--accent);
  border-radius: 8px;
  padding: 6px 16px;
  cursor: pointer;
  font-size: 13px;
}
.pager-btn:hover { border-color: var(--accent); }
</style>
