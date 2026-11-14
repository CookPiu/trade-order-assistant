<script setup lang="ts">
/** 订单草稿预览与核验区（FR-030、FR-031、FR-023）。字段可编辑，修改后保存到服务端重新校验。 */
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { errorMessage, http, type ApiIssue } from '@/api/http'
import {
  emptyDraft,
  money,
  ORDER_STATUS_LABEL,
  ORDER_TYPE_LABEL,
  type Candidate,
  type ContractDetail,
  type DraftData,
  type DraftItem,
} from '@/api/types'
import QuotaCards from '@/components/QuotaCards.vue'
import SubmitBar from '@/components/SubmitBar.vue'
import { useDraftStore } from '@/stores/draft'

const store = useDraftStore()
const router = useRouter()
const form = ref<DraftData>(emptyDraft())
const contract = ref<ContractDetail | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined

const view = computed(() => store.view)
const locked = computed(() => store.submitted || !view.value)

watch(
  () => view.value,
  (v) => {
    form.value = v ? JSON.parse(JSON.stringify(v.data)) : emptyDraft()
  },
  { immediate: true },
)

watch(
  () => form.value.contract_no,
  async (no) => {
    contract.value = null
    if (!no) return
    try {
      const { data } = await http.get<ContractDetail>(`/master/contracts/${encodeURIComponent(no)}`)
      contract.value = data
    } catch {
      contract.value = null
    }
  },
  { immediate: true },
)

const capsule = computed(() => {
  const v = view.value
  if (!v) return { text: '暂无草稿', type: 'info' as const }
  if (v.status === 'submitted') {
    const s = v.order_status ?? 'submitted'
    return { text: ORDER_STATUS_LABEL[s] ?? '已提交', type: s === 'pending_special' ? ('warning' as const) : ('success' as const) }
  }
  if (v.status === 'pending_confirm') return { text: '待确认', type: 'danger' as const }
  return { text: '草稿未提交', type: 'primary' as const }
})

function issuesOf(field: string): ApiIssue[] {
  return view.value?.issues.filter((i) => i.field === field) ?? []
}
function cls(field: string) {
  const list = issuesOf(field)
  if (list.some((i) => i.level === 'error')) return 'field-pending'
  if (list.some((i) => i.level === 'warning')) return 'field-warn'
  return ''
}

const overIssue = computed(() => view.value?.issues.find((i) => i.level === 'over'))
const warnings = computed(() => view.value?.issues.filter((i) => i.level === 'warning' && i.field.startsWith('quota')) ?? [])
const generalErrors = computed(
  () => view.value?.issues.filter((i) => i.level === 'error' && i.field === 'items') ?? [],
)

function options(item: DraftItem): Candidate[] {
  const map = new Map<string, Candidate>()
  for (const c of contract.value?.items ?? []) {
    map.set(c.material_code, { code: c.material_code, name: c.material_name, spec: c.spec, unit: c.unit })
  }
  for (const c of item.candidates ?? []) if (!map.has(c.code)) map.set(c.code, c)
  if (item.material_code && !map.has(item.material_code)) {
    map.set(item.material_code, { code: item.material_code, name: item.material_name, spec: item.spec, unit: item.unit })
  }
  return [...map.values()]
}

function schedule(delay = 600) {
  if (locked.value) return
  clearTimeout(timer)
  timer = setTimeout(save, delay)
}

async function save() {
  clearTimeout(timer)
  try {
    await store.save(JSON.parse(JSON.stringify(form.value)))
  } catch (e) {
    ElMessage.error(`保存失败：${errorMessage(e)}`)
  }
}

function onMaterial(item: DraftItem) {
  item.material_name = ''
  item.spec = ''
  schedule(0)
}

function addItem() {
  form.value.items.push({
    raw_name: '',
    material_code: null,
    material_name: '',
    spec: '',
    unit: '',
    quantity: null,
    unit_price: null,
    amount: null,
    candidates: [],
  })
}

