// R2 评审反例的失败夹具（V2R2-001/002）：修复前应当红，修复后转绿。
// 依据 H:/codex/project-advice/pilots/atria-demo-review/2026-10-03-v2-r2/REVIEW.md
// 的两个外置反例 + 范围携带丢失；正对照同文件。
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { writeUrl } from '../src/modules/urlState'
import { setScope, clearScope, getScope, host } from '../src/modules/scope'

let pendingQueue = []
let callCount = 0
let calls = []

vi.mock('../src/api', () => ({
  getProjects: vi.fn((params, signal) => {
    callCount += 1
    calls.push({ ...params })
    return new Promise((res, rej) => {
      if (signal && signal.aborted) {
        const e = new Error('aborted'); e.name = 'AbortError'; return rej(e)
      }
      pendingQueue.push({ res, params })
    })
  }),
  getAnalysis: vi.fn(() => Promise.resolve({
    top_subjects_l1: [], top_subjects_l2: [], coverage: { by_year: [] },
    by_source: { contributions: {} },
    meta: { total_projects: 165200, year_min: 2004, year_max: 2024 },
  })),
  getAdvanced: vi.fn(() => Promise.resolve({
    top_subjects_l2: [], keyword_freq: { overall: [], by_division: [], by_year: [] },
    dept_year_matrix: { departments: [], years: [], counts: [] },
  })),
  getHealth: vi.fn(() => Promise.resolve({ status: 'ready', snapshot: { unified_db: 'h' } })),
}))

vi.mock('../src/components/BaseChart.vue', () => ({
  default: { name: 'BaseChartStub', template: '<div class="chart-stub"></div>' },
}))

const Explorer = (await import('../src/views/Explorer.vue')).default

/** 解开队首请求（按请求实际发出顺序，与时序无关、不丢请求） */
function flushOne(total, marker) {
  const p = pendingQueue.shift()
  if (!p) throw new Error('flushOne: 没有待决请求')
  const remaining = Math.max(0, total - (p.params.page - 1) * p.params.size)
  p.res({
    total, page: p.params.page, size: p.params.size,
    rows: Array.from({ length: Math.min(p.params.size, remaining) }, (_, i) => ({
      grant_no: String(80000000 + p.params.page * 1000 + i),
      title: '题目' + marker + i, pi: '张三', institution: '甲大学', award_year: 2018,
      grant_type: '面上项目', division_name: '医学科学部', amount_wan: 60,
      sources: '["grok"]',
    })),
  })
}

async function flushWhenReady(total, marker) {
  for (let i = 0; i < 200 && !pendingQueue.length; i++) {
    await new Promise(r => setTimeout(r, 1))
  }
  flushOne(total, marker)
}

function captureDownloads() {
  const captured = []
  const orig = HTMLAnchorElement.prototype.click
  HTMLAnchorElement.prototype.click = function () { captured.push(this.download) }
  return { captured, restore: () => { HTMLAnchorElement.prototype.click = orig } }
}

// ============ V2R2-002：导出与结果/查询绑定 ============

describe('V2R2-002：每份导出绑定独立的查询与结果快照', () => {
  beforeEach(() => {
    callCount = 0
    pendingQueue = []
    calls = []
    localStorage.clear()
    history.replaceState(null, '', '#/overview')
  })

  it('反例：A 结果尚在显示、applied 已切 B，本页导出必须绑 result 对应的查询', async () => {
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('查询A') + '&page=1')
    const w = mount(Explorer)
    flushOne(5, 'A')
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.result.rows[0].title).toContain('A')

    // 提交 B（未回包）：result 仍是 A、applied 已是 B
    w.vm.q = '查询B'
    w.vm.submit()
    await new Promise(r => setTimeout(r, 5))
    expect(w.vm.applied.q).toBe('查询B')
    expect(w.vm.result.rows[0].title).toContain('A')

    // 导出的文件名必须与「正在显示的行」同源（A）
    const { captured, restore } = captureDownloads()
    w.vm.exportCSV()
    restore()
    expect(captured[0]).toContain('查询A')
  })

  it('正对照：正常顺序下文件名与行同源', async () => {
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('查询A') + '&page=1')
    const w = mount(Explorer)
    flushOne(5, 'A')
    await new Promise(r => setTimeout(r, 10))
    const { captured, restore } = captureDownloads()
    w.vm.exportCSV()
    restore()
    expect(captured[0]).toContain('查询A')
  })

  it('反例：全量导出期间提交新查询，导出循环的页参数必须恒为任务冻结的查询', async () => {
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('查询A'))
    const w = mount(Explorer)
    flushOne(150, 'A')
    await new Promise(r => setTimeout(r, 10))
    const callsBefore = calls.length
    const p = w.vm.exportAll()   // 任务冻结 A，size=100，共 2 页
    await flushWhenReady(150, 'A')       // 第 1 页回包
    // 第 2 页发出前提交 B（导出循环读的是冻结 jobQuery，不是 live applied）
    w.vm.q = '查询B'
    w.vm.submit()
    // 消化陆续到达的请求（导出第 2 页 / B 的重载），直到导出任务结束
    let guard = 0
    while (guard++ < 50) {
      while (pendingQueue.length) flushOne(150, 'x')
      await new Promise(r => setTimeout(r, 20))
      if (!w.vm.exportJob.active) break
    }
    await p
    // 导出任务期间的页请求（size=100）必须全部 q=查询A
    const exportPages = calls.slice(callsBefore).filter(c => c.size === 100)
    expect(exportPages.length).toBe(2)
    for (const c of exportPages) {
      expect(c.q).toBe('查询A')
    }
  })
})

