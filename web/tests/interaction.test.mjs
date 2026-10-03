// 关键词页/学科页/检索页的交互联动验证。
// 用 @vue/test-utils 真实派发 click/change，绕开内嵌浏览器视口不可用的问题。
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import Keywords from '../src/views/Keywords.vue'
import Subjects from '../src/views/Subjects.vue'
import Explorer from '../src/views/Explorer.vue'

// API client 打桩：返回固定的 advanced/analysis/projects 数据
const ADVANCED = {
  keyword_freq: {
    overall: [{ keyword: '自噬', count: 100 }, { keyword: '深度学习', count: 90 }],
    overall_rows: 1000,
    by_division: [
      { division_name: '医学科学部', top: [{ keyword: '肿瘤', count: 50 }] },
      { division_name: '信息科学部', top: [{ keyword: '深度学习', count: 40 }] },
    ],
    by_year: [
      { year: 2021, top: [{ keyword: '深度学习', count: 30 }] },
      { year: 2022, top: [{ keyword: '稳定性', count: 20 }] },
      // V2-002：低覆盖年度——选中时必须显示缺测，而非空榜
      { year: 2023, keyworded_n: 5, top: [], sufficient: false },
    ],
  },
  strength_by_type: [
    { grant_type: '面上项目', count: 10, avg: 56.9, median: 60, total: 569 },
  ],
  dept_year_matrix: { departments: ['医学科学部'], years: [2017], counts: [[5]] },
  close_award_matrix: { close_years: [2020], award_years: [2017], counts: [[5]] },
  top_subjects_l2: [
    { division_name: '医学科学部', subject_l1: '肿瘤学', subject_l2: '诊疗', count: 80, amount: 100 },
    { division_name: '信息科学部', subject_l1: '自动化', subject_l2: '控制', count: 70, amount: 90 },
  ],
}

const ANALYSIS = {
  top_subjects_l1: [
    { division_name: '医学科学部', subject_l1: '肿瘤学', count: 100 },
    { division_name: '信息科学部', subject_l1: '自动化', count: 90 },
  ],
  by_department: [],
  by_grant_type: [],
  meta: {},
}

// 学部×类别与单位趋势维度的桩数据
const DEPT_TYPE = {
  dept_type_matrix: {
    departments: ['医学科学部', '信息科学部'],
    types: ['面上项目', '青年科学基金项目（C类）', '地区科学基金项目', '重点项目'],
    counts: [[100, 60, 5, 2], [80, 90, 3, 1]],
    youth_ratio: [0.6, 1.125],
  },
  top_institution_years: {
    institutions: ['甲大学', '乙大学'],
    years: [2016, 2017],
    counts: [[3, 5], [2, 4]],
  },
}

