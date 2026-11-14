<script setup lang="ts">
/** 提单操作栏：保存草稿、一键提单；超额时必须填写备注；提交成功后锁定（FR-022、FR-032、FR-033）。 */
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { useDraftStore } from '@/stores/draft'

const props = defineProps<{ compact?: boolean }>()
const emit = defineEmits<{ (e: 'save'): void; (e: 'switch'): void }>()

const store = useDraftStore()
const remark = ref('')
const remarkError = ref('')

const view = computed(() => store.view)
const errors = computed(() => view.value?.issues.filter((i) => i.level === 'error') ?? [])
const over = computed(() => !!view.value?.quota?.over_quota)
const canSubmit = computed(
  () => !!view.value?.id && !store.submitted && errors.value.length === 0 && !store.busy && !store.saving,
)

watch(
  () => view.value?.id,
  () => {
    remark.value = view.value?.data.remark ?? ''
    remarkError.value = ''
  },
  { immediate: true },
)

async function submit() {
  if (over.value && !remark.value.trim()) {
    remarkError.value = '本次金额超出合同剩余可下金额，请填写备注说明后提交'
    return
  }
  remarkError.value = ''
  const r = await store.submit(remark.value.trim())
  if (r.ok) ElMessage.success(`提单成功：${r.message}`)
  else if (r.message) ElMessage.error(r.message)
}
</script>

<template>
  <div class="bar" :class="{ compact: props.compact }">
    <div v-if="over && !store.submitted" class="remark" :class="{ 'field-pending': !!remarkError }">
      <el-input v-model="remark" placeholder="超额提交必填：说明原因，如“项目追加采购，已与客户确认”" maxlength="200" />
      <div v-if="remarkError" class="field-reason error">{{ remarkError }}</div>
    </div>
    <div class="actions">
      <span v-if="store.submitted && view?.order_no" class="done">
        订单编号 <b>{{ view.order_no }}</b>
      </span>
      <span v-else-if="errors.length" class="hint">还有 {{ errors.length }} 项待确认</span>
      <span v-else-if="store.saving" class="hint">保存中…</span>
      <el-button v-if="!props.compact" @click="emit('switch')">切到悬浮窗</el-button>
      <el-button v-if="!props.compact" :disabled="!view?.id || store.submitted || store.saving" @click="emit('save')">
        保存草稿
      </el-button>
      <el-button
        type="primary"
        :loading="store.submitting"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ store.submitted ? '已提交' : '一键提单' }}
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.bar {
  border-top: 1px solid #e3e8ef;
  padding: 10px 14px;
  background: #fff;
}
.remark {
  margin-bottom: 8px;
}
.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
.hint {
  margin-right: auto;
  color: var(--app-pending);
  font-size: 12px;
}
.done {
  margin-right: auto;
  color: var(--el-color-success);
}
.compact {
  padding: 8px 10px;
}
</style>
