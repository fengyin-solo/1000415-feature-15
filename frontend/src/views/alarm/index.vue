<template>
  <section class="page" data-module="alarm">
    <header class="page-head">
      <div>
        <h2>报警中心管理</h2>
        <p class="page-desc">按报警编号、报警等级与触发时间段定位报警事件，待确认与超时未处置的自动置顶，统计口径与列表一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记报警事件</button>
        <button class="btn" type="button" @click="exportRows">导出报警中心清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="applyFilters">
      <label class="filter-item">
        <span>报警编号</span>
        <input v-model.trim="filters.keyword" placeholder="按报警编号检索" />
      </label>
      <label class="filter-item">
        <span>报警等级</span>
        <select v-model="filters.level">
          <option value="">全部等级</option>
          <option v-for="level in levelOptions" :key="level" :value="level">{{ level }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>触发时间起</span>
        <input v-model="filters.start" type="date" />
      </label>
      <label class="filter-item">
        <span>触发时间止</span>
        <input v-model="filters.end" type="date" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="showHighOnly">只看高等级</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">{{ emptyText }}</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条报警中心记录</span>
      <span v-if="notice" class="notice-text">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Filters = { keyword: string; level: string; start: string; end: string }
type StatsPayload = {
  total?: number
  level_distribution?: { level: string; count: number }[]
  handling?: Record<string, number>
}

const ENDPOINT = '/api/alarm'
const columns = ["报警编号", "报警类型", "报警等级", "触发点位", "触发时间", "确认人员", "处置措施", "报警状态"]
const actions = ["确认报警", "处置报警", "忽略报警"]
const levelOptions = ["高", "中", "低"]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const notice = ref('')
const stats = ref([
  { label: '结果总数', value: 0 },
  { label: '高等级', value: 0 },
  { label: '中等级', value: 0 },
  { label: '低等级', value: 0 },
  { label: '待确认', value: 0 },
  { label: '超时未处置', value: 0 },
])
const filters = ref<Filters>({ keyword: '', level: '', start: '', end: '' })
const applied = ref<Filters>({ keyword: '', level: '', start: '', end: '' })

const hasActiveFilters = computed(() => Object.values(applied.value).some(Boolean))
const emptyText = computed(() =>
  hasActiveFilters.value ? '未查询到符合条件的报警事件，请调整筛选条件后重试' : '暂无报警中心数据，可先登记报警事件',
)

function queryOf(source: Filters): Record<string, string> {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(source)) {
    if (value) {
      query[key] = value
    }
  }
  return query
}

function applyFilters() {
  errorMessage.value = ''
  notice.value = ''
  const { start, end } = filters.value
  if (start && end && end < start) {
    errorMessage.value = '触发时间段起止颠倒，请调整开始与结束时间'
    return
  }
  if (JSON.stringify(queryOf(filters.value)) === JSON.stringify(queryOf(applied.value))) {
    notice.value = '当前查询条件与上次一致，列表已是最新结果'
    return
  }
  applied.value = { ...filters.value }
  void reload()
}

function showHighOnly() {
  filters.value.level = '高'
  applyFilters()
}

function resetFilters() {
  filters.value = { keyword: '', level: '', start: '', end: '' }
  applied.value = { keyword: '', level: '', start: '', end: '' }
  notice.value = ''
  void reload()
}

function exportRows() {
  const query = new URLSearchParams(queryOf(applied.value)).toString()
  window.open(`${ENDPOINT}/export${query ? `?${query}` : ''}`, '_blank')
}

function openCreate() {
  errorMessage.value = '报警事件登记入口尚未接入审批流'
}

async function readDetail(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    if (payload && typeof payload.detail === 'string') {
      return payload.detail
    }
  } catch {
    // 响应不是 JSON 时保留兜底文案
  }
  return fallback
}

function buildStats(payload: StatsPayload) {
  const distribution = payload.level_distribution ?? []
  const handling = payload.handling ?? {}
  const levelCount = (name: string) => distribution.find((item) => item.level === name)?.count ?? 0
  return [
    { label: '结果总数', value: payload.total ?? 0 },
    { label: '高等级', value: levelCount('高') },
    { label: '中等级', value: levelCount('中') },
    { label: '低等级', value: levelCount('低') },
    { label: '待确认', value: handling['待确认'] ?? 0 },
    { label: '超时未处置', value: handling['超时未处置'] ?? 0 },
  ]
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  notice.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('报警中心动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报警中心操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(queryOf(applied.value)).toString()
  const suffix = query ? `?${query}` : ''
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}${suffix}`),
      request(`${ENDPOINT}/stats${suffix}`),
    ])
    if (!listResponse.ok) {
      throw new Error(await readDetail(listResponse, '报警事件列表读取失败'))
    }
    if (!statsResponse.ok) {
      throw new Error(await readDetail(statsResponse, '报警统计读取失败'))
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = buildStats((await statsResponse.json()) as StatsPayload)
    // 已应用的筛选条件写回地址栏，刷新页面后仍与查询前保持一致
    void router.replace({ query: queryOf(applied.value) })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报警中心数据读取失败'
  }
}

onMounted(() => {
  const { keyword, level, start, end } = route.query
  const restored = {
    keyword: typeof keyword === 'string' ? keyword : '',
    level: typeof level === 'string' ? level : '',
    start: typeof start === 'string' ? start : '',
    end: typeof end === 'string' ? end : '',
  }
  filters.value = { ...restored }
  applied.value = { ...restored }
  void reload()
})
</script>
