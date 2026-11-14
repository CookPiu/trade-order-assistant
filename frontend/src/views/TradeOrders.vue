<script setup lang="ts">
/** 模拟商贸系统订单列表（FR-035、FR-043）：销售/采购页签、筛选、详情抽屉；经办人右下角挂悬浮窗。 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { errorMessage, http } from '@/api/http'
import { fmtTime, money, ORDER_STATUS_LABEL, type OrderDetail, type OrderRow, type OrderType } from '@/api/types'
import { onOrderCreated } from '@/bus/orderBus'
import FloatingWidget from '@/components/FloatingWidget.vue'
import OrderDrawer from '@/components/OrderDrawer.vue'
import { useDraftStore } from '@/stores/draft'
import { useSessionStore } from '@/stores/session'

const PENDING = 'submitted,pending_special'
const ALL_STATUS_OPTIONS = [
  { label: '待审核（已提交、待特批）', value: PENDING },
  { label: '已提交', value: 'submitted' },
  { label: '待特批', value: 'pending_special' },
  { label: '已审核', value: 'approved' },
  { label: '退回', value: 'returned' },
  { label: '驳回', value: 'rejected' },
]
const STATUS_TYPE: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  submitted: 'primary',
  pending_special: 'warning',
  approved: 'success',
  returned: 'warning',
  rejected: 'danger',
}

const session = useSessionStore()
const draftStore = useDraftStore()
const router = useRouter()
const isOperator = computed(() => session.user?.role === 'operator')
const isApprover = computed(() => session.user?.role === 'approver')
// 审批人只看本部门待审订单
const STATUS_OPTIONS = computed(() =>
  isApprover.value ? ALL_STATUS_OPTIONS.filter((o) => ['submitted', 'pending_special', PENDING].includes(o.value)) : ALL_STATUS_OPTIONS,
)
const acting = ref(false)
const drawer = ref<InstanceType<typeof OrderDrawer> | null>(null)

const tab = ref<OrderType>('sales')
const filters = reactive({
  status: isApprover.value ? PENDING : '',
  contract_no: '',
  range: null as [string, string] | null,
})
const page = ref(1)
const pageSize = 20
const total = ref(0)
const rows = ref<OrderRow[]>([])
const loading = ref(false)
const highlight = ref('')
const drawerOpen = ref(false)
const currentId = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<{ total: number; items: OrderRow[] }>('/orders', {
      params: {
        order_type: tab.value,
        status: filters.status || undefined,
        contract_no: filters.contract_no.trim() || undefined,
        date_from: filters.range?.[0],
        date_to: filters.range?.[1],
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

function resetFilters() {
  filters.status = isApprover.value ? PENDING : ''
  filters.contract_no = ''
  filters.range = null
  search()
}

function switchTab() {
  page.value = 1
  load()
}

function open(row: OrderRow) {
  currentId.value = row.id
  drawerOpen.value = true
}

type ReviewAction = 'approve' | 'return' | 'reject'
const REVIEW: Record<ReviewAction, { title: string; required: boolean; button: string }> = {
  approve: { title: '审核通过', required: false, button: '通过' },
  return: { title: '退回修改', required: true, button: '退回' },
  reject: { title: '驳回', required: true, button: '驳回' },
}

async function review(order: OrderDetail, action: ReviewAction) {
  const cfg = REVIEW[action]
  let comment = ''
  try {
    const { value } = await ElMessageBox.prompt(
      action === 'reject' ? '驳回后订单不能再修改或提交，并释放占用的合同额度。' : `订单 ${order.order_no}`,
      cfg.title,
      {
        inputType: 'textarea',
        inputPlaceholder: cfg.required ? '必填：说明原因' : '选填：审批意见',
        inputValidator: (v: string) => !cfg.required || !!v?.trim() || '请填写审批意见',
        confirmButtonText: cfg.button,
        cancelButtonText: '取消',
        confirmButtonClass: action === 'approve' ? '' : 'el-button--danger',
      },
    )
    comment = value ?? ''
  } catch {
    return
  }
  acting.value = true
  try {
    await http.post(`/orders/${order.id}/${action}`, { comment })
    ElMessage.success(`${cfg.title}：${order.order_no}`)
    await drawer.value?.reload()
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    acting.value = false
  }
}

async function editReturned(order: OrderDetail) {
  acting.value = true
  try {
    await draftStore.loadReturned(order.id)
    drawerOpen.value = false
    router.push({ name: 'workbench' })
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    acting.value = false
  }
}

function rowClass({ row }: { row: OrderRow }) {
  return row.order_no === highlight.value ? 'row-new' : ''
}

let off: (() => void) | undefined
onMounted(() => {
  load()
  // 悬浮窗或工作台提单成功后自动刷新并标出新订单（FR-043）
  off = onOrderCreated((p) => {
    highlight.value = p.order_no
    if (tab.value !== p.order_type) tab.value = p.order_type
    page.value = 1
    load()
  })
})
onBeforeUnmount(() => off?.())
</script>

<template>
  <div class="orders-page">
    <section class="app-panel">
      <header class="head">
        <h2>商贸订单</h2>
        <span class="sub">模拟底层商贸系统，按部门显示订单</span>
      </header>
      <el-tabs v-model="tab" class="tabs" @tab-change="switchTab">
        <el-tab-pane label="销售订单" name="sales" />
        <el-tab-pane label="采购订单" name="purchase" />
      </el-tabs>

      <div class="filters">
        <el-select v-model="filters.status" class="f-status" placeholder="全部状态" @change="search">
          <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-input v-model="filters.contract_no" placeholder="合同号" clearable class="f-contract" @keyup.enter="search" @clear="search" />
        <el-date-picker
          v-model="filters.range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="创建开始日期"
          end-placeholder="结束日期"
          class="f-range"
          @change="search"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>

      <el-table
        v-loading="loading"
        :data="rows"
        :row-class-name="rowClass"
        size="small"
        class="table"
        empty-text="没有符合条件的订单"
        @row-click="open"
      >
        <el-table-column label="单据编号" min-width="190">
          <template #default="{ row }">
            <span class="no">{{ row.order_no }}</span>
          </template>
        </el-table-column>
        <el-table-column label="合同号" prop="contract_no" width="120" />
        <el-table-column label="签约单位" prop="party_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="工程项目" prop="project_name" min-width="120" show-overflow-tooltip />
        <el-table-column label="总金额" width="130" align="right">
          <template #default="{ row }">{{ money(row.total_amount) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="86">
          <template #default="{ row }">
            <el-tag :type="STATUS_TYPE[row.status] ?? 'info'" size="small">{{ ORDER_STATUS_LABEL[row.status] ?? row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="超额" width="64" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.over_quota" type="danger" effect="plain" size="small">超额</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="经办人" prop="operator_name" width="80" />
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.submitted_at) }}</template>
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
      <div v-else class="count">共 {{ total }} 笔</div>
    </section>

    <OrderDrawer ref="drawer" v-model="drawerOpen" :order-id="currentId">
      <template #footer="{ order }">
        <div class="actions">
          <template v-if="isApprover && ['submitted', 'pending_special'].includes(order.status)">
            <span v-if="order.over_quota" class="over-tip">超额订单，通过即为特批</span>
            <el-button type="danger" plain :loading="acting" @click="review(order, 'reject')">驳回</el-button>
            <el-button type="warning" plain :loading="acting" @click="review(order, 'return')">退回修改</el-button>
            <el-button type="primary" :loading="acting" @click="review(order, 'approve')">审核通过</el-button>
          </template>
          <template v-else-if="isOperator && order.status === 'returned' && order.operator_id === session.user?.id">
            <span class="over-tip">订单已退回，修改后沿用原单号重新提交</span>
            <el-button type="primary" :loading="acting" @click="editReturned(order)">修改</el-button>
          </template>
          <span v-else class="muted-tip">{{ order.status === 'rejected' ? '订单已驳回，不能再修改或提交' : '当前状态无可执行的操作' }}</span>
        </div>
      </template>
    </OrderDrawer>
    <FloatingWidget v-if="isOperator" />
  </div>
</template>

<style scoped lang="scss">
.orders-page {
  padding: 12px;
  box-sizing: border-box;
  min-width: 0;
}
.app-panel {
  padding: 12px 14px 14px;
  min-width: 0;
}
.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  h2 {
    font-size: 15px;
    margin: 0;
  }
  .sub {
    font-size: 12px;
    color: var(--app-text-secondary);
  }
}
.tabs {
  margin-top: 4px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
  .f-status {
    width: 200px;
  }
  .f-contract {
    width: 160px;
  }
  // 日期选择器根节点经 tooltip 渲染，不带 scoped 属性
  :deep(.f-range) {
    flex: none;
    width: 280px;
  }
}
.table {
  width: 100%;
  :deep(.el-table__row) {
    cursor: pointer;
  }
  :deep(.row-new) {
    --el-table-tr-bg-color: var(--el-color-success-light-9);
  }
}
.no {
  color: var(--el-color-primary);
  font-weight: 600;
}
.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
.over-tip {
  margin-right: auto;
  font-size: 12px;
  color: var(--app-over);
}
.muted-tip {
  font-size: 12px;
  color: var(--app-text-secondary);
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
