<script setup lang="ts">
/** 订单详情抽屉（FR-035）：订单主档、物资明细、合同履约配额看板、审批意见与审计流水。 */
import { computed, ref, watch } from 'vue'
import { errorMessage, http } from '@/api/http'
import {
  AUDIT_LABEL,
  fmtTime,
  money,
  ORDER_STATUS_LABEL,
  ORDER_TYPE_LABEL,
  qty,
  type OrderDetail,
} from '@/api/types'
import QuotaCards from '@/components/QuotaCards.vue'

const props = defineProps<{ orderId: number | null }>()
const visible = defineModel<boolean>({ required: true })

const order = ref<OrderDetail | null>(null)
const loading = ref(false)
const error = ref('')

const STATUS_TYPE: Record<string, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  submitted: 'primary',
  pending_special: 'warning',
  approved: 'success',
  returned: 'warning',
  rejected: 'danger',
}

async function load() {
  if (!props.orderId) return
  loading.value = true
  error.value = ''
  try {
    const { data } = await http.get<OrderDetail>(`/orders/${props.orderId}`)
    order.value = data
  } catch (e) {
    error.value = errorMessage(e)
    order.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.orderId, visible.value] as const,
  ([id, v]) => {
    if (v && id) load()
  },
  { immediate: true },
)

const size = computed(() => (window.innerWidth < 760 ? '100%' : '720px'))

defineExpose({ reload: load, order })
</script>

<template>
  <el-drawer v-model="visible" :size="size" :with-header="false" class="order-drawer">
    <div v-loading="loading" class="wrap">
      <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
      <template v-if="order">
        <header class="head">
          <div class="no">{{ order.order_no }}</div>
          <el-tag :type="STATUS_TYPE[order.status] ?? 'info'" effect="dark" size="small">
            {{ ORDER_STATUS_LABEL[order.status] ?? order.status }}
          </el-tag>
          <el-tag v-if="order.over_quota" type="danger" effect="plain" size="small">超额</el-tag>
          <span class="type">{{ ORDER_TYPE_LABEL[order.order_type] }}</span>
          <el-button class="close" link @click="visible = false">关闭</el-button>
        </header>

        <div class="body">
          <section>
            <h3>订单主档</h3>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="合同编号">{{ order.contract_no }}</el-descriptions-item>
              <el-descriptions-item label="签约单位">{{ order.party_name }}</el-descriptions-item>
              <el-descriptions-item label="工程项目">{{ order.project_name }}</el-descriptions-item>
              <el-descriptions-item label="交期">{{ order.delivery_date }}</el-descriptions-item>
              <el-descriptions-item label="收货地址" :span="2">{{ order.address }}</el-descriptions-item>
              <el-descriptions-item label="联系人">{{ order.contact || '—' }}</el-descriptions-item>
              <el-descriptions-item label="经办人">{{ order.operator_name }} / {{ order.dept_name }}</el-descriptions-item>
              <el-descriptions-item label="业务名称">{{ order.biz_name }}</el-descriptions-item>
              <el-descriptions-item label="采购模式 / 标签">{{ order.purchase_mode }} / {{ order.biz_tag }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ fmtTime(order.submitted_at) }}</el-descriptions-item>
              <el-descriptions-item label="总金额">{{ money(order.total_amount) }} 元</el-descriptions-item>
              <el-descriptions-item label="备注" :span="2">{{ order.remark || '—' }}</el-descriptions-item>
            </el-descriptions>
          </section>

          <section>
            <h3>物资明细</h3>
            <el-table :data="order.items" size="small" border>
              <el-table-column label="序号" prop="seq" width="56" align="center" />
              <el-table-column label="标准物料" min-width="170">
                <template #default="{ row }">
                  <div>{{ row.material_name }}</div>
                  <div class="muted">{{ row.material_code }}</div>
                </template>
              </el-table-column>
              <el-table-column label="规格" prop="spec" min-width="100" />
              <el-table-column label="数量" width="96" align="right">
                <template #default="{ row }">{{ qty(row.quantity) }} {{ row.unit }}</template>
              </el-table-column>
              <el-table-column label="含税单价" width="96" align="right">
                <template #default="{ row }">{{ money(row.unit_price) }}</template>
              </el-table-column>
              <el-table-column label="金额" width="116" align="right">
                <template #default="{ row }">{{ money(row.amount) }}</template>
              </el-table-column>
            </el-table>
          </section>

          <section>
            <h3>合同履约配额</h3>
            <QuotaCards :quota="order.quota" />
            <p v-if="order.quota" class="muted note">
              累计已下金额不含本单；本单占用后合同剩余 {{ money(order.quota.after_remaining_amount) }} 元。
            </p>
          </section>

          <section>
            <h3>审批意见</h3>
            <p class="comment" :class="{ muted: !order.approval_comment }">{{ order.approval_comment || '暂无' }}</p>
          </section>

          <section>
            <h3>审计流水</h3>
            <el-timeline v-if="order.audits.length" class="audits">
              <el-timeline-item v-for="(a, i) in order.audits" :key="i" :timestamp="fmtTime(a.created_at)" size="small">
                {{ AUDIT_LABEL[a.action] ?? a.action }} · {{ a.username }}
                <span v-if="a.detail?.comment" class="muted">：{{ a.detail.comment }}</span>
              </el-timeline-item>
            </el-timeline>
            <p v-else class="muted">暂无记录</p>
          </section>
        </div>

        <footer v-if="$slots.footer" class="foot">
          <slot name="footer" :order="order" />
        </footer>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped lang="scss">
.wrap {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 200px;
}
.head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  border-bottom: 1px solid #e3e8ef;
  .no {
    font-size: 16px;
    font-weight: 600;
    color: var(--el-color-primary);
    word-break: break-all;
  }
  .type {
    font-size: 12px;
    color: var(--app-text-secondary);
  }
  .close {
    margin-left: auto;
  }
}
.body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px 2px 12px;
}
section {
  margin-top: 14px;
}
h3 {
  font-size: 14px;
  margin: 0 0 8px;
}
.muted {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.note {
  margin: 6px 0 0;
}
.comment {
  margin: 0;
  white-space: pre-wrap;
}
.audits {
  padding-left: 2px;
  font-size: 13px;
}
.foot {
  border-top: 1px solid #e3e8ef;
  padding-top: 12px;
}
</style>
