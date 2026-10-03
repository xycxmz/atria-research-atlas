<script setup>
import { computed } from 'vue'
import { getScope, setScope, clearScope, host } from '../modules/scope'

const props = defineProps({
  // 本页数据基准与日期维度：页派生，只读展示（V2-009：范围持续可见）
  basis: { type: String, default: '库内样本' },
  dateDim: { type: String, default: '批准年' },
})

const sc = getScope()

const anyApplied = computed(() => sc.division !== '' || sc.year !== '' || sc.grantType !== '')

// 本页真正生效的维度（V2R2-001）：其余维度即使设了也不作用于本页结果
const divisionLive = computed(() => host.supports.includes('division'))
const yearLive = computed(() => host.supports.includes('year'))
const typeLive = computed(() => host.supports.includes('grantType'))

const DIVISIONS = ['数理科学部', '化学科学部', '生命科学部', '地球科学部',
                   '工程与材料科学部', '信息科学部', '管理科学部', '医学科学部']

/** 带完整范围转检索页（页内不支持的维度在检索页全部生效） */
function goExplorerWithScope() {
  if (host.go) {
    host.go('explorer', {
      dept: sc.division, year: sc.year, type: sc.grantType, page: '1',
    })
  }
}

/** 应用到当前页：只调用页声明的维度；不支持的维度变更直接转检索页 */
function pickDivision(e) {
  setScope({ division: e.target.value })
  if (divisionLive.value && host.applyScope) {
    host.applyScope({ division: sc.division })
  } else {
    goExplorerWithScope()
  }
}

function pickYear(e) {
  const v = e.target.value.trim()
  if (yearLive.value && host.applyScope) {
    // 本页年份真实生效（检索页）：就地应用，submit 内部静默同步 scope
    host.applyScope({ year: v })
  } else {
    setScope({ year: v })
    goExplorerWithScope()
  }
}

function pickType(e) {
  const v = e.target.value.trim()
  if (typeLive.value && host.applyScope) {
    host.applyScope({ grantType: v })
  } else {
    setScope({ grantType: v })
    goExplorerWithScope()
  }
}

function onClear() {
  clearScope()
  if (host.applyScope) {
    // 只清本页真正生效的维度；草稿中的其余维度本就未作用于结果
    const patch = {}
    if (divisionLive.value) patch.division = ''
    if (yearLive.value) patch.year = ''
    if (typeLive.value) patch.grantType = ''
    if (Object.keys(patch).length) host.applyScope(patch)
    else goExplorerWithScope()
  } else {
    goExplorerWithScope()
  }
}
</script>

<template>
  <div class="scopebar">
    <div class="scope-group">
      <span class="scope-label">数据基准</span>
      <span class="badge ok">{{ basis }}</span>
      <span class="scope-label">日期维度</span>
      <span class="badge">{{ dateDim }}</span>
    </div>
    <div class="scope-group">
      <span class="scope-label">范围</span>
      <select :value="sc.division" @change="pickDivision" aria-label="学部">
        <option value="">全部学部</option>
        <option v-for="d in DIVISIONS" :key="d" :value="d">{{ d }}</option>
      </select>
      <input :value="sc.year" @change="pickYear" placeholder="年份" aria-label="年份"
             style="width: 80px;" inputmode="numeric">
      <input :value="sc.grantType" @change="pickType" placeholder="类别（如 面上）" aria-label="类别"
             style="width: 140px;">
      <button v-if="anyApplied" class="scope-clear" @click="onClear">清除范围</button>
    </div>
    <div v-if="anyApplied" class="scope-chips">
      <span v-if="sc.division" class="chip-scope" :class="{ 'not-applied': !divisionLive }">
        学部: {{ sc.division }}<span v-if="!divisionLive">（本页未应用）</span>
      </span>
      <span v-if="sc.year" class="chip-scope" :class="{ 'not-applied': !yearLive }">
        年: {{ sc.year }}<span v-if="!yearLive">（本页未应用）</span>
      </span>
      <span v-if="sc.grantType" class="chip-scope" :class="{ 'not-applied': !typeLive }">
        类别: {{ sc.grantType }}<span v-if="!typeLive">（本页未应用）</span>
      </span>
    </div>
    <div v-if="anyApplied && (!divisionLive || !yearLive || !typeLive)" class="scope-hint">
      标「本页未应用」的维度不作用于本页结果——改它们或点进「数据检索」后全部生效
    </div>
    <div v-else-if="!host.applyScope" class="scope-hint">
      本页不按此范围分片——改范围将带条件转到「数据检索」打开
    </div>
  </div>
</template>

<style scoped>
.scopebar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 10px 14px;
  margin-bottom: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  align-items: center;
}
.scope-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.scope-label { font-size: 11.5px; color: var(--muted); }
.scopebar select, .scopebar input {
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 5px 10px;
  font-size: 12.5px;
  outline: none;
}
.scopebar select:focus, .scopebar input:focus { border-color: var(--accent); }
.scope-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip-scope {
  font-size: 11.5px;
  background: rgba(76, 194, 255, 0.12);
  color: var(--accent);
  border: 1px solid rgba(76, 194, 255, 0.35);
  border-radius: 999px;
  padding: 2px 10px;
}
.scope-clear {
  background: none;
  border: 1px solid var(--border);
  color: var(--muted);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.scope-clear:hover { color: var(--danger); border-color: var(--danger); }
.chip-scope.not-applied {
  background: rgba(139, 152, 168, 0.1);
  color: var(--muted);
  border-color: var(--border);
}
.scope-hint { font-size: 11.5px; color: var(--muted); width: 100%; }
</style>
