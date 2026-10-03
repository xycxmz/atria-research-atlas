/**
 * 共享分析范围（V2-009/W4）：让「当前在看什么范围」持续可见、跨页保持。
 *
 * 三个可交互维度：学部 / 资助类别 / 年份。数据基准（库内样本/门户聚合/年报聚合）
 * 与日期维度由当前页派生，只展示不可切换——切换它们等于换数据源。
 *
 * scope 写入当前页 URL（division/year/type 三个参数），刷新与后退可恢复；
 * 每页通过 registerApplyScope 声明自己如何应用范围（检索页重建查询，
 * 学科/关键词页切学部筛选）；不支持的页面在范围变更时转至检索页打开。
 */
import { reactive, readonly } from 'vue'
import { readUrl, writeUrl } from './urlState'

const scope = reactive({ division: '', grantType: '', year: '' })

export const SCOPE_KEYS = ['division', 'grantType', 'year']

export function getScope() {
  return readonly(scope)
}

function writeScopeToUrl() {
  const { page, params } = readUrl()
  writeUrl(page, { ...params, division: scope.division, type: scope.grantType, year: scope.year })
}

/** 修改范围。silent=true 只更新状态不回写 URL（页面自身已写完 URL 时用）。 */
export function setScope(patch, opts = {}) {
  let changed = false
  for (const k of SCOPE_KEYS) {
    if (k in patch && scope[k] !== (patch[k] ?? '')) {
      scope[k] = patch[k] ?? ''
      changed = true
    }
  }
  if (changed && !opts.silent) writeScopeToUrl()
  return changed
}

export function clearScope() {
  setScope({ division: '', grantType: '', year: '' })
}

/** 普通导航时把当前 scope 三参写到目标页 URL（V2R2-001：从 scope 状态携带，
 *  不读源页 URL——explorer 的 dept 与规范 division 不同名，从 URL 携会丢学部） */
export function writeScopeCarry(page) {
  const carried = {}
  for (const k of SCOPE_KEYS) {
    if (scope[k]) carried[k] = scope[k]
  }
  // URL 里的 type 参数名与规范名一致（grantType → type）
  if (scope.grantType) {
    carried.type = scope.grantType
    delete carried.grantType
  }
  writeUrl(page, carried)
}

/** 从 URL 参数重建范围（页面切换/直链恢复/刷新时）。
 *  学部接受 division（canonical）与 dept（检索页命名）两种写法——
 *  共享深链与旧链接可能只有 dept（V2R2-001：刷新不能丢学部）。 */
export function syncScopeFromUrl() {
  const { params } = readUrl()
  setScope({
    division: params.division || params.dept || '',
    grantType: params.type || '',
    year: params.year || '',
  }, { silent: true })
}

// 页面注册自己的范围应用函数；supports 声明本页真正支持哪些维度（V2R2-001：
// 只有所声明维度才在页内应用，其余维度变更带条件转检索页，避免 scope 条件
// 展示了却不生效）
import { reactive as _reactive } from 'vue'
export const host = _reactive({ applyScope: null, go: null, supports: [] })

export function registerApplyScope(fn, supports = ['division']) {
  host.applyScope = fn
  host.supports = supports
}

export function unregisterApplyScope() {
  host.applyScope = null
  host.supports = []
}