vi.mock('../src/api', () => ({
  getAdvanced: vi.fn(() => Promise.resolve(JSON.parse(JSON.stringify({ ...ADVANCED, ...DEPT_TYPE })))),
  getAnalysis: vi.fn(() => Promise.resolve(JSON.parse(JSON.stringify(ANALYSIS)))),
  getProjects: vi.fn(() => Promise.resolve({
    total: 2, page: 1, size: 20,
    rows: [
      { grant_no: '11500001', title: '题目甲', pi: '张三', institution: '甲大学', award_year: 2015, close_year: 2020, grant_type: '面上项目', division_name: '医学科学部', subject_code: 'H18', subject_l1: '肿瘤学', amount_wan: 60, keywords: '自噬', sources: '["grok","pkg"]' },
      { grant_no: '11500002', title: '题目乙', pi: '李四', institution: '乙大学', award_year: 2016, close_year: 2021, grant_type: '重点项目', division_name: '信息科学部', subject_code: 'F01', subject_l1: '自动化', amount_wan: 200, keywords: '深度学习', sources: '["pkg"]' },
    ],
  })),
  // V2-005：报告链接与学科推导同时存在的真实样本
  getProject: vi.fn(() => Promise.resolve({
    found: true,
    project: {
      grant_no: '11500001', title: '题目甲', pi: '张三', institution: '甲大学',
      award_year: 2015, close_year: 2020, grant_type: '青年科学基金项目（C类）',
      grant_type_raw: '青年科学基金项目', division_name: '医学科学部',
      subject_code: 'H1801', subject_l1: '肿瘤学', subject_l2: '诊疗', subject_l3: '诊疗技术',
      subject_names_derived: 1, amount_wan: 60, amount_inferred: 0,
      keywords: '自噬', abstract_zh: '这是摘要', has_report: 1,
      sources: '["grok","atria"]', report_keywords: '自噬;凋亡',
      report_url: 'https://example.com/report/11500001',
      provenance: { grant_type: 'atria', grant_type_raw: 'atria', subject_l3: 'grok', amount_wan: 'grok', report_url: 'nstrs' },
    },
    conflicts: [],
  })),
  getConflicts: vi.fn(() => Promise.resolve({
    total: 1, page: 1, size: 20,
    fields: [{ field: 'subject_code', count: 1 }],
    classifications: [{ classification: '代码层级差（前缀关系，待核语义）', count: 1 }],
    rows: [{ grant_no: '11500001', field: 'subject_code', selected: 'A01', selected_from: 'grok', alternatives: '[{"value":"A0101","from":"atria"}]', classification: '代码层级差（前缀关系，待核语义）' }],
  })),
  // V2-004 资助率 formatter 的夹具：20%、0%、缺分母、近似标记
  getRecent: vi.fn(() => Promise.resolve({
    RECENT_YEARS: [
      {
        year: 2025,
        depts: [
          { dept: '数理科学部', general: { apply: 100, funded: 20, fundingWan: 1200 } },
          { dept: '化学科学部', general: { apply: 100, funded: 0, fundingWan: 0 } },
          { dept: '生命科学部', general: { apply: null, funded: 5, approx: 1 } },
        ],
      },
    ],
    NATIONAL_HEADLINES: {
      2024: { general: { apply: 1000, funded: 200 }, youth: { apply: 500, funded: 100 }, regional: { apply: 100, funded: 0 } },
    },
  })),
}))

// BaseChart 在 jsdom 里没有真实 canvas，ECharts 初始化会失败；打桩为空组件
vi.mock('../src/components/BaseChart.vue', () => ({
  default: { name: 'BaseChartStub', template: '<div class="chart-stub"></div>' },
}))

// scope 是全局单例：上一个测试用 UI 选过的学部会泄漏到下一个挂载
// （V2R2-001 后页挂载即同步 scope，隔离必须显式）
import { clearScope } from '../src/modules/scope'
beforeEach(() => {
  clearScope()
  localStorage.clear()
  history.replaceState(null, '', '#/overview')
})

describe('Keywords.vue 交互联动', () => {
  it('默认渲染总榜，切换到分年度后词表与 select 联动', async () => {
    const w = mount(Keywords)
    await new Promise(r => setTimeout(r, 50))
    expect(w.find('h2').text()).toContain('关键词')

    // 默认总榜
    let rows = w.findAll('tbody tr')
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain('自噬')

    // select 不应存在（scope=overall）
    expect(w.find('select').exists()).toBe(false)

    // 点击分年度
    const btns = w.findAll('.filters button')
    const yearBtn = btns.find(b => b.text() === '分年度')
    await yearBtn.trigger('click')
    await new Promise(r => setTimeout(r, 50))

    // select 出现，且 year 默认取 by_year 末项 2022
    const sel = w.find('select')
    expect(sel.exists()).toBe(true)
    expect(sel.element.value).toContain('2022')

    // 词表切换到 2022 的 top（稳定性）
    rows = w.findAll('tbody tr')
    expect(rows[0].text()).toContain('稳定性')

    // 切年份到 2021，词表变为深度学习
    await sel.setValue('2021')
    rows = w.findAll('tbody tr')
    expect(rows[0].text()).toContain('深度学习')
  })

  it('分学部切换：学部与词表联动', async () => {
    const w = mount(Keywords)
    await new Promise(r => setTimeout(r, 50))

    const divBtn = w.findAll('.filters button').find(b => b.text() === '分学部')
    await divBtn.trigger('click')
    await new Promise(r => setTimeout(r, 50))

    const sel = w.find('select')
    expect(sel.exists()).toBe(true)
    // 默认学部取第一个（医学科学部），词表是肿瘤
    expect(w.findAll('tbody tr')[0].text()).toContain('肿瘤')

    // 切到信息科学部 → 深度学习
    await sel.setValue('信息科学部')
    expect(w.findAll('tbody tr')[0].text()).toContain('深度学习')
  })
})

