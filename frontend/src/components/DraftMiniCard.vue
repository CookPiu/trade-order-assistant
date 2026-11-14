<script setup lang="ts">
/** 悬浮窗精简草稿卡片（FR-044、D-017）：关键字段、额度、超额与缺失提示，卡片上一键提单。 */
import { computed } from 'vue'
import { money, ORDER_STATUS_LABEL, ORDER_TYPE_LABEL, qty } from '@/api/types'
import SubmitBar from '@/components/SubmitBar.vue'
import { useDraftStore } from '@/stores/draft'

const emit = defineEmits<{ (e: 'expand'): void }>()
const store = useDraftStore()
const view = computed(() => store.view)
const d = computed(() => view.value?.data)
const errors = computed(() => view.value?.issues.filter((i) => i.level === 'error') ?? [])
const over = computed(() => view.value?.issues.find((i) => i.level === 'over') ?? null)
const warns = computed(() => view.value?.issues.filter((i) => i.level === 'warning') ?? [])

const capsule = computed(() => {
  const v = view.value
  if (!v) return null
  if (v.status === 'submitted') {
    const s = v.order_status ?? 'submitted'
    return { text: ORDER_STATUS_LABEL[s] ?? '已提交', type: s === 'pending_special' ? 'warning' : 'success' }
  }
  if (v.status === 'pending_confirm') return { text: '待确认', type: 'danger' }
  return { text: '草稿未提交', type: 'primary' }
})
</script>

<template>
  <div v-if="view && d" class="mini">
    <div class="top">
      <el-tag v-if="capsule" :type="capsule.type as any" size="small" effect="dark">{{ capsule.text }}</el-tag>
      <span class="type">{{ ORDER_TYPE_LABEL[d.order_type] }}</span>
      <el-button link type="primary" size="small" class="expand" @click="emit('expand')">全屏编辑</el-button>
    </div>
    <dl class="kv">
      <dt>合同号</dt>
      <dd :class="{ miss: !d.contract_no }">{{ d.contract_no || '待补充' }}</dd>
      <dt>签约单位</dt>
      <dd>{{ d.party_name || '—' }}</dd>
      <dt>物资</dt>
      <dd>
        <template v-if="d.items.length">
          <div v-for="(it, i) in d.items" :key="i">
            {{ it.material_name || it.raw_name || '未识别物资' }} {{ it.spec }} {{ qty(it.quantity) }} {{ it.unit }}
          </div>
        </template>
        <span v-else class="miss">待补充</span>
      </dd>
      <dt>交期</dt>
      <dd :class="{ miss: !d.delivery_date }">{{ d.delivery_date || '待补充' }}</dd>
      <dt>本次金额</dt>
      <dd class="num" :class="{ over: !!over }">{{ view.quota ? money(view.quota.current_amount) : '—' }}</dd>
      <dt>剩余可下</dt>
      <dd class="num" :class="{ over: !!over }">{{ view.quota ? money(view.quota.remaining_amount) : '—' }}</dd>
    </dl>
    <div v-if="view.order_status === 'returned' && !store.submitted" class="alert warn-alert">
      退回修改 {{ view.order_no }}{{ view.approval_comment ? `：${view.approval_comment}` : '' }}
    </div>
    <div v-if="over && !store.submitted" class="alert over-alert">超额：{{ over.message }}</div>
    <div v-if="errors.length && !store.submitted" class="alert miss-alert">
      待确认：{{ errors.map((e) => e.message).join('；') }}
    </div>
    <div v-if="warns.length && !store.submitted" class="alert warn-alert">提醒：{{ warns.map((w) => w.message).join('；') }}</div>
    <SubmitBar compact />
  </div>
</template>

<style scoped lang="scss">
.mini {
  border-bottom: 1px solid #e3e8ef;
  background: #fbfcfe;
}
.top {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 0;
  .type {
    font-size: 12px;
    color: var(--app-text-secondary);
  }
  .expand {
    margin-left: auto;
  }
}
.kv {
  display: grid;
  grid-template-columns: 60px 1fr;
  gap: 3px 8px;
  margin: 6px 12px 4px;
  font-size: 12px;
  dt {
    color: var(--app-text-secondary);
  }
  dd {
    margin: 0;
    min-width: 0;
    word-break: break-all;
  }
}
.miss {
  color: var(--app-pending);
}
.over {
  color: var(--app-over);
  font-weight: 600;
}
.alert {
  margin: 4px 12px;
  padding: 5px 8px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
}
.over-alert {
  background: var(--app-over-bg);
  color: var(--app-over);
}
.miss-alert {
  background: var(--app-pending-bg);
  color: var(--app-pending);
}
.warn-alert {
  background: var(--app-warn-bg);
  color: var(--app-warn-dark, #a16e0e);
}
.mini :deep(.bar) {
  background: transparent;
  border-top: none;
}
</style>
