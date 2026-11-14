<script setup lang="ts">
/** 审计日志（FR-052）：按操作人、动作、时间和单号筛选，展开行查看原始输入和变更明细。 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/api/http'
import { AUDIT_LABEL, fmtTime } from '@/api/types'

interface AuditRow {
  id: number
  created_at: string
  username: string
  display_name: string
  action: string
  order_no: string
  input_text: string
  input_hash: string
  detail: Record<string, unknown>
}

const ROLE_LABEL: Record<string, string> = { operator: '经办人', approver: '审批人', admin: '管理员' }
const ENTITY_LABEL: Record<string, string> = { contract: '合同', material: '物料', alias: '别名' }

const users = ref<{ username: string; display_name: string; role: string }[]>([])
const actions = ref<string[]>([])
const filters = reactive({
  username: '',
  actions: [] as string[],
  range: null as [string, string] | null,
  order_no: '',
})
const rows = ref<AuditRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<{ total: number; items: AuditRow[] }>('/audit', {
      params: {
        username: filters.username || undefined,
        action: filters.actions.join(',') || undefined,
        date_from: filters.range?.[0],
        date_to: filters.range?.[1],
        order_no: filters.order_no.trim() || undefined,
        page: page.value,
        page_size: pageSize,
      },
    })
    rows.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function reset() {
  Object.assign(filters, { username: '', actions: [], range: null, order_no: '' })
  search()
}

/** 表格中的一行摘要：主数据和参数显示改了什么，其他动作显示原始输入或审批意见 */
function summary(r: AuditRow): string {
  const d = r.detail ?? {}
  if (r.action === 'master_update') {
    const op = d.op === 'create' ? '新增' : '修改'
    const after = d.after as Record<string, unknown> | undefined
    const target = d.entity === 'alias' && after?.material_code ? ` → ${after.material_code}` : ''
    return `${op}${ENTITY_LABEL[String(d.entity)] ?? ''} ${d.key ?? ''}${target}`
  }
  if (r.action === 'param_update') return `${d.key}：${JSON.stringify(d.before)} → ${JSON.stringify(d.after)}`
  if (d.comment) return `意见：${d.comment}`
  if (r.input_text) return r.input_text
  if (d.file_name) return String(d.file_name)
  return ''
}

onMounted(async () => {
  try {
    const { data } = await http.get('/audit/options')
    users.value = data.users
    actions.value = data.actions
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  load()
})
</script>

<template>
  <div>
    <div class="filters">
      <el-select v-model="filters.username" placeholder="全部操作人" clearable filterable class="f-user" @change="search">
        <el-option
          v-for="u in users"
          :key="u.username"
          :label="`${u.display_name}（${u.username}，${ROLE_LABEL[u.role] ?? u.role}）`"
          :value="u.username"
        />
      </el-select>
      <el-select
        v-model="filters.actions"
        placeholder="全部动作"
        multiple
        collapse-tags
        collapse-tags-tooltip
        clearable
        class="f-action"
        @change="search"
      >
        <el-option v-for="a in actions" :key="a" :label="AUDIT_LABEL[a] ?? a" :value="a" />
      </el-select>
      <el-date-picker
        v-model="filters.range"
        type="daterange"
        value-format="YYYY-MM-DD"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        class="f-range"
        @change="search"
      />
      <el-input v-model="filters.order_no" placeholder="单据编号" clearable class="f-no" @keyup.enter="search" @clear="search" />
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" size="small" empty-text="没有符合条件的审计记录">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand">
            <div v-if="row.input_text"><b>原始输入</b><pre>{{ row.input_text }}</pre></div>
            <div v-if="row.input_hash"><b>文件哈希</b> <code>{{ row.input_hash }}</code></div>
            <div v-if="Object.keys(row.detail).length"><b>明细</b><pre>{{ JSON.stringify(row.detail, null, 2) }}</pre></div>
            <div v-if="!row.input_text && !row.input_hash && !Object.keys(row.detail).length" class="muted">没有更多内容</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作人" width="130">
        <template #default="{ row }">{{ row.display_name || row.username }} <span class="muted">{{ row.username }}</span></template>
      </el-table-column>
      <el-table-column label="动作" width="120">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ AUDIT_LABEL[row.action] ?? row.action }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="单据编号" prop="order_no" width="200" />
      <el-table-column label="内容" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ summary(row) }}</template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      class="pager"
      @current-change="load"
    />
    <div v-else class="count">共 {{ total }} 条</div>
  </div>
</template>

<style scoped lang="scss">
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
  .f-user {
    width: 220px;
  }
  .f-action {
    width: 220px;
  }
  .f-no {
    width: 180px;
  }
  :deep(.f-range) {
    flex: none;
    width: 260px;
  }
}
.expand {
  padding: 4px 16px 4px 48px;
  font-size: 12px;
  display: grid;
  gap: 6px;
  pre {
    margin: 4px 0 0;
    padding: 6px 8px;
    background: #f5f7fa;
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 260px;
    overflow: auto;
  }
  code {
    word-break: break-all;
  }
}
.muted {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.pager,
.count {
  margin-top: 10px;
  justify-content: flex-end;
}
.count {
  text-align: right;
  font-size: 12px;
  color: var(--app-text-secondary);
}
</style>
