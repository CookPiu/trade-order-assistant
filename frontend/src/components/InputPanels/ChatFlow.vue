<script setup lang="ts">
/** 消息气泡流、快捷操作与输入框。全屏工作台与悬浮窗共用。 */
import { nextTick, ref, watch } from 'vue'
import { useDraftStore } from '@/stores/draft'

const props = withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const store = useDraftStore()
const input = ref('')
const listEl = ref<HTMLElement>()

const quick = [
  { key: 'new_sales', label: '新建销售订单' },
  { key: 'new_purchase', label: '新建采购订单' },
  { key: 'continue', label: '继续上次' },
  { key: 'help', label: '使用帮助' },
] as const

async function scrollBottom() {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

watch(() => store.messages.length, scrollBottom, { immediate: true })
watch(() => store.busy, scrollBottom)

async function send() {
  const text = input.value
  if (!text.trim() || store.busy) return
  input.value = ''
  await store.send(text)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <div class="chat" :class="{ compact: props.compact }">
    <div class="quick">
      <el-check-tag
        v-for="q in quick"
        :key="q.key"
        class="quick-tag"
        :checked="false"
        :disabled="store.busy"
        @change="store.quick(q.key)"
      >
        {{ q.label }}
      </el-check-tag>
    </div>
    <div ref="listEl" class="list">
      <div v-if="!store.messages.length" class="empty">
        用一句话描述订单，例如：给中建八局科技城项目下 200 吨 HRB400E 螺纹钢，走 2026-WZ-089 合同，后天送到一号工地。
      </div>
      <div v-for="m in store.messages" :key="m.id" class="msg" :class="[m.role, { failed: m.failed }]">
        <div class="bubble">{{ m.text }}</div>
        <div class="time">{{ m.at }}</div>
      </div>
      <div v-if="store.busy" class="msg assistant">
        <div class="bubble typing">正在识别<span class="dots" /></div>
      </div>
    </div>
    <div class="composer">
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: props.compact ? 1 : 2, maxRows: 5 }"
        resize="none"
        :disabled="store.busy"
        placeholder="描述订单或补充信息，Enter 发送，Shift+Enter 换行"
        @keydown="onKeydown"
      />
      <el-button type="primary" :loading="store.busy" :disabled="!input.trim()" @click="send">发送</el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.quick {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid #edf0f4;
}
.quick-tag {
  font-weight: normal;
  font-size: 12px;
  padding: 4px 10px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}
.list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.empty {
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.7;
  padding: 12px;
  background: #f6f8fb;
  border-radius: 6px;
}
.msg {
  display: flex;
  flex-direction: column;
  max-width: 88%;
  &.user {
    align-self: flex-end;
    align-items: flex-end;
    .bubble {
      background: var(--el-color-primary);
      color: #fff;
    }
  }
  &.assistant {
    align-self: flex-start;
    .bubble {
      background: #f1f4f8;
    }
  }
  &.failed .bubble {
    background: var(--app-over-bg);
    color: var(--app-over);
  }
}
.bubble {
  padding: 8px 12px;
  border-radius: 8px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.time {
  font-size: 11px;
  color: #9aa3ae;
  margin-top: 2px;
}
.typing {
  color: var(--app-text-secondary);
}
.dots::after {
  content: '…';
  animation: blink 1.2s infinite;
}
@keyframes blink {
  50% {
    opacity: 0.2;
  }
}
.composer {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 10px 12px;
  border-top: 1px solid #edf0f4;
}
.compact {
  .quick {
    padding: 8px 10px;
  }
  .list {
    padding: 10px;
  }
}
</style>
