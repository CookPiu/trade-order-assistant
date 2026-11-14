<script setup lang="ts">
/** 合同台账（FR-050）：按合同号或签约单位、类型、部门查询，新增和修改合同及明细，不提供删除。 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { errorMessage, http } from '@/api/http'
import { money, qty, type OrderType } from '@/api/types'

interface Option {
  depts: { id: number; code: string; name: string }[]
  parties: { id: number; name: string; kind: string }[]
  projects: { id: number; name: string; address: string; contact: string; phone: string }[]
}
interface MaterialOpt {
  code: string
  name: string
  spec: string
  unit: string
}
interface ContractItemRow {
  material_code: string
  material_name?: string
  spec?: string
  unit?: string
  unit_price: number | null
  quantity: number | null
}
interface ContractRow {
  id: number
  contract_no: string
  contract_type: OrderType
  dept_id: number
  party_name: string
  project_name: string
  address: string
  contact: string
  phone: string
  total_amount: number
  total_qty: number
  unit: string
  sign_date: string
  expire_date: string
  version: number
  used_amount: number
  remaining_amount: number
  items: ContractItemRow[]
}

const TYPE_LABEL: Record<OrderType, string> = { sales: '销售', purchase: '采购' }

const opts = ref<Option>({ depts: [], parties: [], projects: [] })
const materials = ref<MaterialOpt[]>([])
const rows = ref<ContractRow[]>([])
const loading = ref(false)
const filters = reactive({ q: '', contract_type: '' as '' | OrderType, dept_id: null as number | null })

const deptName = (id: number) => opts.value.depts.find((d) => d.id === id)?.name ?? id

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<ContractRow[]>('/admin/contracts', {
      params: {
        q: filters.q.trim() || undefined,
        contract_type: filters.contract_type || undefined,
        dept_id: filters.dept_id || undefined,
      },
    })
    rows.value = data
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  const [o, m] = await Promise.all([
    http.get<Option>('/admin/options'),
    http.get<MaterialOpt[]>('/admin/materials'),
  ])
  opts.value = o.data
  materials.value = m.data
}

// ---------- 表单 ----------
const dialog = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  contract_no: '',
  contract_type: 'sales' as OrderType,
  dept_id: null as number | null,
  party_name: '',
  project_name: '',
  address: '',
  contact: '',
  phone: '',
  total_amount: null as number | null,
  total_qty: null as number | null,
  unit: '吨',
  sign_date: '',
  expire_date: '',
  items: [] as ContractItemRow[],
})

const rules: FormRules = {
  contract_no: [{ required: true, message: '请填写合同号', trigger: 'blur' }],
  dept_id: [{ required: true, message: '请选择所属部门', trigger: 'change' }],
  party_name: [{ required: true, message: '请填写签约单位', trigger: 'blur' }],
  project_name: [{ required: true, message: '请填写工程项目', trigger: 'blur' }],
  address: [{ required: true, message: '请填写收货地址', trigger: 'blur' }],
  contact: [{ required: true, message: '请填写联系人', trigger: 'blur' }],
  total_amount: [{ required: true, message: '请填写合同总金额', trigger: 'blur' }],
  total_qty: [{ required: true, message: '请填写合同总数量', trigger: 'blur' }],
  unit: [{ required: true, message: '请填写单位', trigger: 'blur' }],
  sign_date: [{ required: true, message: '请选择签订日期', trigger: 'change' }],
  expire_date: [{ required: true, message: '请选择到期日期', trigger: 'change' }],
}

const partyOptions = computed(() =>
  opts.value.parties.filter((p) => p.kind === (form.contract_type === 'sales' ? 'customer' : 'supplier')),
)
const itemsAmount = computed(() =>
  form.items.reduce((s, i) => s + (Number(i.unit_price) || 0) * (Number(i.quantity) || 0), 0),
)

function blank() {
  Object.assign(form, {
    contract_no: '',
    contract_type: 'sales',
    dept_id: opts.value.depts[0]?.id ?? null,
    party_name: '',
    project_name: '',
    address: '',
    contact: '',
    phone: '',
    total_amount: null,
    total_qty: null,
    unit: '吨',
    sign_date: '',
    expire_date: '',
    items: [{ material_code: '', unit_price: null, quantity: null }],
  })
}

function openCreate() {
  editingId.value = null
  blank()
  dialog.value = true
  formRef.value?.clearValidate()
}

function openEdit(row: ContractRow) {
  editingId.value = row.id
  Object.assign(form, {
    ...row,
    total_amount: Number(row.total_amount),
    total_qty: Number(row.total_qty),
    items: row.items.map((i) => ({ ...i, unit_price: Number(i.unit_price), quantity: Number(i.quantity) })),
  })
  dialog.value = true
  formRef.value?.clearValidate()
}

/** 选中已有工程项目时带出地址和联系人 */
function pickProject(name: string) {
  const p = opts.value.projects.find((x) => x.name === name)
  if (p) Object.assign(form, { address: p.address, contact: p.contact, phone: p.phone })
}