describe('Subjects.vue 学部筛选', () => {
  it('选择学部后 l1/l2 列表过滤', async () => {
    const w = mount(Subjects)
    await new Promise(r => setTimeout(r, 50))

    const sel = w.find('select')
    expect(sel.exists()).toBe(true)
    // 未选时 l2 明细 2 条
    expect(w.findAll('tbody tr').length).toBeGreaterThanOrEqual(2)

    // 选医学科学部后只剩 1 条
    await sel.setValue('医学科学部')
    const l2rows = w.findAll('tbody tr').filter(tr => tr.text().includes('诊疗'))
    expect(l2rows.length).toBe(1)
  })
})

describe('Departments/Institutions 新维度', () => {
  it('学部×类别堆叠图与青年:面上比提示渲染', async () => {
    const Departments = (await import('../src/views/Departments.vue')).default
    const utils = await import('@vue/test-utils')
    const w = utils.mount(Departments)
    await new Promise(r => setTimeout(r, 50))

    const texts = w.text()
    expect(texts).toContain('学部 × 资助类别构成')
    expect(texts).toContain('青年:面上')
    // 堆叠图数据注入正确：两个学部、四类别、比例与数据一致
    const opt = w.vm.typeStackOption
    expect(opt.xAxis.data).toEqual(['医学科学部', '信息科学部'])
    expect(opt.series.length).toBe(4)
    expect(opt.series[0].name).toBe('面上项目')
    expect(opt.series[1].data).toEqual([60, 90]) // 青年：医 60 / 信 90
  })

  it('Top 单位年度趋势图渲染', async () => {
    const Institutions = (await import('../src/views/Institutions.vue')).default
    const utils = await import('@vue/test-utils')
    const w = utils.mount(Institutions)
    await new Promise(r => setTimeout(r, 50))

    const texts = w.text()
    expect(texts).toContain('Top 10 单位年度立项趋势')
    expect(texts).toContain('单位 × 主导学部 Top 15')
    // 趋势数据已注入（legend 条目在 BaseChart stub 里不渲染，看组件数据）
    expect(w.vm.trendOption).toBeTruthy()
    expect(w.vm.trendOption.series.length).toBe(2)
    expect(w.vm.trendOption.series[0].name).toBe('甲大学')
    expect(w.vm.trendOption.series[1].data).toEqual([2, 4])
  })
})

describe('Keywords.vue 低覆盖年缺测（V2-002）', () => {
  it('默认年份跳过低覆盖年；选中低覆盖年显示缺测而非空榜', async () => {
    const w = mount(Keywords)
    await new Promise(r => setTimeout(r, 50))

    // 切到分年度：默认取最后一个「充分」年 2022，不是 2023
    await w.findAll('.filters button').find(b => b.text() === '分年度').trigger('click')
    await new Promise(r => setTimeout(r, 50))
    const sel = w.find('select')
    expect(sel.exists()).toBe(true)
    expect(sel.element.value).toContain('2022')
    expect(w.findAll('tbody tr')[0].text()).toContain('稳定性')

    // 选 2023（sufficient=false）
    await sel.setValue('2023')
    await new Promise(r => setTimeout(r, 50))

    // 必须出现缺测提示，且明示「不能读作没有研究热点」
    const err = w.find('.error')
    expect(err.exists()).toBe(true)
    expect(err.text()).toContain('样本不足')
    expect(err.text()).toContain('不能读作「该年没有研究热点」')
    expect(w.findAll('tbody tr').length).toBe(0)
  })
})

describe('ProjectDetail.vue 详情字段（V2-005/006）', () => {
  it('报告链接与学科推导提示同时显示，raw 保留原始类别', async () => {
    const ProjectDetail = (await import('../src/views/ProjectDetail.vue')).default
    const utils = await import('@vue/test-utils')
    const w = utils.mount(ProjectDetail, { props: { grantNo: '11500001' } })
    await new Promise(r => setTimeout(r, 50))

    const text = w.text()
    // 两类说明不再互斥（v-if/v-else-if 修复）
    expect(text).toContain('NSTRS 科技报告元数据')
    expect(text).toContain('学科名由申请代码映射推导')
    // raw 与规范化值同时保留
    expect(text).toContain('青年科学基金项目（C类）')
    expect(text).toContain('青年科学基金项目')
    // 原来缺失的字段到位
    expect(text).toContain('这是摘要')
    expect(text).toContain('诊疗技术')
    expect(text).toContain('是')
    // 推导/推断标记区分明确
    expect(text).toContain('是（申请代码推导）')
    expect(text).toContain('否（明确单位）')
  })
})

