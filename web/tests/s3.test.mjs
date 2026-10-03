// S3（V2-014）回归：分析摘要、全筛选导出的上限/进度/取消、导出文件名与已应用状态一致。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { buildSummaryMarkdown, rebuildLink, describeFilters } from '../src/modules/exportAnalysis'

// ------- 摘要内容（V2-014） -------

const APPLIED = { q: '自噬', year: '2018', dept: '医学科学部', inst: '', type: '', subj: '', page: 2, size: 20 }
const RESULT = {
  total: 42, page: 2, size: 20,
  rows: [
    { grant_no: '81800001', title: '含管道|与换行\n的题目', pi: '张三', institution: '甲大学',
      award_year: 2018, grant_type: '面上项目', division_name: '医学科学部',
      amount_wan: 60, amount_inferred: 0, sources: '["grok"]' },
    { grant_no: '81800002', title: '乙题目', pi: '李四', institution: '乙大学',
      award_year: 2018, grant_type: '青年科学基金项目（C类）', division_name: '医学科学部',
      amount_wan: 24.5, amount_inferred: 1, sources: '["pkg","grok"]' },
  ],
}
const SNAPSHOT = { unified_db: '0a9427476ea0', analysis: '4d1645fe27ed' }

describe('分析摘要（S3-A）', () => {
  const md = buildSummaryMarkdown({ applied: APPLIED, result: RESULT, snapshot: SNAPSHOT })

  it('含筛选与可重建的复现链接', () => {
    expect(md).toContain('关键词：自噬')
    expect(md).toContain('批准年：2018')
    expect(md).toContain('学部：医学科学部')
    const link = rebuildLink(APPLIED)
    expect(link).toContain('#/explorer?q=' + encodeURIComponent('自噬'))
    expect(link).toContain('year=2018')
    expect(md).toContain(link)
  })

  it('样本计数与页面一致', () => {
    expect(md).toContain('命中项目：42 条')
    expect(md).toContain('本页为第 2 页')
    expect(md).toContain('本页 2 条明细')
  })

  it('含快照哈希与数据基准声明', () => {
    expect(md).toContain('0a9427476ea0')
    expect(md).toContain('4d1645fe27ed')
    expect(md).toContain('不是全国全量明细')
  })

  it('含指标定义与口径护栏', () => {
    expect(md).toContain('amount_inferred=1')
    expect(md).toContain('基金委门户 > LetPub > 第三方交付包')
    expect(md).toContain('不相加、不取平均')
  })

  it('含来源与限制、明确无 AI 结论', () => {
    expect(md).toContain('来源与限制')
    expect(md).toContain('接口已下线')
    expect(md).toContain('不包含 AI 生成的结论')
  })

  it('明细表转义管道与换行，行数与结果一致', () => {
    expect(md).toContain('含管道\\|与换行 的题目')
    const tableRows = md.split('\n').filter((l) => l.startsWith('| 8180000'))
    expect(tableRows.length).toBe(2)
    expect(tableRows[0]).toContain('60')
    expect(tableRows[1]).toContain('24.5')
  })

  it('无筛选时也能重建（空条件不报错）', () => {
    const md2 = buildSummaryMarkdown({ applied: null, result: RESULT, snapshot: null })
    expect(md2).toContain('无筛选条件')
    expect(md2).toContain('unified.db `—`')
    expect(md2).toContain('81800001')
  })

  it('describeFilters 忽略空值', () => {
    expect(describeFilters({ q: '甲', year: '', dept: null })).toEqual([['关键词', '甲']])
    expect(describeFilters(null)).toEqual([])
  })
})

// ------- Explorer 导出交互（S3-A/B） -------

let pending = null
let callCount = 0

vi.mock('../src/api', () => ({
  getProjects: vi.fn((params, signal) => {
    callCount += 1
    return new Promise((res, rej) => {
      if (signal && signal.aborted) {
        const e = new Error('The user aborted a request')
        e.name = 'AbortError'
        return rej(e)
      }
      pending = { res, params }
    })
  }),
  getHealth: vi.fn(() => Promise.resolve({
    status: 'ready', missing: [], corrupt: [],
    snapshot: SNAPSHOT,
  })),
}))

vi.mock('../src/components/BaseChart.vue', () => ({
  default: { name: 'BaseChartStub', template: '<div class="chart-stub"></div>' },
}))

