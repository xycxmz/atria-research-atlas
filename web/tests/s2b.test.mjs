// S2 剩余工作包（W4/W5/W6/W8）的回归：范围条、图表点击转检索、首页示例问题、口径对比。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setScope, clearScope, getScope, syncScopeFromUrl, host } from '../src/modules/scope'
import { writeUrl } from '../src/modules/urlState'

vi.mock('../src/api', () => ({
  getAnalysis: vi.fn(() => Promise.resolve({
    meta: { total_projects: 165200, year_min: 2004, year_max: 2024 },
    top_institutions: [{ institution: '甲大学', count: 100 }],
    by_department: [
      { division_name: '数理科学部', count: 16405, amount: 100, valid_n: 16000 },
      { division_name: '医学科学部', count: 28596, amount: 200, valid_n: 28000 },
    ],
    top_subjects_l1: [
      { division_name: '医学科学部', subject_l1: '肿瘤学', count: 100, rank_in_scope: 1 },
    ],
    coverage: {
      by_year: [
        { year: 2023, have: 6, portal: 51542, report: 52547, rate_portal: 0.0001 },
        { year: 2022, have: 215, portal: 50012, report: 50100 },
      ],
    },
    by_source: { contributions: {} },
  })),
  getAdvanced: vi.fn(() => Promise.resolve({
    top_subjects_l1: [{ division_name: '医学科学部', subject_l1: '肿瘤学', count: 100, rank_in_scope: 1 }],
    top_subjects_l2: [{ division_name: '医学科学部', subject_l1: '肿瘤学', subject_l2: '诊疗', count: 80, amount: 100, rank_in_scope: 1 }],
    keyword_freq: { overall: [], overall_rows: 0, by_division: [], by_year: [] },
    dept_year_matrix: { departments: ['医学科学部'], years: [2017, 2018], counts: [[5, 10]] },
  })),
}))

vi.mock('../src/components/BaseChart.vue', () => ({
  default: { name: 'BaseChartStub', template: '<div class="chart-stub"></div>', emits: ['click'] },
}))

// ------- scope 模块 -------

describe('scope 模块（W4）', () => {
  beforeEach(() => {
    clearScope()
    history.replaceState(null, '', '#/subjects')
    host.applyScope = null
    host.go = null
  })

  it('setScope 写入 URL 的 division/year/type 参数', () => {
    setScope({ division: '数理科学部', year: '2018', grantType: '面上项目' })
    expect(location.hash).toContain('division=' + encodeURIComponent('数理科学部'))
    expect(location.hash).toContain('year=2018')
    expect(location.hash).toContain('type=' + encodeURIComponent('面上项目'))
    expect(getScope().division).toBe('数理科学部')
  })

  it('syncScopeFromUrl 从 URL 重建范围（静默，不产生历史步）', () => {
    history.replaceState(null, '', '#/subjects?division=医学科学部&type=面上项目')
    const before = history.length
    syncScopeFromUrl()
    expect(getScope().division).toBe('医学科学部')
    expect(getScope().grantType).toBe('面上项目')
    expect(history.length).toBe(before)
  })

  it('clearScope 清空维度并写回 URL', () => {
    setScope({ division: '数理科学部' })
    clearScope()
    expect(getScope().division).toBe('')
    expect(location.hash).not.toContain('division')
  })
})

// ------- ScopeBar -------

describe('ScopeBar（W4）', () => {
  beforeEach(() => {
    clearScope()
    history.replaceState(null, '', '#/subjects')
    host.applyScope = null
    host.go = null
  })

  it('展示页派生的数据基准与日期维度', async () => {
    const ScopeBar = (await import('../src/components/ScopeBar.vue')).default
    const w = mount(ScopeBar, { props: { basis: '门户聚合', dateDim: '批准+结题' } })
    expect(w.text()).toContain('门户聚合')
    expect(w.text()).toContain('批准+结题')
  })

  it('选学部时页面已注册应用函数则就地应用', async () => {
    const ScopeBar = (await import('../src/components/ScopeBar.vue')).default
    const applied = vi.fn()
    // 声明本页支持学部维度（V2R2-001 的页声明）
    host.applyScope = applied
    host.supports = ['division']
    const w = mount(ScopeBar)
    const sel = w.find('select')
    await sel.setValue('数理科学部')
    expect(applied).toHaveBeenCalledWith(expect.objectContaining({ division: '数理科学部' }))
    expect(getScope().division).toBe('数理科学部')
  })

  it('选学部时页面未注册则带条件转检索页', async () => {
    const ScopeBar = (await import('../src/components/ScopeBar.vue')).default
    const go = vi.fn()
    host.go = go
    const w = mount(ScopeBar)
    await w.find('select').setValue('医学科学部')
    expect(go).toHaveBeenCalledWith('explorer', expect.objectContaining({ dept: '医学科学部' }))
  })

  it('清除范围后再次应用', async () => {
    const ScopeBar = (await import('../src/components/ScopeBar.vue')).default
    const go = vi.fn()
    host.go = go
    setScope({ division: '医学科学部' })
    const w = mount(ScopeBar)
    await w.find('.scope-clear').trigger('click')
    expect(getScope().division).toBe('')
    expect(go).toHaveBeenCalled()
  })
})

// ------- Home：示例问题与继续上次（W6） -------

