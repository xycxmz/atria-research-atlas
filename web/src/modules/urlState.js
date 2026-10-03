/**
 * 轻量 hash 路由与 URL 状态（V2-010）。
 *
 * 形态：#/<page>?q=...&page=2&detail=11500001
 * 选 hash 而非 history：S4 的精选静态版不需要服务器回退配置，浏览器刷新与
 * 前进后退都能恢复页面/筛选/分页/详情抽屉。
 *
 * 写入用 pushState（产生可后退的历史步），不触发 popstate；
 * 用户点后退/前进时由监听方读 readUrl() 恢复。
 */

export function readUrl() {
  const raw = typeof location !== 'undefined' ? location.hash : ''
  const hash = raw.startsWith('#') ? raw.slice(1) : raw
  const [path, query] = hash.split('?')
  // 无 hash 直达时默认首页（四区导航的入口，W6）
  const page = (path || '').replace(/^\//, '') || 'home'
  const params = Object.fromEntries(new URLSearchParams(query || ''))
  return { page, params }
}

/** 写入 URL（pushState）。空值参数自动丢弃；hash 未变时不产生历史步。 */
export function writeUrl(page, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== '' && v != null && v !== undefined)
  ).toString()
  const url = '#/' + page + (qs ? '?' + qs : '')
  if (location.hash !== url) {
    history.pushState(null, '', url)
  }
}

/** 订阅浏览器前进/后退。返回取消订阅函数。 */
export function onPopState(fn) {
  const handler = () => fn(readUrl())
  window.addEventListener('popstate', handler)
  return () => window.removeEventListener('popstate', handler)
}
