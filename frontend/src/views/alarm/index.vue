<template>
  <section class="page" data-module="alarm">
    <header class="page-head">
      <div>
        <h2>报警中心管理</h2>
        <p class="page-desc">按报警编号、报警等级与触发时间段定位；待确认与超时未处置自动置顶，可只看高等级。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记报警事件</button>
        <button class="btn" type="button" @click="exportRows">导出报警中心清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">平均处置时效</span>
        <strong class="stat-value">{{ avgDisposeText }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">待确认报警</span>
        <strong class="stat-value">{{ statsData.pending ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">超时未处置（&gt;{{ statsData.slaHours ?? 24 }}h）</span>
        <strong class="stat-value" :class="{ 'stat-alert': (statsData.overtime ?? 0) > 0 }">{{ statsData.overtime ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">高等级报警</span>
        <strong class="stat-value" :class="{ 'stat-alert': (statsData.highLevel ?? 0) > 0 }">{{ statsData.highLevel ?? 0 }}</strong>
      </article>
    </div>

    <article class="level-panel">
      <div class="level-panel-head">
        <span class="level-panel-title">等级分布</span>
        <span class="level-panel-sub">口径与列表一致，随当前筛选条件联动</span>
      </div>
      <div class="level-bars">
        <div v-for="item in statsData.levelDistribution ?? []" :key="item.level" class="level-bar">
          <div class="level-bar-meta">
            <span :class="['level-tag', `level-${item.level}`]">{{ item.level }}等级</span>
            <strong>{{ item.count }}</strong>
          </div>
          <div class="level-bar-track">
            <span
              :class="['level-bar-fill', `fill-${item.level}`]"
              :style="{ width: barWidth(item.count) }"
            ></span>
          </div>
        </div>
      </div>
    </article>

    <form class="filter-bar" @submit.prevent="search()">
      <label class="filter-item">
        <span>报警编号</span>
        <input v-model.trim="filters.keyword" placeholder="按报警编号检索，如 ALAR-0001" />
      </label>
      <label class="filter-item">
        <span>报警等级</span>
        <select v-model="filters.level">
          <option value="">全部等级</option>
          <option value="高">高</option>
          <option value="中">中</option>
          <option value="低">低</option>
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
      <button class="btn ghost" type="button" @click="onlyHigh">只看高等级</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="infoMessage" class="notice info-text">{{ infoMessage }}</div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :class="{
            'row-pinned': row['待确认'] || row['超时未处置'],
            'row-overtime': row['超时未处置'],
            'row-high': String(row['报警等级']) === '高',
          }"
        >
          <td v-for="column in columns" :key="column">
            <template v-if="column === '报警等级'">
              <span :class="['level-tag', `level-${row[column]}`]">{{ row[column] ?? '—' }}</span>
            </template>
            <template v-else-if="column === '报警状态'">
              <span v-if="row['待确认']" class="pin-badge pin-pending">待确认·置顶</span>
              <span v-else-if="row['超时未处置']" class="pin-badge pin-overtime">超时·置顶</span>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </template>
            <template v-else-if="column === '处置时效'">
              <span :class="{ 'timeliness-overtime': row['超时未处置'] }">{{ row[column] ?? '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
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
        <tr v-if="!loading && !rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            当前条件下未查询到报警事件，可调整编号、等级或触发时间段后重试
          </td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条报警记录（待确认、超时未处置已置顶）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

interface LevelBucket {
  level: string
  count: number
}

interface AlarmStats {
  total: number
  highLevel: number
  pending: number
  overtime: number
  slaHours: number
  avgDisposeHours: number | null
  handledCount: number
  levelDistribution: LevelBucket[]
}

interface Filters {
  keyword: string
  level: string
  start: string
  end: string
}

const ENDPOINT = '/api/alarm'
const columns = ["报警编号", "报警类型", "报警等级", "触发点位", "触发时间", "确认人员", "处置措施", "报警状态", "处置时效"]
const actions = ["确认报警", "处置报警", "忽略报警"]

const route = useRoute()
const router = useRouter()

const rows = ref<Row[]>([])
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const infoMessage = ref('')

const emptyStats = (): AlarmStats => ({
  total: 0,
  highLevel: 0,
  pending: 0,
  overtime: 0,
  slaHours: 24,
  avgDisposeHours: null,
  handledCount: 0,
  levelDistribution: [
    { level: '高', count: 0 },
    { level: '中', count: 0 },
    { level: '低', count: 0 },
  ],
})
const statsData = ref<AlarmStats>(emptyStats())

// 刷新后与查询前保持一致：筛选条件以 query 形式持久化在地址栏。
function readFilters(): Filters {
  const pick = (key: string) => String(route.query[key] ?? '').trim()
  return {
    keyword: pick('keyword'),
    level: pick('level'),
    start: pick('start'),
    end: pick('end'),
  }
}

const filters = ref<Filters>(readFilters())

// 已生效的查询串：用于识别“重复查询”，也用于动作后按相同条件静默刷新。
const appliedQuery = ref<string>(buildQuery(filters.value))

function buildQuery(source: Filters): string {
  const params = new URLSearchParams()
  if (source.keyword) params.set('keyword', source.keyword)
  if (source.level) params.set('level', source.level)
  if (source.start) params.set('start', source.start)
  if (source.end) params.set('end', source.end)
  return params.toString()
}

function syncUrl(query: string) {
  void router.replace({ path: route.path, query: query ? Object.fromEntries(new URLSearchParams(query)) : {} })
}

function isValidDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false
  }
  const [y, m, d] = value.split('-').map(Number)
  const date = new Date(value + 'T00:00:00')
  return date.getFullYear() === y && date.getMonth() + 1 === m && date.getDate() === d
}

function validateFilters(): string {
  const { start, end } = filters.value
  if (start && !isValidDate(start)) {
    return '触发时间起格式非法，请选择有效日期（YYYY-MM-DD）'
  }
  if (end && !isValidDate(end)) {
    return '触发时间止格式非法，请选择有效日期（YYYY-MM-DD）'
  }
  if (start && end && start > end) {
    return '触发时间段非法：开始时间不能晚于结束时间'
  }
  return ''
}

async function fetchListAndStats(query: string) {
  loading.value = true
  try {
    const suffix = query ? `?${query}` : ''
    const [listRes, statsRes] = await Promise.all([
      request(`${ENDPOINT}${suffix}`),
      request(`${ENDPOINT}/stats${suffix}`),
    ])
    // 任一接口失败都把后端可读的校验/错误说明透传给页脚。
    if (!listRes.ok) {
      throw new Error(await readDetail(listRes, '报警事件列表读取失败'))
    }
    if (!statsRes.ok) {
      throw new Error(await readDetail(statsRes, '报警统计读取失败'))
    }
    const payload = await listRes.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    statsData.value = (await statsRes.json()) as AlarmStats
    if (!rows.value.length) {
      infoMessage.value = '查询无结果：当前编号/等级/触发时间段下没有匹配的报警事件'
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报警中心列表读取失败'
  } finally {
    loading.value = false
  }
}

async function readDetail(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json()
    if (data && typeof data.detail === 'string' && data.detail.trim()) {
      return data.detail
    }
  } catch {
    // 非 JSON 错误体时使用兜底文案
  }
  return fallback
}

// 主动查询：校验时间段、拦截重复查询，再写入 URL 并请求。
async function search(force = false) {
  errorMessage.value = ''
  infoMessage.value = ''
  const invalid = validateFilters()
  if (invalid) {
    errorMessage.value = invalid
    return
  }
  const query = buildQuery(filters.value)
  if (!force && query === appliedQuery.value) {
    infoMessage.value = '与上次查询条件完全相同，已为你保留当前结果，无需重复查询'
    return
  }
  appliedQuery.value = query
  syncUrl(query)
  await fetchListAndStats(query)
}

// 动作后静默刷新：沿用已生效条件，排序与筛选不丢，也不触发“重复查询”提示。
async function reload() {
  errorMessage.value = ''
  await fetchListAndStats(appliedQuery.value)
}

function resetFilters() {
  filters.value = { keyword: '', level: '', start: '', end: '' }
  void search(true)
}

function onlyHigh() {
  filters.value = { ...filters.value, level: '高' }
  void search()
}

function exportRows() {
  window.open(`${ENDPOINT}/export${appliedQuery.value ? `?${appliedQuery.value}` : ''}`, '_blank')
}

function openCreate() {
  errorMessage.value = '报警事件登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error(await readDetail(response, '报警中心动作未生效，请稍后重试'))
    }
    const result = await response.json()
    if (result && result.ok === false) {
      throw new Error(result.message || '报警中心动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报警中心操作失败'
  }
}

const maxLevelCount = () =>
  Math.max(1, ...(statsData.value.levelDistribution ?? []).map((item) => item.count))

function barWidth(count: number): string {
  return `${Math.round((count / maxLevelCount()) * 100)}%`
}

const avgDisposeText = () => {
  const value = statsData.value.avgDisposeHours
  if (value === null || value === undefined) {
    return statsData.value.handledCount > 0 ? '—' : '暂无已处置'
  }
  return `${value} 小时`
}

onMounted(() => {
  // 从地址栏恢复条件后直接请求；首次加载不弹“重复查询”。
  void fetchListAndStats(appliedQuery.value)
})
</script>

<style scoped>
.stat-alert { color: #b42318; }
.notice {
  background: #fff;
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 10px;
}
.info-text { color: var(--muted); }

.level-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.level-panel-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.level-panel-title { font-size: 13px; font-weight: 600; }
.level-panel-sub { font-size: 12px; color: var(--muted); }
.level-bars { display: flex; gap: 18px; flex-wrap: wrap; }
.level-bar { flex: 1; min-width: 150px; }
.level-bar-meta { display: flex; justify-content: space-between; align-items: center; font-size: 12px; margin-bottom: 4px; }
.level-bar-track { height: 8px; background: #eef1f5; border-radius: 999px; overflow: hidden; }
.level-bar-fill { display: block; height: 100%; border-radius: 999px; }
.fill-高 { background: #d92d20; }
.fill-中 { background: #f79009; }
.fill-低 { background: #12b76a; }

.level-tag {
  display: inline-block;
  min-width: 22px;
  text-align: center;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 12px;
  line-height: 18px;
}
.level-高 { background: #fee4e2; color: #b42318; }
.level-中 { background: #fef0c7; color: #b54708; }
.level-低 { background: #d1fadf; color: #027a48; }

.row-pinned { background: #fffbf5; }
.row-overtime { background: #fef3f2; }
.row-high td:first-child { border-left: 3px solid #d92d20; }

.pin-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 12px;
  white-space: nowrap;
}
.pin-pending { background: #fef0c7; color: #b54708; }
.pin-overtime { background: #fee4e2; color: #b42318; }
.timeliness-overtime { color: #b42318; font-weight: 600; }
</style>