function addItem() {
  form.items.push({ material_code: '', unit_price: null, quantity: null })
}

async function save() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  if (form.expire_date < form.sign_date) return ElMessage.warning('到期日期不能早于签订日期')
  const items = form.items.filter((i) => i.material_code)
  if (!items.length) return ElMessage.warning('至少填写一条合同明细')
  if (items.some((i) => !i.unit_price || !i.quantity)) return ElMessage.warning('合同明细的单价和数量必须大于 0')
  if (new Set(items.map((i) => i.material_code)).size !== items.length) return ElMessage.warning('合同明细中物料编码重复')
  saving.value = true
  try {
    const body = {
      ...form,
      items: items.map((i) => ({ material_code: i.material_code, unit_price: i.unit_price, quantity: i.quantity })),
    }
    if (editingId.value) await http.put(`/admin/contracts/${editingId.value}`, body)
    else await http.post('/admin/contracts', body)
    ElMessage.success(editingId.value ? `已保存合同 ${form.contract_no}` : `已新增合同 ${form.contract_no}`)
    dialog.value = false
    await Promise.all([load(), loadOptions()])
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    await loadOptions()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
  load()
})
</script>

<template>
  <div>
    <div class="filters">
      <el-input v-model="filters.q" placeholder="合同号或签约单位" clearable class="f-q" @keyup.enter="load" @clear="load" />
      <el-select v-model="filters.contract_type" placeholder="全部类型" clearable class="f-type" @change="load">
        <el-option label="销售合同" value="sales" />
        <el-option label="采购合同" value="purchase" />
      </el-select>
      <el-select v-model="filters.dept_id" placeholder="全部部门" clearable class="f-dept" @change="load">
        <el-option v-for="d in opts.depts" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <el-button type="primary" @click="load">查询</el-button>
      <el-button type="primary" plain class="add" @click="openCreate">新增合同</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" size="small" empty-text="没有符合条件的合同">
      <el-table-column type="expand">
        <template #default="{ row }">
          <el-table :data="row.items" size="small" class="sub-table">
            <el-table-column label="物料编码" prop="material_code" width="160" />
            <el-table-column label="物料名称" prop="material_name" min-width="120" />
            <el-table-column label="规格" prop="spec" min-width="120" />
            <el-table-column label="合同单价" width="120" align="right">
              <template #default="{ row: i }">{{ money(i.unit_price) }}</template>
            </el-table-column>
            <el-table-column label="合同数量" width="110" align="right">
              <template #default="{ row: i }">{{ qty(i.quantity) }} {{ i.unit }}</template>
            </el-table-column>
          </el-table>
        </template>
      </el-table-column>
      <el-table-column label="合同号" prop="contract_no" width="120" />
      <el-table-column label="类型" width="60">
        <template #default="{ row }">{{ TYPE_LABEL[row.contract_type as OrderType] }}</template>
      </el-table-column>
      <el-table-column label="所属部门" width="120" show-overflow-tooltip>
        <template #default="{ row }">{{ deptName(row.dept_id) }}</template>
      </el-table-column>
      <el-table-column label="签约单位" prop="party_name" min-width="170" show-overflow-tooltip />
      <el-table-column label="工程项目" prop="project_name" min-width="120" show-overflow-tooltip />
      <el-table-column label="总金额" width="130" align="right">
        <template #default="{ row }">{{ money(row.total_amount) }}</template>
      </el-table-column>
      <el-table-column label="剩余金额" width="130" align="right">
        <template #default="{ row }">
          <span :class="{ over: row.remaining_amount < 0 }">{{ money(row.remaining_amount) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="有效期" width="180">
        <template #default="{ row }">{{ row.sign_date }} 至 {{ row.expire_date }}</template>
      </el-table-column>
      <el-table-column label="" width="60" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row)">修改</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="count">共 {{ rows.length }} 份合同</div>

    <el-dialog v-model="dialog" :title="editingId ? `修改合同 ${form.contract_no}` : '新增合同'" width="min(760px, 94vw)" top="6vh">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px" size="default">
        <div class="grid">
          <el-form-item label="合同号" prop="contract_no">
            <el-input v-model="form.contract_no" maxlength="32" />
          </el-form-item>
          <el-form-item label="合同类型">
            <el-radio-group v-model="form.contract_type">
              <el-radio-button value="sales">销售</el-radio-button>
              <el-radio-button value="purchase">采购</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="所属部门" prop="dept_id">
            <el-select v-model="form.dept_id">
              <el-option v-for="d in opts.depts" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
          </el-form-item>
          <el-form-item :label="form.contract_type === 'sales' ? '客户' : '供应商'" prop="party_name">
            <el-autocomplete
              v-model="form.party_name"
              :fetch-suggestions="(q: string, cb: (v: { value: string }[]) => void) => cb(partyOptions.filter((p) => p.name.includes(q)).map((p) => ({ value: p.name })))"
              placeholder="选择已有单位或输入新单位"
              maxlength="128"
            />
          </el-form-item>
          <el-form-item label="工程项目" prop="project_name">
            <el-autocomplete
              v-model="form.project_name"
              :fetch-suggestions="(q: string, cb: (v: { value: string }[]) => void) => cb(opts.projects.filter((p) => p.name.includes(q)).map((p) => ({ value: p.name })))"
              placeholder="选择已有项目或输入新项目"
              maxlength="128"
              @select="(v: { value: string }) => pickProject(v.value)"
            />
          </el-form-item>
          <el-form-item label="联系人" prop="contact">
            <el-input v-model="form.contact" maxlength="32" />
          </el-form-item>
          <el-form-item label="收货地址" prop="address" class="wide">
            <el-input v-model="form.address" maxlength="255" />
          </el-form-item>
          <el-form-item label="联系电话">
            <el-input v-model="form.phone" maxlength="32" />
          </el-form-item>
          <el-form-item label="单位" prop="unit">
            <el-input v-model="form.unit" maxlength="8" />
          </el-form-item>
          <el-form-item label="总金额" prop="total_amount">
            <el-input-number v-model="form.total_amount" :min="0.01" :precision="2" :controls="false" class="num" />
          </el-form-item>
          <el-form-item label="总数量" prop="total_qty">
            <el-input-number v-model="form.total_qty" :min="0.001" :precision="3" :controls="false" class="num" />
          </el-form-item>
          <el-form-item label="签订日期" prop="sign_date">
            <el-date-picker v-model="form.sign_date" type="date" value-format="YYYY-MM-DD" class="date" />
          </el-form-item>
          <el-form-item label="到期日期" prop="expire_date">
            <el-date-picker v-model="form.expire_date" type="date" value-format="YYYY-MM-DD" class="date" />
          </el-form-item>
        </div>
        <p v-if="editingId" class="hint">修改合同总金额会立即影响后续提单的额度核验；已提交订单的金额不变。</p>

        <div class="items-head">
          <span>合同明细</span>
          <span class="sum">明细金额合计 {{ money(itemsAmount) }}</span>
          <el-button link type="primary" @click="addItem">添加明细</el-button>
        </div>
        <el-table :data="form.items" size="small" class="items">
          <el-table-column label="物料" min-width="260">
            <template #default="{ row }">
              <el-select v-model="row.material_code" filterable placeholder="从物料字典选择" class="full">
                <el-option
                  v-for="m in materials"
                  :key="m.code"
                  :label="`${m.code} ${m.name} ${m.spec}`"
                  :value="m.code"
                />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="合同单价" width="140">
            <template #default="{ row }">
              <el-input-number v-model="row.unit_price" :min="0.01" :precision="2" :controls="false" class="full" />
            </template>
          </el-table-column>
          <el-table-column label="合同数量" width="130">
            <template #default="{ row }">
              <el-input-number v-model="row.quantity" :min="0.001" :precision="3" :controls="false" class="full" />
            </template>
          </el-table-column>
          <el-table-column label="" width="56">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" :disabled="form.items.length === 1" @click="form.items.splice($index, 1)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
  .f-q {
    width: 200px;
  }
  .f-type,
  .f-dept {
    width: 140px;
  }
  .add {
    margin-left: auto;
  }
}
.sub-table {
  margin: 0 12px 0 48px;
  width: auto;
}
.over {
  color: var(--app-over);
  font-weight: 600;
}
.count {
  margin-top: 10px;
  text-align: right;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 12px;
  .wide {
    grid-column: span 1;
  }
  :deep(.el-select),
  :deep(.el-autocomplete),
  .num,
  :deep(.date) {
    width: 100%;
  }
}
.hint {
  margin: -4px 0 8px 96px;
  font-size: 12px;
  color: var(--app-warn-dark, #a16e0e);
}
.items-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 4px 0 6px;
  font-weight: 600;
  .sum {
    margin-left: auto;
    font-weight: normal;
    font-size: 12px;
    color: var(--app-text-secondary);
  }
}
.full {
  width: 100%;
}
@media (max-width: 760px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .hint {
    margin-left: 0;
  }
}
</style>
