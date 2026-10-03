// S2 工作包的回归（V2-010 / V2-011）：请求序保护、URL 状态、草稿/已应用分离、产物未就绪态。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createLatest } from '../src/modules/latestGuard'
import { readUrl, writeUrl } from '../src/modules/urlState'
import DataState from '../src/components/DataState.vue'

// ------- latestGuard：慢 A 快 B，旧回包作废 -------

describe('latestGuard', () => {
  it('晚到的回包被丢弃', () => {
    const g = createLatest()
    const a = g.begin()
    const b = g.begin()
    expect(g.isLatest(a)).toBe(false)
    expect(g.isLatest(b)).toBe(true)
  })

  it('bump 作废全部在途请求', () => {
    const g = createLatest()
    const a = g.begin()
    g.bump()
    expect(g.isLatest(a)).toBe(false)
  })
})

// ------- urlState：hash 读写与空值丢弃 -------

describe('urlState', () => {
  beforeEach(() => {
    history.replaceState(null, '', '#/overview')
  })

  it('写入后读回页面与参数', () => {
    writeUrl('explorer', { q: '深度学习', page: 2, dept: '' })
    // URLSearchParams 按标准百分号编码 UTF-8
    expect(location.hash).toBe('#/explorer?q=' + encodeURIComponent('深度学习') + '&page=2')
    const { page, params } = readUrl()
    expect(page).toBe('explorer')
    expect(params.q).toBe('深度学习')
    expect(params.page).toBe('2')
  })

  it('空 hash 默认首页', () => {
    history.replaceState(null, '', '#')
    const { page } = readUrl()
    expect(page).toBe('home')
  })

  it('相同状态不产生新的历史步', () => {
    writeUrl('explorer', { q: '甲' })
    const before = history.length
    writeUrl('explorer', { q: '甲' })
    expect(history.length).toBe(before)
  })
})

// ------- DataState：五态显示（V2-011） -------

describe('DataState', () => {
  it('加载中', () => {
    const w = mount(DataState, { props: { loading: true } })
    expect(w.text()).toContain('加载中')
  })

  it('普通错误带重试按钮', async () => {
    const w = mount(DataState, { props: { error: new Error('网络断了') } })
    expect(w.text()).toContain('加载失败')
    expect(w.text()).toContain('网络断了')
    await w.find('button').trigger('click')
    expect(w.emitted('retry')).toBeTruthy()
  })

  it('产物未就绪显示构建指引而非单纯失败', () => {
    const w = mount(DataState, {
      props: { error: { kind: 'unavailable', message: '产物未就绪：analysis.json（missing）', missing: ['analysis'] } },
    })
    expect(w.text()).toContain('数据产物未就绪')
    expect(w.text()).toContain('merge.build')
    expect(w.text()).not.toContain('加载失败')
  })

  it('空结果与正常内容', () => {
    const w = mount(DataState, { props: { empty: true, emptyText: '没有项目' } })
    expect(w.text()).toContain('没有项目')
    const w2 = mount(DataState, { slots: { default: '<div>内容</div>' } })
    expect(w2.text()).toContain('内容')
  })
})

// ------- Explorer：序保护 / 草稿隔离 / URL 恢复（V2-010） -------

let resolveNext = null
let pending = []
let callCount = 0

vi.mock('../src/api', () => ({
  getProjects: vi.fn((params) => {
    callCount += 1
    const p = new Promise((res) => {
      pending.push({ res, params, call: callCount })
    })
    return p
  }),
  getProject: vi.fn(() => Promise.resolve({ found: true, project: {}, conflicts: [] })),
}))

vi.mock('../src/components/BaseChart.vue', () => ({
  default: { name: 'BaseChartStub', template: '<div class="chart-stub"></div>' },
}))

const Explorer = (await import('../src/views/Explorer.vue')).default

function flushPending() {
  for (const p of pending.splice(0)) p.res({
    total: 1, page: 1, size: 20,
    rows: [{ grant_no: '1150000' + p.call, title: '结果' + p.call, sources: '["grok"]' }],
  })
}

describe('Explorer.vue 请求序保护与草稿分离', () => {
  beforeEach(() => {
    callCount = 0
    pending = []
    localStorage.clear()
    history.replaceState(null, '', '#/overview')
  })

  it('慢 A 快 B：B 先回 A 后回，最终显示 B', async () => {
    const w = mount(Explorer)
    flushPending()          // 挂载时的初始查询先回包
    await new Promise(r => setTimeout(r, 10))
    w.vm.q = '甲'
    w.vm.submit()           // A：后回
    w.vm.q = '乙'
    w.vm.submit()           // B：先回
    const [a, b] = pending.splice(0)
    b.res({ total: 1, page: 1, size: 20, rows: [{ grant_no: 'B', title: '结果B', sources: '[]' }] })
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.result.rows[0].grant_no).toBe('B')
    // A 后到：token 已被 B 超越，必须丢弃，不覆盖 B
    a.res({ total: 1, page: 1, size: 20, rows: [{ grant_no: 'A', title: '结果A', sources: '[]' }] })
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.result.rows[0].grant_no).toBe('B')
    w.unmount()
  })

  it('页码重置不产生重复请求', async () => {
    const w = mount(Explorer)
    await new Promise(r => setTimeout(r, 10))
    flushPending()
    await new Promise(r => setTimeout(r, 10))
    w.vm.page = 3
    w.vm.q = '甲'
    const before = callCount
    w.vm.submit()          // 触发 page 1→watch + 显式 load，只能一次请求
    expect(callCount).toBe(before + 1)
    flushPending()
    w.unmount()
  })

  it('导出文件名读已应用快照，不读编辑中的草稿', async () => {
    const w = mount(Explorer)
    w.vm.q = '甲'
    w.vm.submit()
    flushPending()
    await new Promise(r => setTimeout(r, 10))
    // 草稿改为「乙」但没点检索
    w.vm.q = '乙'
    let captured = null
    const orig = HTMLAnchorElement.prototype.click
    HTMLAnchorElement.prototype.click = function () { captured = this.download }
    w.vm.exportCSV()
    HTMLAnchorElement.prototype.click = orig
    expect(captured).toBe('nsfc_甲_p1.csv')
    w.unmount()
  })

  it('URL 参数在挂载时恢复', async () => {
    history.replaceState(null, '', '#/explorer?q=abc&page=2')
    const w = mount(Explorer)
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.q).toBe('abc')
    expect(w.vm.page).toBe(2)
    expect(w.vm.applied.q).toBe('abc')
    flushPending()
    w.unmount()
  })

  it('已应用查询写入 URL 与最近查询', async () => {
    const w = mount(Explorer)
    w.vm.q = '深度学习'
    w.vm.submit()
    expect(location.hash).toContain('q=' + encodeURIComponent('深度学习'))
    const saved = JSON.parse(localStorage.getItem('nsfc_last_query'))
    expect(saved.q).toBe('深度学习')
    flushPending()
    w.unmount()
  })

  it('无 URL 参数时恢复上次查询（继续上次）', async () => {
    localStorage.setItem('nsfc_last_query', JSON.stringify({ q: '上次', year: '2018', page: 1, size: 20 }))
    const w = mount(Explorer)
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.q).toBe('上次')
    expect(w.vm.year).toBe('2018')
    expect(w.vm.applied.year).toBe('2018')
    flushPending()
    w.unmount()
  })
})
