<script setup lang="ts">
/** 物料编码字典与别名（FR-050、FR-051）：维护物料与公允价，为物料新增或修改别名；别名保存后对话和图片识别立即使用。 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { errorMessage, http } from '@/api/http'
import { money } from '@/api/types'

interface MaterialRow {
  code: string
  name: string
  spec: string
  unit: string
  brand: string
  category: string
  fair_price: number | null
  aliases: string[]
}
interface AliasRow {
  id: number
  alias: string
  material_code: string
  material_name: string
  spec: string
}

const rows = ref<MaterialRow[]>([])
const aliasRows = ref<AliasRow[]>([])
const loading = ref(false)
const q = ref('')

async function load() {
  loading.value = true
  try {
    const keyword = q.value.trim() || undefined
    const [m, a] = await Promise.all([
      http.get<MaterialRow[]>('/admin/materials', { params: { q: keyword } }),
      http.get<AliasRow[]>('/admin/aliases'),
    ])
    rows.value = m.data
    aliasRows.value = a.data
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    loading.value = false
  }
}

// ---------- 物料 ----------
const mDialog = ref(false)
const mEditing = ref(false)
const mSaving = ref(false)
const mRef = ref<FormInstance>()
const mForm = reactive({
  code: '',
  name: '',
  spec: '',
  unit: '',
  brand: '',
  category: '',
  fair_price: null as number | null,
})
const mRules: FormRules = {
  code: [{ required: true, message: '请填写物料编码', trigger: 'blur' }],
  name: [{ required: true, message: '请填写物料名称', trigger: 'blur' }],
  unit: [{ required: true, message: '请填写计量单位', trigger: 'blur' }],
}

function openMaterial(row?: MaterialRow) {
  mEditing.value = !!row
  Object.assign(
    mForm,
    row
      ? { ...row, fair_price: row.fair_price === null ? null : Number(row.fair_price) }
      : { code: '', name: '', spec: '', unit: '吨', brand: '', category: '', fair_price: null },
  )
  mDialog.value = true
  mRef.value?.clearValidate()
}

async function saveMaterial() {
  if (!(await mRef.value?.validate().catch(() => false))) return
  mSaving.value = true
  try {
    const body = { ...mForm, fair_price: mForm.fair_price || null }
    if (mEditing.value) await http.put(`/admin/materials/${encodeURIComponent(mForm.code)}`, body)
    else await http.post('/admin/materials', body)
    ElMessage.success(`已保存物料 ${mForm.code.toUpperCase()}`)
    mDialog.value = false
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    mSaving.value = false
  }
}

// ---------- 别名 ----------
const aDialog = ref(false)
const aEditingId = ref<number | null>(null)
const aSaving = ref(false)
const aForm = reactive({ alias: '', material_code: '' })

function openAlias(code: string, alias?: string) {
  const row = alias ? aliasRows.value.find((a) => a.alias === alias) : undefined
  aEditingId.value = row?.id ?? null
  Object.assign(aForm, { alias: row?.alias ?? '', material_code: code })
  aDialog.value = true
}

async function saveAlias() {
  if (!aForm.alias.trim()) return ElMessage.warning('请填写别名')
  if (!aForm.material_code) return ElMessage.warning('请选择物料')
  aSaving.value = true
  try {
    if (aEditingId.value) await http.put(`/admin/aliases/${aEditingId.value}`, aForm)
    else await http.post('/admin/aliases', aForm)
    ElMessage.success(`别名“${aForm.alias.trim()}”已对应 ${aForm.material_code}`)
    aDialog.value = false
    load()
  } catch (e) {
    ElMessage.error(errorMessage(e))
  } finally {
    aSaving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="filters">
      <el-input v-model="q" placeholder="编码、名称、规格或别名" clearable class="f-q" @keyup.enter="load" @clear="load" />
      <el-button type="primary" @click="load">查询</el-button>
      <span class="tip">点击别名标签可修改；对话和图片识别按别名把物资映射到物料编码</span>
      <el-button type="primary" plain class="add" @click="openMaterial()">新增物料</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" size="small" empty-text="没有符合条件的物料">
      <el-table-column label="物料编码" prop="code" width="150" />
      <el-table-column label="名称" prop="name" width="110" />
      <el-table-column label="规格" prop="spec" min-width="120" show-overflow-tooltip />
      <el-table-column label="单位" prop="unit" width="56" />
      <el-table-column label="公允价" width="110" align="right">
        <template #default="{ row }">{{ row.fair_price === null ? '未设置' : money(row.fair_price) }}</template>
      </el-table-column>
      <el-table-column label="别名" min-width="280">
        <template #default="{ row }">
          <div class="aliases">
            <el-tag
              v-for="a in row.aliases"
              :key="a"
              size="small"
              effect="plain"
              class="alias"
              @click="openAlias(row.code, a)"
            >{{ a }}</el-tag>
            <el-button link type="primary" size="small" @click="openAlias(row.code)">＋ 别名</el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="" width="60" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openMaterial(row)">修改</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="count">共 {{ rows.length }} 种物料，{{ aliasRows.length }} 个别名</div>

    <el-dialog v-model="mDialog" :title="mEditing ? `修改物料 ${mForm.code}` : '新增物料'" width="min(480px, 94vw)">
      <el-form ref="mRef" :model="mForm" :rules="mRules" label-width="80px">
        <el-form-item label="物料编码" prop="code">
          <el-input v-model="mForm.code" :disabled="mEditing" maxlength="32" placeholder="如 STL-RB-400E-32" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="mForm.name" maxlength="64" />
        </el-form-item>
        <el-form-item label="规格">
          <el-input v-model="mForm.spec" maxlength="64" />
        </el-form-item>
        <el-form-item label="单位" prop="unit">
          <el-input v-model="mForm.unit" maxlength="8" />
        </el-form-item>
        <el-form-item label="品牌">
          <el-input v-model="mForm.brand" maxlength="64" />
        </el-form-item>
        <el-form-item label="类别">
          <el-input v-model="mForm.category" maxlength="32" />
        </el-form-item>
        <el-form-item label="公允价">
          <el-input-number v-model="mForm.fair_price" :min="0" :precision="2" :controls="false" class="full" placeholder="不填则不做偏离提醒" />
        </el-form-item>
      </el-form>
      <p v-if="mEditing" class="hint">物料编码已被合同和订单引用，不能修改。</p>
      <template #footer>
        <el-button @click="mDialog = false">取消</el-button>
        <el-button type="primary" :loading="mSaving" @click="saveMaterial">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="aDialog" :title="aEditingId ? '修改别名' : '新增别名'" width="min(440px, 94vw)">
      <el-form label-width="80px" @submit.prevent="saveAlias">
        <el-form-item label="别名" required>
          <el-input v-model="aForm.alias" maxlength="64" placeholder="业务中的叫法，如 三级螺纹钢" />
        </el-form-item>
        <el-form-item label="对应物料" required>
          <el-select v-model="aForm.material_code" filterable class="full">
            <el-option v-for="m in rows" :key="m.code" :label="`${m.code} ${m.name} ${m.spec}`" :value="m.code" />
          </el-select>
        </el-form-item>
      </el-form>
      <p class="hint">忽略空格和符号后与已有别名相同的不能保存。</p>
      <template #footer>
        <el-button @click="aDialog = false">取消</el-button>
        <el-button type="primary" :loading="aSaving" @click="saveAlias">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  .f-q {
    width: 220px;
  }
  .tip {
    font-size: 12px;
    color: var(--app-text-secondary);
  }
  .add {
    margin-left: auto;
  }
}
.aliases {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}
.alias {
  cursor: pointer;
}
.count {
  margin-top: 10px;
  text-align: right;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.full {
  width: 100%;
}
.hint {
  margin: 0 0 0 80px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
</style>
