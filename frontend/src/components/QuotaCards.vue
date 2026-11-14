<script setup lang="ts">
import { computed } from 'vue'
import { money, qty, type QuotaSummary } from '@/api/types'

const props = defineProps<{ quota: QuotaSummary | null }>()

const cards = computed(() => {
  const q = props.quota
  return [
    { label: '合同总金额', value: q ? money(q.total_amount) : '—', sub: q ? `总量 ${qty(q.total_qty)} ${q.unit}` : '' },
    { label: '累计已下金额', value: q ? money(q.used_amount) : '—', sub: q ? `已下 ${qty(q.used_qty)} ${q.unit}` : '' },
    {
      label: '本次占用金额',
      value: q ? money(q.current_amount) : '—',
      sub: q ? `本次 ${qty(q.current_qty)} ${q.unit}` : '',
      tone: q?.over_quota ? 'over' : '',
    },
    {
      label: '剩余可下额度',
      value: q ? money(q.remaining_amount) : '—',
      sub: q ? `剩余 ${qty(q.remaining_qty)} ${q.unit}` : '',
      tone: q?.over_quota ? 'over' : q?.low_quota ? 'warn' : '',
    },
  ]
})
</script>

<template>
  <div class="cards">
    <div v-for="c in cards" :key="c.label" class="card" :class="c.tone">
      <div class="label">{{ c.label }}</div>
      <div class="value">{{ c.value }}</div>
      <div class="sub">{{ c.sub }}</div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
@media (max-width: 900px) {
  .cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.card {
  border: 1px solid #e3e8ef;
  border-radius: 6px;
  padding: 10px 12px;
  background: #fafbfd;
  &.over {
    border-color: var(--app-over);
    background: var(--app-over-bg);
    .value {
      color: var(--app-over);
    }
  }
  &.warn {
    border-color: var(--app-warn);
    background: var(--app-warn-bg);
  }
}
.label {
  color: var(--app-text-secondary);
  font-size: 12px;
}
.value {
  font-size: 18px;
  font-weight: 600;
  margin: 4px 0 2px;
  font-variant-numeric: tabular-nums;
  color: #1d2733;
}
.sub {
  color: #8a94a2;
  font-size: 12px;
}
</style>
