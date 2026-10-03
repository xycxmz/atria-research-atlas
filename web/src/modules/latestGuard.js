/**
 * 最新请求令牌：慢 A 快 B 时丢弃 A 的回包（V2-010）。
 *
 * 用法：
 *   const guard = createLatest()
 *   async function load() {
 *     const t = guard.begin()
 *     const r = await fetchSomething()
 *     if (!guard.isLatest(t)) return   // 在途期间又发起了新请求，本回包作废
 *     result.value = r
 *   }
 *   guard.bump()   // 不等回包就作废所有在途请求（页面切走、详情关闭）
 */
export function createLatest() {
  let current = 0
  return {
    /** 开始一次请求，返回它的序号 */
    begin() {
      return ++current
    },
    /** 序号是否仍是最新（未被后续 begin/bump 超越） */
    isLatest(n) {
      return n === current
    },
    /** 作废所有在途请求，不改变下一次 begin 的起点语义 */
    bump() {
      current += 1
    },
  }
}
