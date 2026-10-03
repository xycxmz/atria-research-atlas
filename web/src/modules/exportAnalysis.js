/**
 * 分析摘要 Markdown（S3 / V2-014）：把「问题 → 筛选 → 样本 → 指标 → 来源限制」
 * 打包成一个别人能据此复查的结果。所有内容来自已应用查询与已显示结果，
 * 不生成 AI 结论。
 *
 * 摘要字段：生成时间、数据快照哈希、数据基准、已应用筛选（含复现链接）、
 * 样本计数、指标定义、本页明细表、来源与限制。
 */

const FILTER_LABELS = [
  ['q', '关键词'],
  ['year', '批准年'],
  ['dept', '学部'],
  ['inst', '依托单位'],
  ['type', '项目类别'],
  ['subj', '一级学科'],
]

export function describeFilters(applied) {
  const out = []
  for (const [key, label] of FILTER_LABELS) {
    if (applied && applied[key] != null && String(applied[key]).trim() !== '') {
      out.push([label, String(applied[key])])
    }
  }
  return out
}

/** 重建深链：与 Explorer 写 URL 的参数同构 */
export function rebuildLink(applied) {
  if (!applied) return ''
  const qs = new URLSearchParams(
    Object.entries(applied).filter(([, v]) => v !== '' && v != null)
  ).toString()
  if (typeof location === 'undefined') return qs ? `#/explorer?${qs}` : '#/explorer'
  return `${location.origin}${location.pathname}#/explorer${qs ? '?' + qs : ''}`
}

// Markdown 表格转义：管道、换行
function cell(v) {
  const s = v == null || v === '' ? '' : String(v)
  return s.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ')
}

const TABLE_COLS = [
  ['grant_no', '批准号'],
  ['title', '题目'],
  ['pi', '负责人'],
  ['institution', '依托单位'],
  ['award_year', '批准年'],
  ['grant_type', '类别'],
  ['division_name', '学部'],
  ['amount_wan', '金额(万元)'],
  ['amount_inferred', '推断'],
  ['sources', '来源'],
]

export function buildSummaryMarkdown({ applied, result, snapshot, generatedAt }) {
  const at = generatedAt || new Date().toISOString()
  const snap = snapshot || {}
  const lines = []
  lines.push('# NSFC 库内样本 · 分析摘要')
  lines.push('')
  lines.push(`- 生成时间：${at}`)
  lines.push(`- 数据快照：unified.db \`${snap.unified_db || '—'}\` · analysis.json \`${snap.analysis || '—'}\``)
  lines.push('- 数据基准：**库内样本**（按结题年度采入），不是全国全量明细')
  lines.push('')
  lines.push('## 已应用筛选（可由此重建查询）')
  const filters = describeFilters(applied)
  if (filters.length) {
    for (const [label, value] of filters) lines.push(`- ${label}：${value}`)
  } else {
    lines.push('- 无筛选条件（全部库内样本）')
  }
  lines.push(`- 复现链接：<${rebuildLink(applied)}>`)
  lines.push('')
  lines.push('## 样本计数')
  const total = result?.total ?? 0
  const page = result?.page ?? 1
  const size = result?.size ?? 20
  const rows = result?.rows ?? []
  lines.push(`- 命中项目：${total.toLocaleString('zh-CN')} 条（每页 ${size} 条，本页为第 ${page} 页）`)
  lines.push(`- 本摘要附表为本页 ${rows.length} 条明细；如需更多行请翻页后再次导出，或使用「导出全部命中」`)
  lines.push('')
  lines.push('## 指标定义')
  lines.push('- 金额单位：万元；`amount_inferred=1` = 来源未给单位、按量级推断的值')
  lines.push('- 学科名：由申请代码映射（2019 学科树 + 门户现行名），非全部来自来源页面原文')
  lines.push('- 项目类别：规范化到门户现行名，原始写法见 `grant_type_raw`')
  lines.push('- 合并优先级：基金委门户 > LetPub > 第三方交付包；冲突不丢弃，留档可查')
  lines.push('- 门户聚合与年报聚合两套官方基数部分年份不一致：并列呈现，不相加、不取平均')
  lines.push('')
  lines.push('## 本页明细')
  lines.push('| ' + TABLE_COLS.map(([, label]) => label).join(' | ') + ' |')
  lines.push('|' + TABLE_COLS.map(() => '---').join('|') + '|')
  for (const r of rows) {
    lines.push('| ' + TABLE_COLS.map(([k]) => cell(r[k])).join(' | ') + ' |')
  }
  lines.push('')
  lines.push('## 来源与限制')
  lines.push('- 库内覆盖：2017/2018 批准年约 93%，2020 年 16.7%，2021 年后不足 2%（见应用内覆盖率页）')
  lines.push('- 门户结题项目检索接口已下线（2026-10-03 探测确认），缺口按既定事实呈现，不再续采')
  lines.push('- NSTRS 报告只关联已有批准号的元数据（交付包严格关联 + 三元组匹配），不随摘要分发报告正文')
  lines.push('- 本摘要由应用按已应用条件导出，不包含 AI 生成的结论或解读')
  lines.push('')
  return lines.join('\n')
}
