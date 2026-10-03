<script setup>
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import { readUrl, writeUrl, onPopState } from './modules/urlState'
import { syncScopeFromUrl, getScope, host, writeScopeCarry } from './modules/scope'
import { getHealth } from './api'
import ScopeBar from './components/ScopeBar.vue'
import Home from './views/Home.vue'
import Overview from './views/Overview.vue'
import Trends from './views/Trends.vue'
import Departments from './views/Departments.vue'
import Institutions from './views/Institutions.vue'
import Subjects from './views/Subjects.vue'
import Keywords from './views/Keywords.vue'
import Coverage from './views/Coverage.vue'
import Quality from './views/Quality.vue'
import Explorer from './views/Explorer.vue'
import NationalLedger from './views/NationalLedger.vue'
import FundingRate from './views/FundingRate.vue'
import Compare from './views/Compare.vue'

// 页面注册表（V2-009）：扁平 URL 页号 + 按四区分组的导航；
// basis/dim 是每页的数据基准与日期维度，由页派生、只读展示
const PAGES = [
  { id: 'home', zone: 'discover', label: '首页', basis: '库内样本', dim: '批准年' },
  { id: 'explorer', zone: 'explore', label: '数据检索', basis: '库内样本', dim: '批准年' },
  { id: 'compare', zone: 'explore', label: '口径对比', basis: '门户+年报聚合', dim: '批准年' },
  { id: 'overview', zone: 'analyze', label: '总览', basis: '库内样本', dim: '批准年' },
  { id: 'trends', zone: 'analyze', label: '年份趋势', basis: '库内样本', dim: '批准+结题' },
  { id: 'depts', zone: 'analyze', label: '学部分布', basis: '库内样本', dim: '批准年' },
  { id: 'insts', zone: 'analyze', label: '单位排行', basis: '库内样本', dim: '批准年' },
  { id: 'subjects', zone: 'analyze', label: '学科分布', basis: '库内样本', dim: '批准年' },
  { id: 'keywords', zone: 'analyze', label: '关键词', basis: '库内样本', dim: '批准年' },
  { id: 'coverage', zone: 'data', label: '覆盖率', basis: '库内样本 vs 官方聚合', dim: '批准年' },
  { id: 'quality', zone: 'data', label: '数据质量', basis: '库内样本', dim: '批准年' },
  { id: 'national', zone: 'data', label: '全国台账', basis: '门户聚合', dim: '批准+结题' },
  { id: 'funding', zone: 'data', label: '资助率', basis: '年报聚合', dim: '申请年' },
]

const ZONES = [
  { id: 'discover', label: '发现问题' },
  { id: 'explore', label: '探索项目' },
  { id: 'analyze', label: '对比分析' },
  { id: 'data', label: '数据与口径' },
]

const initial = readUrl()
const initialPage = PAGES.find((p) => p.id === initial.page)
const active = ref(initialPage ? initialPage.id : 'home')

const health = ref(null)

async function checkHealth() {
  try {
    health.value = await getHealth()
  } catch (e) {
    health.value = { status: 'unavailable', error: e.message }
  }
}

/** 页面切换：写 URL、同步范围状态。
 *  普通导航从 scope 状态携带三参（canonical：division/year/type，不读 URL 的 dept，
 *  V2R2-001 修复跨页丢学部）；带显式 params 的跳转（示例问题/图表点击）以参数为准。 */
function go(page, params) {
  const found = PAGES.find((p) => p.id === page)
  if (!found) return
  if (params) {
    writeUrl(page, params)
  } else {
    writeScopeCarry(page)
  }
  active.value = page
  syncScopeFromUrl()
}

host.go = go

onMounted(() => {
  if (!initialPage) writeUrl(active.value)
  // 刷新/直链进入时按 URL 重建范围（go/popstate 之外唯一来源；子组件先挂载、
  // 此处变更经 watch 传播——V2R2-001 刷新不丢学部）。
  // URL 完全无范围参数时不重建：检索页可能正从 localStorage「继续上次」恢复，
  // 重建会把它清掉（V2-009）
  const p = readUrl().params
  if (p.division || p.dept || p.year || p.type) syncScopeFromUrl()
  checkHealth()
  offPop = onPopState(({ page }) => {
    const found = PAGES.find((p) => p.id === page)
    if (found) {
      active.value = page
      syncScopeFromUrl()
    }
  })
})

let offPop = null
onBeforeUnmount(() => {
  offPop && offPop()
  host.go = null
})

watch(active, (page) => {
  if (readUrl().page !== page) writeUrl(page)
  syncScopeFromUrl()
})

const activeMeta = computed(() => PAGES.find((p) => p.id === active.value) || PAGES[0])
const sidebarCollapsed = ref(false)
</script>

<template>
  <div class="layout" :class="{ collapsed: sidebarCollapsed }">
    <aside class="sidebar">
      <div class="brand">
        <h1>国自然项目看板</h1>
        <div class="sub">NSFC 采集与分析</div>
      </div>
      <button class="collapse-btn" @click="sidebarCollapsed = !sidebarCollapsed">
        {{ sidebarCollapsed ? '»' : '« 收起' }}
      </button>
      <nav class="nav">
        <div v-for="z in ZONES" :key="z.id" class="zone">
          <div class="zone-label">{{ z.label }}</div>
          <button
            v-for="p in PAGES.filter(p => p.zone === z.id)"
            :key="p.id"
            :class="{ active: active === p.id }"
            @click="go(p.id)"
          >{{ p.label }}</button>
        </div>
      </nav>
      <div class="sub" style="margin-top: 22px;">
        <span class="badge" :class="health?.status === 'ready' ? 'ok' : 'warn'">
          <template v-if="!health">检查中…</template>
          <template v-else-if="health.status === 'ready'">API 正常</template>
          <template v-else-if="health.status === 'partial'">
            产物缺 {{ (health.missing || []).join('、') || '?' }}
          </template>
          <template v-else>API 不可用</template>
        </span>
      </div>
    </aside>
    <main class="main">
      <ScopeBar :basis="activeMeta.basis" :date-dim="activeMeta.dim" />
      <Home v-if="active === 'home'" @go="go" />
      <Overview v-else-if="active === 'overview'" />
      <Trends v-else-if="active === 'trends'" />
      <Departments v-else-if="active === 'depts'" />
      <Institutions v-else-if="active === 'insts'" />
      <Subjects v-else-if="active === 'subjects'" />
      <Keywords v-else-if="active === 'keywords'" />
      <Coverage v-else-if="active === 'coverage'" />
      <Quality v-else-if="active === 'quality'" />
      <Explorer v-else-if="active === 'explorer'" />
      <NationalLedger v-else-if="active === 'national'" />
      <FundingRate v-else-if="active === 'funding'" />
      <Compare v-else-if="active === 'compare'" />
    </main>
  </div>
</template>