function removeItem(idx: number) {
  form.value.items.splice(idx, 1)
  schedule(0)
}

function toWidget() {
  router.push({ name: 'trade-orders', query: { widget: 'open' } })
}
</script>

<template>
  <div class="preview">
    <div class="head">
      <div class="title">
        订单草稿
        <el-tag :type="capsule.type" effect="dark" round size="small">{{ capsule.text }}</el-tag>
        <span v-if="view" class="type">{{ ORDER_TYPE_LABEL[form.order_type] }}</span>
      </div>
      <span v-if="store.saving" class="saving">保存中…</span>
    </div>

    <div v-if="!view" class="empty-hint">在左侧描述订单或点击“新建销售订单”，草稿会显示在这里。</div>

    <div v-else class="body">
      <el-alert
        v-if="view.order_status === 'returned' && !store.submitted"
        type="warning"
        :closable="false"
        show-icon
        :title="`退回修改：${view.order_no}，重新提交后沿用原单号`"
        :description="view.approval_comment ? `退回意见：${view.approval_comment}` : undefined"
        class="banner"
      />
      <el-alert
        v-if="overIssue"
        type="error"
        effect="dark"
        :closable="false"
        show-icon
        title="超额警告"
        :description="overIssue.message"
        class="banner"
      />
      <el-alert
        v-for="w in warnings"
        :key="w.field"
        type="warning"
        :closable="false"
        show-icon
        :title="w.message"
        class="banner"
      />

      <QuotaCards :quota="view.quota" />

      <section class="section">
        <h3>基本信息</h3>
        <el-form label-position="top" :disabled="locked" class="grid" @submit.prevent>
          <el-form-item label="单据类型">
            <el-select v-model="form.order_type" @change="schedule(0)">
              <el-option label="销售订单" value="sales" />
              <el-option label="采购订单" value="purchase" />
            </el-select>
          </el-form-item>
          <el-form-item label="合同编号" :class="cls('contract_no')">
            <el-input v-model="form.contract_no" placeholder="如 2026-WZ-089" @change="schedule(0)" />
            <div v-for="i in issuesOf('contract_no')" :key="i.message" class="field-reason error">{{ i.message }}</div>
          </el-form-item>
          <el-form-item label="签约单位">
            <el-input :model-value="form.party_name" disabled />
          </el-form-item>
          <el-form-item label="工程项目">
            <el-input :model-value="form.project_name" disabled />
          </el-form-item>
          <el-form-item label="交期" :class="cls('delivery_date')">
            <el-date-picker
              v-model="form.delivery_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择交期"
              style="width: 100%"
              @change="schedule(0)"
            />
            <div v-for="i in issuesOf('delivery_date')" :key="i.message" class="field-reason error">{{ i.message }}</div>
          </el-form-item>
          <el-form-item label="收货地址" :class="cls('address')" class="wide">
            <el-input v-model="form.address" @change="schedule(0)" />
            <div v-for="i in issuesOf('address')" :key="i.message" class="field-reason error">{{ i.message }}</div>
          </el-form-item>
          <el-form-item label="联系人">
            <el-input v-model="form.contact" @change="schedule(0)" />
          </el-form-item>
          <el-form-item label="业务名称">
            <el-input :model-value="form.biz_name" disabled />
          </el-form-item>
          <el-form-item label="采购模式">
            <el-input :model-value="form.purchase_mode" disabled />
          </el-form-item>
          <el-form-item label="业务标签">
            <el-input :model-value="form.biz_tag" disabled />
          </el-form-item>
          <el-form-item label="经办人 / 经办单位">
            <el-input :model-value="`${form.operator_name} / ${form.dept_name}`" disabled />
          </el-form-item>
          <el-form-item label="创建人 / 创建时间">
            <el-input :model-value="`${form.creator_name} / ${form.created_at}`" disabled />
          </el-form-item>
        </el-form>
      </section>

      <section class="section">
        <div class="section-head">
          <h3>产品明细</h3>
          <el-button v-if="!locked" link type="primary" @click="addItem">添加一行</el-button>
        </div>
        <div v-for="i in generalErrors" :key="i.message" class="field-reason error">{{ i.message }}</div>
        <el-table :data="form.items" size="small" border class="items" empty-text="暂无物资明细">
          <el-table-column type="index" label="序号" width="52" align="center" />
          <el-table-column label="标准物料" min-width="180">
            <template #default="{ row, $index }">
              <div :class="cls(`items.${$index}.material_code`)">
                <el-select
                  v-model="row.material_code"
                  filterable
                  placeholder="选择物料"
                  :disabled="locked"
                  style="width: 100%"
                  @change="onMaterial(row)"
                >
                  <el-option v-for="o in options(row)" :key="o.code" :value="o.code" :label="`${o.name} ${o.spec}`">
                    <span>{{ o.name }} {{ o.spec }}</span>
                    <span class="code">{{ o.code }}</span>
                  </el-option>
                </el-select>
              </div>
              <div v-if="row.raw_name" class="raw">原文：{{ row.raw_name }}</div>
              <div v-for="i in issuesOf(`items.${$index}.material_code`)" :key="i.message" class="field-reason error">
                {{ i.message }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="规格" prop="spec" min-width="90" show-overflow-tooltip />
          <el-table-column label="数量" width="104">
            <template #default="{ row, $index }">
              <div :class="cls(`items.${$index}.quantity`)">
                <el-input-number
                  v-model="row.quantity"
                  :min="0"
                  :precision="3"
                  :controls="false"
                  :disabled="locked"
                  style="width: 100%"
                  @change="schedule()"
                />
              </div>
              <div v-for="i in issuesOf(`items.${$index}.quantity`)" :key="i.message" class="field-reason error">{{ i.message }}</div>
            </template>
          </el-table-column>
          <el-table-column label="单位" prop="unit" width="52" align="center" />
          <el-table-column label="含税单价" width="112">
            <template #default="{ row, $index }">
              <div :class="cls(`items.${$index}.unit_price`)">
                <el-input-number
                  v-model="row.unit_price"
                  :min="0"
                  :precision="2"
                  :controls="false"
                  :disabled="locked"
                  style="width: 100%"
                  @change="schedule()"
                />
              </div>
              <div
                v-for="i in issuesOf(`items.${$index}.unit_price`)"
                :key="i.message"
                class="field-reason"
                :class="i.level === 'info' ? 'info' : i.level"
              >
                {{ i.message }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="金额" min-width="110" align="right">
            <template #default="{ row }">{{ money(row.amount) }}</template>
          </el-table-column>
          <el-table-column v-if="!locked" width="56" align="center">
            <template #default="{ $index }">
              <el-button link type="danger" @click="removeItem($index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <SubmitBar v-if="view" @save="save" @switch="toWidget" />
  </div>
</template>

<style scoped lang="scss">
.preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid #edf0f4;
}
.title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
}
.type {
  color: var(--app-text-secondary);
  font-weight: normal;
  font-size: 13px;
}
.saving {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px;
}
.banner {
  margin-bottom: 8px;
}
.section {
  margin-top: 14px;
  h3 {
    font-size: 14px;
    margin: 0 0 8px;
    color: #33404f;
  }
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  h3 {
    margin: 0 0 8px;
  }
}
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  column-gap: 12px;
  :deep(.el-form-item) {
    margin-bottom: 10px;
  }
  :deep(.el-form-item__label) {
    margin-bottom: 2px !important;
    line-height: 18px;
    font-size: 12px;
    color: var(--app-text-secondary);
  }
  .wide {
    grid-column: span 2;
  }
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.items {
  width: 100%;
}
.raw {
  font-size: 12px;
  color: #8a94a2;
  margin-top: 2px;
}
.code {
  float: right;
  color: #8a94a2;
  font-size: 12px;
  margin-left: 12px;
}
.field-reason.info {
  color: #8a94a2;
}
</style>