// ============ V2R2-001：范围条件跨页保持与真实生效 ============

describe('V2R2-001：范围条只展示真正作用于当前结果的条件', () => {
  beforeEach(() => {
    clearScope()
    history.replaceState(null, '', '#/overview')
  })

  it('查询页建立 dept=医学&year=2018 后，scope 与 URL 都带 canonical division', async () => {
    history.replaceState(null, '', '#/explorer?q=x&dept=' + encodeURIComponent('医学科学部') + '&year=2018')
    const w = mount(Explorer)
    flushOne(9620, 'A')
    await new Promise(r => setTimeout(r, 10))
    expect(getScope().division).toBe('医学科学部')
    expect(getScope().year).toBe('2018')
    w.unmount()
  })

  it('反例修复：导航到其他页用 writeScopeCarry 携带，学部与年份不丢', async () => {
    history.replaceState(null, '', '#/explorer?q=x&dept=' + encodeURIComponent('医学科学部') + '&year=2018')
    const w = mount(Explorer)
    flushOne(9620, 'A')
    await new Promise(r => setTimeout(r, 10))
    expect(getScope().division).toBe('医学科学部')
    expect(getScope().year).toBe('2018')

    // 模拟 App.go 的普通导航（携带后新页 URL 与 scope 均含两个维度）
    const { writeScopeCarry } = await import('../src/modules/scope')
    writeScopeCarry('subjects')
    expect(location.hash).toContain('division=' + encodeURIComponent('医学科学部'))
    expect(location.hash).toContain('year=2018')

    const { syncScopeFromUrl } = await import('../src/modules/scope')
    syncScopeFromUrl()
    expect(getScope().division).toBe('医学科学部')
    expect(getScope().year).toBe('2018')
    w.unmount()
  })

  it('刷新直链：URL 的 dept（检索页命名）参数也重建学部 scope', async () => {
    history.replaceState(null, '', '#/explorer?q=x&dept=' + encodeURIComponent('医学科学部') + '&year=2018')
    const { syncScopeFromUrl } = await import('../src/modules/scope')
    syncScopeFromUrl()
    expect(getScope().division).toBe('医学科学部')
    expect(getScope().year).toBe('2018')
  })

  it('Subjects 的 applyScope 只接收 division——year/类别在该页不生效须显式标记', async () => {
    const Subjects = (await import('../src/views/Subjects.vue')).default
    const w = mount(Subjects)
    await new Promise(r => setTimeout(r, 10))
    // 本页只声明支持学部
    expect(w.vm.scopeSupport).toEqual(['division'])
    w.unmount()
  })
})

// ============ V2R2-001 补充：ScopeBar 按页声明的维度决定就地应用或跳转 ============