const Explorer = (await import('../src/views/Explorer.vue')).default

function flushPending(total) {
  const p = pending
  pending = null
  const remaining = Math.max(0, total - (p.params.page - 1) * p.params.size)
  p.res({
    total, page: p.params.page, size: p.params.size,
    rows: Array.from({ length: Math.min(p.params.size, remaining) }, (_, i) => ({
      grant_no: String(80000000 + p.params.page * 1000 + i),
      title: '题目' + i, pi: '张三', institution: '甲大学', award_year: 2018,
      grant_type: '面上项目', division_name: '医学科学部', amount_wan: 60,
      sources: '["grok"]',
    })),
  })
}

function captureDownloads() {
  const captured = []
  const orig = HTMLAnchorElement.prototype.click
  HTMLAnchorElement.prototype.click = function () { captured.push(this.download) }
  return { captured, restore: () => { HTMLAnchorElement.prototype.click = orig } }
}

describe('Explorer 导出（S3-A/B）', () => {
  beforeEach(() => {
    callCount = 0
    pending = null
    localStorage.clear()
    history.replaceState(null, '', '#/overview')
  })

  it('带 page≠1 的 URL 恢复只发一次请求（V2-010 重复请求回归）', async () => {
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('自噬') + '&page=2')
    const w = mount(Explorer)
    await new Promise(r => setTimeout(r, 10))
    expect(callCount).toBe(1)
    flushPending(42)
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.result.total).toBe(42)
    expect(w.vm.result.page).toBe(2)
  })

  it('导出区有三个按钮；摘要文件名读已应用快照', async () => {
    // 带参直链建立已应用查询（page=2 的自噬×2018×医学）
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('自噬') + '&year=2018&dept=' + encodeURIComponent('医学科学部') + '&page=2')
    const w = mount(Explorer)
    flushPending(42)
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.applied.q).toBe('自噬')
    const btns = [...w.findAll('button')].map(b => b.text())
    expect(btns).toContain('导出本页 CSV')
    expect(btns).toContain('导出分析摘要（Markdown）')
    expect(btns).toContain('导出全部命中（上限 10,000 条）')

    const { captured, restore } = captureDownloads()
    await w.vm.exportSummary()
    restore()
    expect(captured[0]).toBe('nsfc_摘要_自噬_2018_医学科学部_p2.md')
  })

  it('超额命中拒绝全量导出且不发额外请求', async () => {
    const w = mount(Explorer)
    flushPending(20000)
    await new Promise(r => setTimeout(r, 10))
    const before = callCount
    await w.vm.exportAll()
    expect(w.vm.exportJob.error).toContain('超过全量导出上限')
    expect(callCount).toBe(before)   // 不翻页、不预拉
  })

  it('全额导出逐页拉取、进度推进、文件名带条数', async () => {
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('自噬') + '&year=2018&dept=' + encodeURIComponent('医学科学部'))
    const w = mount(Explorer)
    flushPending(150)
    await new Promise(r => setTimeout(r, 10))
    const before = callCount
    const p = w.vm.exportAll()
    // 第 1 页（size=100）
    await new Promise(r => setTimeout(r, 5))
    expect(w.vm.exportJob.active).toBe(true)
    expect(w.vm.exportJob.total).toBe(150)
    flushPending(150)
    // 第 2 页（余 50 条）
    await new Promise(r => setTimeout(r, 5))
    flushPending(150)
    const { captured, restore } = captureDownloads()
    await p
    restore()
    expect(callCount - before).toBe(2)
    expect(w.vm.exportJob.fetched).toBe(150)
    expect(captured[0]).toBe('nsfc_全部_自噬_2018_医学科学部_150条.csv')
  })

  it('取消后停止翻页并复位状态', async () => {
    const w = mount(Explorer)
    flushPending(150)
    await new Promise(r => setTimeout(r, 10))
    const before = callCount
    const p = w.vm.exportAll()
    await new Promise(r => setTimeout(r, 5))
    w.vm.cancelExport()
    flushPending(150)   // 第 1 页回包
    await p
    await new Promise(r => setTimeout(r, 5))
    expect(w.vm.exportJob.active).toBe(false)
    // 取消后不再有第 2 页请求
    expect(callCount - before).toBe(1)
  })
})
