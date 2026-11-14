<script setup lang="ts">
/** 批量导入与数据中心（FR-017、FR-036、FR-047）：模板下载、上传校验、行内修改、批量提交、导入记录。 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { errorMessage, http } from '@/api/http'
import { money, qty } from '@/api/types'

interface RowInput {
  order_type: string
  contract_no: string
  raw_name: string
  spec: string
  quantity: string
  unit_price: string
  delivery_date: string
  remark: string
  material_code?: string
}

interface BatchRow {
  id: number
  row_no: number
  input: RowInput
  result: {
    material_code?: string | null
    material_name?: string
    material_spec?: string
    unit?: string
    amount?: string | null
    candidates?: { code: string; name: string; spec: string }[]
    party_name?: string
    remaining_amount?: string | null
  }
  status: 'ok' | 'over' | 'error' | 'submitted' | 'failed'
  issues: { field: string; level: string; message: string }[]
  order_no: string | null
  message: string
}

interface BatchSummary {
  id: number
  file_name: string
  created_at: string | null
  total_rows: number
  success_rows: number
  failed_rows: number
  status: string
}

interface BatchView extends BatchSummary {
  rows: BatchRow[]
}

const STATUS: Record<BatchRow['status'], { text: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  ok: { text: '可提交', type: 'success' },
  over: { text: '超额·转待特批', type: 'warning' },
  error: { text: '异常', type: 'danger' },
  submitted: { text: '已提交', type: 'success' },
  failed: { text: '提交失败', type: 'danger' },
}

const route = useRoute()
const router = useRouter()
const input = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const uploading = ref(false)
const submitting = ref(false)
const batch = ref<BatchView | null>(null)
const history = ref<BatchSummary[]>([])
const historyLoading = ref(false)
const editingId = ref<number | null>(null)
const savingRow = ref(false)
const editForm = reactive<RowInput>({
  order_type: '',
  contract_no: '',
  raw_name: '',
  spec: '',
  quantity: '',
  unit_price: '',
  delivery_date: '',
  remark: '',
  material_code: '',
})

const counts = computed(() => {
  const rows = batch.value?.rows ?? []
  return {
    ready: rows.filter((r) => r.status === 'ok' || r.status === 'over').length,
    error: rows.filter((r) => r.status === 'error' || r.status === 'failed').length,
    submitted: rows.filter((r) => r.status === 'submitted').length,
  }
})

function rowClass({ row }: { row: BatchRow }) {
  if (row.status === 'error' || row.status === 'failed') return 'row-error'
  if (row.status === 'over') return 'row-over'
  if (row.status === 'submitted') return 'row-done'
  return ''
}

function fieldError(row: BatchRow, ...fields: string[]) {
  return row.issues.some((i) => i.level === 'error' && fields.includes(i.field))
}

function fmtTime(v: string | null) {
  return v ? v.replace('T', ' ').slice(0, 19) : '—'
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const { data } = await http.get<BatchSummary[]>('/batch')
    history.value = data
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    historyLoading.value = false
  }
}

async function openBatch(id: number) {
  try {
    const { data } = await http.get<BatchView>(`/batch/${id}`)
    batch.value = data
    editingId.value = null
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

watch(
  () => batch.value?.id,
  (id) => {
    if (id && String(route.query.id) !== String(id)) router.replace({ query: { id: String(id) } })
  },
)

async function downloadTemplate() {
  try {
    const { data } = await http.get<Blob>('/batch/template', { responseType: 'blob' })
    const url = URL.createObjectURL(data)
    const a = document.createElement('a')
    a.href = url
    a.download = '批量提单模板.xlsx'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(errorMessage(e))
  }
}

async function upload(file: File) {
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    ElMessage.error('只支持 .xlsx 格式的 Excel 文件')
    return
  }
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', file, file.name)
    const { data } = await http.post<BatchView>('/batch', form)
    batch.value = data
    editingId.value = null
    loadHistory()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    uploading.value = false
  }
}

function onPick(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) upload(file)
  ;(e.target as HTMLInputElement).value = ''
}

function onDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) upload(file)
}

function startEdit(row: BatchRow) {
  Object.assign(editForm, { material_code: '', ...row.input })
  editingId.value = row.id
}

async function saveRow(row: BatchRow) {
  if (!batch.value) return
  savingRow.value = true
  try {
    const body = { ...editForm }
    // 改了物料名称时重新映射，不沿用之前选的编码
    if (body.raw_name !== row.input.raw_name) body.material_code = ''
    const { data } = await http.put<BatchView>(`/batch/${batch.value.id}/rows/${row.id}`, body)
    batch.value = data
    editingId.value = null
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    savingRow.value = false
  }
}

async function submitAll() {
  if (!batch.value || !counts.value.ready) return
  const skip = counts.value.error
  if (skip) {
    try {
      await ElMessageBox.confirm(
        `还有 ${skip} 行异常，这些行不会提交。是否先提交其余 ${counts.value.ready} 行？`,
        '批量提交',
        { confirmButtonText: '提交', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }
  submitting.value = true
  try {
    const { data } = await http.post<BatchView>(`/batch/${batch.value.id}/submit`)
    batch.value = data
    editingId.value = null
    const ok = data.rows.filter((r) => r.status === 'submitted').length
    ElMessage.success(`提交完成：已生成 ${ok} 笔订单`)
    loadHistory()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadHistory()
  const id = Number(route.query.id)
  if (id) openBatch(id)
})
</script>

<template>
  <div class="batch-page">
    <section class="app-panel import">
      <header class="head">
        <h2>批量导入</h2>
        <span class="sub">一行一笔单物资订单，异常行修正后可批量提交</span>
        <el-button class="tpl" @click="downloadTemplate">下载导入模板</el-button>
      </header>

      <div
        class="drop"
        :class="{ dragging, compact: !!batch }"
        role="button"
        tabindex="0"
        @click="input?.click()"
        @keydown.enter="input?.click()"
        @dragover.prevent="dragging = true"
        @dragleave.prevent="dragging = false"
        @drop.prevent="onDrop"
      >
        <template v-if="uploading">正在解析与校验…</template>
        <template v-else>
          <strong>{{ batch ? '上传新的 Excel' : '点击选择或拖拽 Excel 文件到此处' }}</strong>
          <span>仅支持 .xlsx，不超过 5 MB；列结构须与导入模板一致</span>
        </template>
        <input ref="input" type="file" accept=".xlsx" hidden @change="onPick" />
      </div>

      <template v-if="batch">
        <div class="summary">
          <span class="file">{{ batch.file_name }}</span>
          <span>共 {{ batch.total_rows }} 行</span>
          <span class="ok">可提交 {{ counts.ready }}</span>
          <span class="bad">异常 {{ counts.error }}</span>
          <span v-if="counts.submitted" class="done">已提交 {{ counts.submitted }}</span>
          <el-button
            type="primary"
            class="submit"
            :loading="submitting"
            :disabled="!counts.ready || editingId !== null"
            @click="submitAll"
          >
            批量提交（{{ counts.ready }} 行）
          </el-button>
        </div>

        <el-table :data="batch.rows" :row-class-name="rowClass" row-key="id" border size="small" class="rows">
          <el-table-column label="行" prop="row_no" width="46" align="center" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="STATUS[row.status as BatchRow['status']].type" size="small" effect="light">
                {{ STATUS[row.status as BatchRow['status']].text }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="72">
            <template #default="{ row }">
              <el-select v-if="editingId === row.id" v-model="editForm.order_type" size="small">
                <el-option label="销售" value="销售" />
                <el-option label="采购" value="采购" />
              </el-select>
              <span v-else :class="{ bad: fieldError(row, 'order_type') }">{{ row.input.order_type || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="合同编号" width="120">
            <template #default="{ row }">
              <el-input v-if="editingId === row.id" v-model="editForm.contract_no" size="small" />
              <span v-else :class="{ bad: fieldError(row, 'contract_no') }">{{ row.input.contract_no || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="物料（原文 → 标准物料）" min-width="180">
            <template #default="{ row }">
              <template v-if="editingId === row.id">
                <el-input v-model="editForm.raw_name" size="small" placeholder="物料名称" />
                <el-select
                  v-if="row.result.candidates?.length"
                  v-model="editForm.material_code"
                  size="small"
                  placeholder="从候选中选择"
                  class="cand"
                >
                  <el-option
                    v-for="c in row.result.candidates"
                    :key="c.code"
                    :label="`${c.name} ${c.spec}`"
                    :value="c.code"
                  />
                </el-select>
              </template>
              <template v-else>
                <div>{{ row.input.raw_name }} <span class="muted">{{ row.input.spec }}</span></div>
                <div v-if="row.result.material_code" class="mapped">
                  → {{ row.result.material_name }} {{ row.result.material_spec }}
                </div>
                <div v-else-if="fieldError(row, 'items.0.material_code')" class="bad small">未匹配标准物料</div>
              </template>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="88" align="right">
            <template #default="{ row }">
              <el-input v-if="editingId === row.id" v-model="editForm.quantity" size="small" />
              <span v-else :class="{ bad: fieldError(row, 'items.0.quantity') }">
                {{ row.input.quantity ? qty(row.input.quantity) : '—' }} {{ row.result.unit }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="单价" width="88" align="right">
            <template #default="{ row }">
              <el-input v-if="editingId === row.id" v-model="editForm.unit_price" size="small" />
              <span v-else :class="{ bad: fieldError(row, 'items.0.unit_price') }">
                {{ row.input.unit_price ? money(row.input.unit_price) : '缺失' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="金额" width="104" align="right">
            <template #default="{ row }">{{ money(row.result.amount) }}</template>
          </el-table-column>
          <el-table-column label="交期" width="120">
            <template #default="{ row }">
              <el-date-picker
                v-if="editingId === row.id"
                v-model="editForm.delivery_date"
                type="date"
                value-format="YYYY-MM-DD"
                size="small"
                :clearable="false"
                style="width: 100%"
              />
              <span v-else :class="{ bad: fieldError(row, 'delivery_date') }">{{ row.input.delivery_date || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="备注" min-width="110">
            <template #default="{ row }">
              <el-input v-if="editingId === row.id" v-model="editForm.remark" size="small" placeholder="超额时必填" />
              <span v-else :class="{ bad: fieldError(row, 'remark') }">{{ row.input.remark || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="结果 / 原因" min-width="230">
            <template #default="{ row }">
              <div v-if="row.order_no" class="order-no">{{ row.order_no }}</div>
              <div v-if="row.message" :class="row.status === 'submitted' ? 'muted small' : 'reason'">{{ row.message }}</div>
              <div v-else-if="!row.order_no && row.result.remaining_amount" class="muted small">
                合同剩余 {{ money(row.result.remaining_amount) }}
              </div>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="96" fixed="right" align="center">
            <template #default="{ row }">
              <template v-if="editingId === row.id">
                <el-button link type="primary" size="small" :loading="savingRow" @click="saveRow(row)">校验</el-button>
                <el-button link size="small" @click="editingId = null">取消</el-button>
              </template>
              <el-button
                v-else-if="row.status !== 'submitted'"
                link
                type="primary"
                size="small"
                :disabled="editingId !== null || submitting"
                @click="startEdit(row)"
              >
                修改
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </section>

    <section class="app-panel records">
      <header class="head">
        <h2>导入记录</h2>
        <span class="sub">点击记录查看该批次每行的订单号或失败原因</span>
      </header>
      <el-table
        v-loading="historyLoading"
        :data="history"
        size="small"
        highlight-current-row
        class="history"
        empty-text="暂无导入记录"
        @row-click="(r: BatchSummary) => openBatch(r.id)"
      >
        <el-table-column label="文件名" prop="file_name" min-width="200" show-overflow-tooltip />
        <el-table-column label="导入时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="总行数" prop="total_rows" width="80" align="right" />
        <el-table-column label="成功" prop="success_rows" width="80" align="right" />
        <el-table-column label="失败" prop="failed_rows" width="80" align="right" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">{{ row.status === 'submitted' ? '已提交' : '待提交' }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped lang="scss">
.batch-page {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
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
  margin-bottom: 10px;
  h2 {
    font-size: 15px;
    margin: 0;
  }
  .sub {
    font-size: 12px;
    color: var(--app-text-secondary);
  }
  .tpl {
    margin-left: auto;
  }
}
.drop {
  border: 1px dashed #b8c4d6;
  border-radius: 6px;
  background: #f6f8fb;
  padding: 26px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  text-align: center;
  font-size: 13px;
  color: var(--app-text-secondary);
  transition: border-color 0.15s, background 0.15s;
  strong {
    font-size: 14px;
    color: var(--el-color-primary);
  }
  span {
    font-size: 12px;
  }
  &:hover,
  &.dragging {
    border-color: var(--el-color-primary);
    background: var(--el-color-primary-light-9);
  }
  &.compact {
    padding: 10px 16px;
    flex-direction: row;
    justify-content: center;
    gap: 12px;
  }
}
.summary {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin: 12px 0 8px;
  font-size: 13px;
  .file {
    font-weight: 600;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .ok {
    color: var(--el-color-success);
  }
  .bad {
    color: var(--app-over);
  }
  .done {
    color: var(--el-color-primary);
  }
  .submit {
    margin-left: auto;
  }
}
.rows {
  width: 100%;
  :deep(.row-error) {
    --el-table-tr-bg-color: var(--app-over-bg);
  }
  :deep(.row-over) {
    --el-table-tr-bg-color: var(--app-warn-bg);
  }
  :deep(.el-table__cell) {
    vertical-align: top;
  }
}
.bad {
  color: var(--app-over);
  font-weight: 600;
}
.small {
  font-size: 12px;
}
.muted {
  color: var(--app-text-secondary);
}
.mapped {
  font-size: 12px;
  color: var(--el-color-success);
}
.cand {
  margin-top: 4px;
  width: 100%;
}
.reason,
.order-no {
  word-break: break-all;
}
.reason {
  color: var(--app-over);
  font-size: 12px;
  line-height: 1.5;
}
.order-no {
  font-weight: 600;
  color: var(--el-color-primary);
}
.history {
  width: 100%;
  :deep(.el-table__row) {
    cursor: pointer;
  }
}
</style>