describe('V2R2-001 补充：维度变更在生效页就地应用、不生效页才跳转', () => {
  beforeEach(() => {
    clearScope()
    history.replaceState(null, '', '#/overview')
  })
  afterEach(() => {
    host.applyScope = null
    host.supports = []
    host.go = null
  })

  it('检索页（三维度 live）改年份：就地应用、不导航、不丢已有查询', async () => {
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('自噬') + '&dept=' + encodeURIComponent('医学科学部'))
    const w = mount(Explorer)
    flushOne(589, 'A')
    await new Promise(r => setTimeout(r, 10))
    const sb = mount((await import('../src/components/ScopeBar.vue')).default)
    host.go = vi.fn()
    await sb.find('input[aria-label="年份"]').setValue('2019')
    expect(host.go).not.toHaveBeenCalled()        // 不跳转（跳转会丢 q/dept 且不重载）
    expect(w.vm.applied.q).toBe('自噬')          // 原查询保留
    expect(w.vm.applied.dept).toBe('医学科学部')
    expect(w.vm.applied.year).toBe('2019')       // 年份就地生效
    flushOne(589, 'B')
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.resultQuery.year).toBe('2019')
    sb.unmount()
    w.unmount()
  })

  it('只支持学部的页改年份：带范围转检索，不假装在本页应用', async () => {
    host.applyScope = vi.fn()
    host.supports = ['division']
    host.go = vi.fn()
    setScope({ division: '医学科学部' })
    const sb = mount((await import('../src/components/ScopeBar.vue')).default)
    await sb.find('input[aria-label="年份"]').setValue('2018')
    expect(host.go).toHaveBeenCalledWith('explorer',
      expect.objectContaining({ dept: '医学科学部', year: '2018', page: '1' }))
    expect(host.applyScope).not.toHaveBeenCalled()  // 本页不生效就不调用页内应用
    sb.unmount()
  })

  it('检索页清除范围：三维度就地清空，原查询保留', async () => {
    history.replaceState(null, '', '#/explorer?q=' + encodeURIComponent('自噬') +
      '&dept=' + encodeURIComponent('医学科学部') + '&year=2018&type=' + encodeURIComponent('面上项目'))
    const w = mount(Explorer)
    flushOne(100, 'A')
    await new Promise(r => setTimeout(r, 10))
    const sb = mount((await import('../src/components/ScopeBar.vue')).default)
    host.go = vi.fn()
    await sb.find('button.scope-clear').trigger('click')
    expect(host.go).not.toHaveBeenCalled()
    expect(w.vm.applied.q).toBe('自噬')
    expect(w.vm.applied.dept).toBe('')
    expect(w.vm.applied.year).toBe('')
    expect(w.vm.applied.type).toBe('')
    sb.unmount()
    w.unmount()
  })

  it('带 scope 直进学科分布：学部筛选立即生效（不是全库）', async () => {
    const Subjects = (await import('../src/views/Subjects.vue')).default
    setScope({ division: '医学科学部' })
    const w = mount(Subjects)
    await new Promise(r => setTimeout(r, 10))
    // 评审证据「学部变全部」：修复后挂载即同步，图表标题不再停在（全库）
    expect(w.vm.deptFilter).toBe('医学科学部')
    expect(w.vm.scopeLabel).toContain('医学科学部')
    w.unmount()
  })

  it('Keywords 分学部模式点词柱：携带学部转检索（同口径）', async () => {
    const Keywords = (await import('../src/views/Keywords.vue')).default
    const w = mount(Keywords)
    await new Promise(r => setTimeout(r, 10))
    w.vm.scope = 'division'
    w.vm.divisionName = '医学科学部'
    host.go = vi.fn()
    w.vm.onBarClick({ name: '自噬' })
    expect(host.go).toHaveBeenCalledWith('explorer',
      expect.objectContaining({ q: '自噬', dept: '医学科学部', page: '1' }))
    w.vm.scope = 'year'
    w.vm.year = 2018
    w.vm.onBarClick({ name: '自噬' })
    expect(host.go).toHaveBeenLastCalledWith('explorer',
      expect.objectContaining({ q: '自噬', year: '2018', page: '1' }))
    w.unmount()
  })
})


// ============ V2R2-003 键盘可达（低风险子集） ============

describe('V2R2-003：键盘任务路径', () => {
  beforeEach(() => {
    localStorage.clear()
    history.replaceState(null, '', '#/home')
  })

  it('Home 示例卡片是原生 button（可 Tab 聚焦）', async () => {
    const Home = (await import('../src/views/Home.vue')).default
    const w = mount(Home)
    await new Promise(r => setTimeout(r, 50))
    const cards = w.findAll('button.card.question')
    expect(cards.length).toBeGreaterThanOrEqual(3)
    expect(cards[0].element.tagName).toBe('BUTTON')
    // 点击路径不变（鼠标与键盘同一 handler）
    await cards[0].trigger('click')
    expect(w.emitted('go')).toBeTruthy()
    expect(w.emitted('go')[0][0]).toBe('explorer')
  })

  it('详情抽屉有 dialog 语义，Escape 关闭', async () => {
    const ProjectDetail = (await import('../src/views/ProjectDetail.vue')).default
    const w = mount(ProjectDetail, { props: { grantNo: '82103025' } })
    await new Promise(r => setTimeout(r, 50))
    expect(w.find('[role="dialog"]').exists()).toBe(true)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await new Promise(r => setTimeout(r, 10))
    expect(w.emitted('close')).toBeTruthy()
    w.unmount()
  })
})
