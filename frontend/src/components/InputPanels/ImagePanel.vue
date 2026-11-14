<script setup lang="ts">
/** 单据图片识别面板（FR-015）：点击、拖拽、粘贴上传，展示识别卡片，一键应用为草稿。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { errorMessage, http } from '@/api/http'
import { money, qty, ORDER_TYPE_LABEL, type RecognizeResponse } from '@/api/types'
import { useDraftStore } from '@/stores/draft'

const emit = defineEmits<{ (e: 'applied'): void }>()

const MAX_BYTES = 10 * 1024 * 1024
const ACCEPT = ['image/jpeg', 'image/png']

const store = useDraftStore()
const input = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const recognizing = ref(false)
const fileName = ref('')
const previewUrl = ref('')
const result = ref<RecognizeResponse | null>(null)
const error = ref('')

const over = computed(() => result.value?.issues.find((i) => i.level === 'over') ?? null)
const errors = computed(() => result.value?.issues.filter((i) => i.level === 'error') ?? [])

function setPreview(file: File) {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(file)
}

async function recognize(file: File) {
  if (recognizing.value) return
  if (!ACCEPT.includes(file.type)) {
    ElMessage.error('只支持 JPG 或 PNG 格式的图片')
    return
  }
  if (file.size > MAX_BYTES) {
    ElMessage.error('图片超过 10 MB，请压缩后重新上传')
    return
  }
  fileName.value = file.name || '粘贴的图片.png'
  setPreview(file)
  result.value = null
  error.value = ''
  recognizing.value = true
  try {
    const form = new FormData()
    form.append('file', file, fileName.value)
    const { data } = await http.post<RecognizeResponse>('/ocr', form)
    result.value = data
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    recognizing.value = false
  }
}

function onPick(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (file) recognize(file)
  ;(e.target as HTMLInputElement).value = ''
}

function onDrop(e: DragEvent) {
  dragging.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) recognize(file)
}

function onPaste(e: ClipboardEvent) {
  const item = Array.from(e.clipboardData?.items ?? []).find((i) => i.kind === 'file' && i.type.startsWith('image/'))
  const file = item?.getAsFile()
  if (file) {
    e.preventDefault()
    recognize(file)
  }
}

async function apply() {
  if (!result.value) return
  try {
    await store.applyRecognized(result.value, fileName.value)
    emit('applied')
  } catch (e) {
    ElMessage.error(`应用失败：${errorMessage(e)}`)
  }
}

function reset() {
  result.value = null
  error.value = ''
  fileName.value = ''
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

onMounted(() => window.addEventListener('paste', onPaste))
onBeforeUnmount(() => {
  window.removeEventListener('paste', onPaste)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <div class="image-panel">
    <div
      class="drop"
      :class="{ dragging, compact: !!previewUrl }"
      role="button"
      tabindex="0"
      @click="input?.click()"
      @keydown.enter="input?.click()"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <img v-if="previewUrl" :src="previewUrl" alt="单据图片预览" class="thumb" />
      <div class="drop-text">
        <strong>{{ previewUrl ? '更换图片' : '上传发货签收单、磅单或采购合同照片' }}</strong>
        <span>点击选择、拖拽到此处，或直接 Ctrl+V 粘贴；JPG、PNG，不超过 10 MB</span>
        <span v-if="fileName" class="file">{{ fileName }}</span>
      </div>
      <input ref="input" type="file" accept="image/jpeg,image/png" hidden @change="onPick" />
    </div>

    <div v-if="recognizing" class="state">
      <el-icon class="is-loading"><svg viewBox="0 0 1024 1024"><path fill="currentColor" d="M512 64a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V96a32 32 0 0 1 32-32zm0 640a32 32 0 0 1 32 32v192a32 32 0 1 1-64 0V736a32 32 0 0 1 32-32zm448-192a32 32 0 0 1-32 32H736a32 32 0 1 1 0-64h192a32 32 0 0 1 32 32zm-640 0a32 32 0 0 1-32 32H96a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32z"/></svg></el-icon>
      正在识别单据，通常需要几秒…
    </div>

    <el-alert v-else-if="error" :title="error" type="error" show-icon :closable="false" class="state-alert" />

    <div v-if="result" class="card">
      <div class="card-head">
        <span class="title">识别结果</span>
        <el-tag size="small" effect="plain">{{ result.card.doc_type }}</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ ORDER_TYPE_LABEL[result.data.order_type] }}</el-tag>
      </div>
      <dl class="fields">
        <dt>合同编号</dt>
        <dd :class="{ missing: !result.card.contract_no }">{{ result.card.contract_no || '未识别' }}</dd>
        <dt>发货单位</dt>
        <dd>{{ result.card.supplier || '—' }}</dd>
        <dt>到货单位</dt>
        <dd>{{ result.card.consignee || '—' }}</dd>
        <dt>单据日期</dt>
        <dd>{{ result.card.doc_date || '—' }}</dd>
        <template v-if="result.card.remark">
          <dt>单据备注</dt>
          <dd>{{ result.card.remark }}</dd>
        </template>
      </dl>

      <table class="items">
        <thead>
          <tr>
            <th>识别物资</th>
            <th class="num">数量</th>
            <th class="num">金额（元）</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(it, idx) in result.card.items" :key="idx">
            <td>
              <div class="raw">{{ it.raw_name }} <span class="spec">{{ it.spec }}</span></div>
              <div v-if="it.material_code" class="mapped">→ {{ it.material_name }}（{{ it.material_code }}）</div>
              <div v-else class="mapped missing">未匹配到标准物料，应用后请在预览区选择</div>
            </td>
            <td class="num">{{ qty(it.quantity) }} {{ it.unit }}</td>
            <td class="num">{{ money(it.amount) }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="result.quota" class="quota">
        合同剩余可下金额 {{ money(result.quota.remaining_amount) }} 元，本次 {{ money(result.quota.current_amount) }} 元
      </div>
      <el-alert v-if="over" type="error" :title="over.message" show-icon :closable="false" class="tip" />
      <div v-if="errors.length" class="todo">
        应用后还需补充：{{ errors.map((e) => e.message).join('；') }}
      </div>

      <div class="actions">
        <el-button @click="reset">重新上传</el-button>
        <el-button type="primary" :loading="store.saving" @click="apply">应用为草稿</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.image-panel {
  height: 100%;
  box-sizing: border-box;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.drop {
  border: 1px dashed #b8c4d6;
  border-radius: 6px;
  background: #f6f8fb;
  padding: 28px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  cursor: pointer;
  text-align: center;
  transition: border-color 0.15s, background 0.15s;
  &:hover,
  &.dragging {
    border-color: var(--el-color-primary);
    background: var(--el-color-primary-light-9);
  }
  &.compact {
    padding: 10px 12px;
    justify-content: flex-start;
    text-align: left;
  }
}
.thumb {
  width: 96px;
  height: 68px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid #dde3ec;
  flex-shrink: 0;
}
.drop-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  strong {
    font-size: 14px;
    color: var(--el-color-primary);
  }
  span {
    font-size: 12px;
    color: var(--app-text-secondary);
  }
  .file {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}
.state {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--app-text-secondary);
  padding: 4px 2px;
}
.card {
  border: 1px solid #dde3ec;
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  .title {
    font-weight: 600;
    margin-right: auto;
  }
}
.fields {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 6px 10px;
  margin: 0;
  font-size: 13px;
  dt {
    color: var(--app-text-secondary);
  }
  dd {
    margin: 0;
    word-break: break-all;
  }
}
.missing {
  color: var(--app-pending);
}
.items {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  th {
    text-align: left;
    font-weight: 600;
    background: #f1f4f8;
    padding: 6px 8px;
  }
  td {
    padding: 8px;
    border-bottom: 1px solid #edf0f4;
    vertical-align: top;
  }
  .num {
    text-align: right;
    white-space: nowrap;
  }
  .spec {
    color: var(--app-text-secondary);
  }
  .mapped {
    margin-top: 3px;
    font-size: 12px;
    color: var(--el-color-success);
  }
}
.quota,
.todo {
  font-size: 12px;
  color: var(--app-text-secondary);
}
.todo {
  color: var(--app-pending);
}
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