describe('Quality.vue 冲突分类（V2-007）', () => {
  it('渲染逐条分类，不出现全局「不是错误」断言', async () => {
    const Quality = (await import('../src/views/Quality.vue')).default
    const utils = await import('@vue/test-utils')
    const w = utils.mount(Quality)
    await new Promise(r => setTimeout(r, 50))

    const text = w.text()
    expect(text).toContain('逐条分类')
    expect(text).toContain('代码层级差（前缀关系，待核语义）')
    // 分类只是线索，不宣称非错误
    expect(text).toContain('不是逐条核验的结论')
    expect(text).not.toContain('不是错误')
    // 行内带分类列
    expect(w.findAll('tbody tr')[0].text()).toContain('待核语义')
  })
})

describe('FundingRate.vue formatter（V2-004）', () => {
  it('100/20 显示 20.0%；100/0 显示 0.0%；缺分母为 null', async () => {
    const FundingRate = (await import('../src/views/FundingRate.vue')).default
    const utils = await import('@vue/test-utils')
    const w = utils.mount(FundingRate)
    await new Promise(r => setTimeout(r, 50))

    const rows = w.vm.rows
    expect(rows.length).toBe(3)
    const byDept = Object.fromEntries(rows.map(r => [r.dept, r]))
    expect(byDept['数理科学部'].rate).toBeCloseTo(0.2)
    // 0 资助率与缺分母必须区分：0 与 null
    expect(byDept['化学科学部'].rate).toBe(0)
    expect(byDept['生命科学部'].rate).toBeNull()

    // 剪刀差表渲染文本：20.0% / 0.0%
    const cells = [...w.findAll('tbody td')].map(td => td.text())
    expect(cells).toContain('20.0%')
    expect(cells).toContain('0.0%')

    // 全国序列：rateFromCounts 对计数生效；分母为 0 的比率是 0.0%
    const nat = w.vm.nationalOption
    expect(nat.series[0].data).toEqual([0.2])   // general 200/1000
    expect(nat.series[2].data).toEqual([0])     // regional 0/100 → 0（不是 —）
    // tooltip formatter 对已是比率的数值正确格式化（旧代码对数值调用 rate 会返回 —）
    const fmt = nat.tooltip.formatter([{ axisValue: '2024', value: 0.2, marker: '', seriesName: '面上' }])
    expect(fmt).toContain('20.0%')
    expect(fmt).not.toContain('—')
  })
})

describe('Explorer.vue', () => {
  it('来源徽标解析 JSON', async () => {
    const w = mount(Explorer)
    await new Promise(r => setTimeout(r, 50))

    const badges = w.findAll('tbody .badge')
    expect(badges.length).toBeGreaterThanOrEqual(3) // 2 + 1 = 3 个 tag
    expect(badges[0].text()).toBe('grok')
    expect(badges[1].text()).toBe('pkg')
  })

  it('CSV 导出生成带表头的内容', async () => {
    const w = mount(Explorer)
    await new Promise(r => setTimeout(r, 50))

    // 打桩 URL.createObjectURL，捕获 blob 原始字节验证 BOM
    let capturedBytes = new Uint8Array()
    const origCreate = URL.createObjectURL
    URL.createObjectURL = (blob) => {
      blob.arrayBuffer().then(buf => { capturedBytes = new Uint8Array(buf) })
      return 'blob:fake'
    }
    const origRevoke = URL.revokeObjectURL
    URL.revokeObjectURL = () => {}

    w.vm.exportCSV()
    await new Promise(r => setTimeout(r, 100))

    URL.createObjectURL = origCreate
    URL.revokeObjectURL = origRevoke

    const text = new TextDecoder('utf-8').decode(capturedBytes)
    // BOM 三个字节 EF BB BF（Excel 识别用；Blob.text() 解码时会剥离，所以看字节）
    expect([capturedBytes[0], capturedBytes[1], capturedBytes[2]]).toEqual([0xEF, 0xBB, 0xBF])
    expect(text).toContain('批准号')
    expect(text).toContain('11500001')
    expect(text).toContain('自噬')
    // 含逗号/引号的字段被 CSV 转义（" → ""，整体加引号）
    expect(text).toContain('"[""grok"",""pkg""]"')
  })
})
