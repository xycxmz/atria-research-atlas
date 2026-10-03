<script setup>
import { ref, onMounted, computed } from 'vue'
import { getConflicts } from '../api'
import DataState from '../components/DataState.vue'
import ProjectDetail from './ProjectDetail.vue'

const data = ref(null)
const error = ref(null)
const field = ref('')
const cls = ref('')
const q = ref('')
const page = ref(1)
const detailNo = ref(null)

const fmt = (n) => Number(n || 0).toLocaleString('zh-CN')

async function load() {
  error.value = null
  try {
    data.value = await getConflicts({ field: field.value, cls: cls.value, q: q.value, page: page.value, size: 20 })
  } catch (e) {
    error.value = e
  }
}

onMounted(load)

function submit() {
  page.value = 1
  load()
}

function pickField(f) {
  field.value = field.value === f ? '' : f
  page.value = 1
  load()
}

function pickClass(c) {
  cls.value = cls.value === c ? '' : c
  page.value = 1
  load()
}

function openDetail(no) {
  detailNo.value = no
}

function closeDetail() {
  detailNo.value = null
}

const totalPages = computed(() => (data.value ? Math.ceil(data.value.total / data.value.size) : 0))
</script>

<template>
  <div>
    <div class="page-header">
      <h2>数据质量</h2>
      <span class="note">多来源字段冲突 · 全部留档不丢弃 · 逐条分类（V2-007）</span>
    </div>
    <DataState :loading="!data && !error" :error="error" @retry="load">
      <template v-if="data">
      <div class="hint" style="margin-bottom: 12px;">
        合并时同一批准号同一字段在不同来源有不同非空值，就记一条冲突。
        选中值按来源优先级裁决（基金委门户 &gt; LetPub &gt; 第三方交付包），落选值全部保留在 alternatives 里。
        <strong>分类只是线索与抽查假设，不是逐条核验的结论</strong>——未核裁决一律标「待核」，
        需要时打开详情比对来源。
      </div>
      <div class="filters" style="margin-bottom: 16px;">
        <input v-model="q" placeholder="批准号 / 值 关键词" style="width: 220px" @keyup.enter="submit" />
        <button class="pager-btn" @click="submit">筛选</button>
        <button v-if="field || cls || q" class="pager-btn" @click="field = ''; cls = ''; q = ''; submit()">清除筛选</button>
      </div>
      <div class="field-chips">
        <button
          v-for="f in data.fields"
          :key="f.field"
          class="chip"
          :class="{ active: field === f.field }"
          @click="pickField(f.field)"
        >{{ f.field }} · {{ fmt(f.count) }}</button>
      </div>
      <div class="field-chips" style="margin-top: 8px;">
        <button
          v-for="c in (data.classifications || [])"
          :key="c.classification"
          class="chip cls"
          :class="{ active: cls === c.classification }"
          @click="pickClass(c.classification)"
        >{{ c.classification }} · {{ fmt(c.count) }}</button>
      </div>
      <div class="chart">
        <h3>共 {{ fmt(data.total) }} 条（第 {{ data.page }} / {{ totalPages }} 页）</h3>
        <table>
          <thead>
            <tr>
              <th>批准号</th><th>字段</th><th>分类</th><th>选中值（来源）</th><th>落选值（来源）</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in data.rows" :key="i">
              <td style="font-family: monospace; font-size: 12px;">
                <a href="javascript:void(0)" @click="openDetail(r.grant_no)">{{ r.grant_no }}</a>
              </td>
              <td><span class="badge">{{ r.field }}</span></td>
              <td style="font-size: 12px; color: var(--muted);">{{ r.classification || '待核' }}</td>
              <td style="max-width: 240px;">{{ r.selected }} <span style="color: var(--muted); font-size: 11px;">({{ r.selected_from }})</span></td>
              <td style="max-width: 240px; color: var(--warn); font-size: 12px;">
                <span v-for="(alt, j) in (typeof r.alternatives === 'string' ? JSON.parse(r.alternatives || '[]') : r.alternatives)" :key="j">
                  {{ alt.value }} ({{ alt.from }})<br/>
                </span>
              </td>
              <td><button class="pager-btn" @click="openDetail(r.grant_no)">详情</button></td>
            </tr>
          </tbody>
        </table>
        <div class="pager">
          <button :disabled="page <= 1" @click="page--; load()">上一页</button>
          <span>第 {{ page }} 页 / 共 {{ totalPages }} 页</span>
          <button :disabled="page >= totalPages" @click="page++; load()">下一页</button>
        </div>
      </div>
      </template>
    </DataState>
    <ProjectDetail v-if="detailNo" :grant-no="detailNo" @close="closeDetail" />
  </div>
</template>

<style scoped>
.field-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chip {
  border: 1px solid var(--border);
  background: var(--panel-2);
  color: var(--text);
  border-radius: 999px;
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
}
.chip:hover { border-color: var(--accent); }
.chip.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.pager-btn {
  background: var(--panel-2);
  border: 1px solid var(--border);
  color: var(--accent);
  border-radius: 8px;
  padding: 7px 18px;
  cursor: pointer;
  font-size: 13px;
}
.pager-btn:hover { border-color: var(--accent); }
</style>