describe('Home（W6）', () => {
  beforeEach(() => {
    localStorage.clear()
    history.replaceState(null, '', '#/home')
  })

  it('三条示例问题带范围参数跳转', async () => {
    const Home = (await import('../src/views/Home.vue')).default
    const w = mount(Home)
    await new Promise(r => setTimeout(r, 50))
    const cards = w.findAll('.card.question')
    expect(cards.length).toBeGreaterThanOrEqual(3)
    // 问题一：2018 × 医学科学部
    cards[0].trigger('click')
    let ev = w.emitted('go')
    expect(ev).toBeTruthy()
    expect(ev[0][0]).toBe('explorer')
    expect(ev[0][1]).toMatchObject({ year: '2018', dept: '医学科学部' })
    // 问题二：头部单位（来自真实数据）
    cards[1].trigger('click')
    expect(w.emitted('go')[1][1]).toMatchObject({ inst: '甲大学' })
    // 问题三：覆盖率
    cards[2].trigger('click')
    expect(w.emitted('go')[2][0]).toBe('coverage')
  })

  it('localStorage 有上次查询时出现「继续上次」入口', async () => {
    const Home = (await import('../src/views/Home.vue')).default
    localStorage.setItem('nsfc_last_query', JSON.stringify({ q: '自噬', page: 1 }))
    const w = mount(Home)
    await new Promise(r => setTimeout(r, 50))
    const t = w.text()
    expect(t).toContain('继续上次')
    expect(t).toContain('自噬')
  })
})

// ------- Compare：双口径并列卡与指标表（W8） -------

describe('Compare（W8）', () => {
  it('最新共同年份双口径并列；指标表带有效N与缺失率', async () => {
    const Compare = (await import('../src/views/Compare.vue')).default
    const w = mount(Compare)
    await new Promise(r => setTimeout(r, 50))
    const t = w.text()
    expect(t).toContain('2023 年批准数对照')
    expect(t).toContain('51,542')  // 门户
    expect(t).toContain('52,547')  // 年报
    expect(t).toContain('6')       // 库内样本
    // 指标表：有效N 与缺失率（405/16405 ≈ 2.5%）
    expect(t).toContain('16,000')
    expect(t).toContain('2.5%')
    // 口径护栏在场
    expect(t).toContain('不相加不取平均')
  })
})

// ------- 图表点击转检索（W5） -------

describe('图表点击转检索（W5）', () => {
  beforeEach(() => {
    clearScope()
    history.replaceState(null, '', '#/subjects')
    host.applyScope = null
    host.go = null
  })

  it('Subjects 一级/二级学科柱点击带同口径参数', async () => {
    const Subjects = (await import('../src/views/Subjects.vue')).default
    const go = vi.fn()
    host.go = go
    const w = mount(Subjects)
    await new Promise(r => setTimeout(r, 50))
    // 图表桩不产生 ECharts 事件，直接测 handler
    w.vm.onL1Click({ name: '肿瘤学' })
    expect(go).toHaveBeenCalledWith('explorer', { subj: '肿瘤学', dept: '医学科学部', page: '1' })
    w.vm.onL2Click({ name: '诊疗' })
    expect(go).toHaveBeenLastCalledWith('explorer', { subj: '肿瘤学', dept: '医学科学部', page: '1' })
  })

  it('Keywords 词柱点击与双击行', async () => {
    const Keywords = (await import('../src/views/Keywords.vue')).default
    const go = vi.fn()
    host.go = go
    const w = mount(Keywords)
    await new Promise(r => setTimeout(r, 50))
    w.vm.onBarClick({ name: '自噬' })
    expect(go).toHaveBeenCalledWith('explorer', { q: '自噬', page: '1' })
  })

  it('Departments 热力图与堆叠柱点击', async () => {
    const Departments = (await import('../src/views/Departments.vue')).default
    const go = vi.fn()
    host.go = go
    const w = mount(Departments)
    await new Promise(r => setTimeout(r, 50))
    // 热力图：[x=年份索引, y=学部索引, 值]
    w.vm.onHeatClick({ value: [0, 0, 5] })
    expect(go).toHaveBeenCalledWith('explorer', { dept: '医学科学部', year: '2017', page: '1' })
    // 类别堆叠柱：axisValue=学部，seriesName=类别
    w.vm.onTypeStackClick({ name: '医学科学部', seriesName: '面上项目' })
    expect(go).toHaveBeenLastCalledWith('explorer', { dept: '医学科学部', type: '面上项目', page: '1' })
    // 学部×年堆叠柱：seriesName=学部，name=年
    w.vm.onStackClick({ name: '2018', seriesName: '医学科学部' })
    expect(go).toHaveBeenLastCalledWith('explorer', { dept: '医学科学部', year: '2018', page: '1' })
  })
})

// ------- Subjects 学部筛选与 scope 双向同步（W4） -------

describe('Subjects 学部双向同步（W4）', () => {
  beforeEach(() => {
    clearScope()
    history.replaceState(null, '', '#/subjects')
    host.applyScope = null
    host.go = null
  })

  it('scope 变学部 → 本页筛选跟随', async () => {
    const Subjects = (await import('../src/views/Subjects.vue')).default
    const w = mount(Subjects)
    await new Promise(r => setTimeout(r, 50))
    setScope({ division: '医学科学部' })
    await new Promise(r => setTimeout(r, 10))
    expect(w.vm.deptFilter).toBe('医学科学部')
  })

  it('本页改学部 → scope 跟随', async () => {
    const Subjects = (await import('../src/views/Subjects.vue')).default
    const w = mount(Subjects)
    await new Promise(r => setTimeout(r, 50))
    const sel = w.find('select')
    await sel.setValue('医学科学部')
    expect(getScope().division).toBe('医学科学部')
  })
})
