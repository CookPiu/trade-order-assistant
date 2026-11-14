<script setup lang="ts">
/** 悬浮球与悬浮窗（FR-040、FR-042）：与全屏工作台共用草稿 store，收起、切换全屏时状态不丢。 */
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ChatFlow from '@/components/InputPanels/ChatFlow.vue'
import DraftMiniCard from '@/components/DraftMiniCard.vue'
import { useDraftStore } from '@/stores/draft'

const OPEN_KEY = 'toa.widget-open'
const store = useDraftStore()
const route = useRoute()
const router = useRouter()

function readOpen() {
  try {
    return sessionStorage.getItem(OPEN_KEY) === '1'
  } catch {
    return false
  }
}

const open = ref(readOpen())

watch(open, (v) => {
  try {
    sessionStorage.setItem(OPEN_KEY, v ? '1' : '0')
  } catch {
    /* 存储不可用时只在本页有效 */
  }
})

onMounted(() => {
  // 从全屏工作台“切到悬浮窗”跳转过来时展开
  if (route.query.widget === 'open') {
    open.value = true
    const { widget: _w, ...rest } = route.query
    router.replace({ query: rest })
  }
})

function toFullscreen() {
  open.value = false
  router.push({ name: 'workbench' })
}
</script>

<template>
  <button v-if="!open" class="ball" type="button" aria-label="展开提单助手" @click="open = true">
    <span>提单</span>
    <i v-if="store.view && !store.submitted" class="dot" />
  </button>
  <div v-else class="widget" role="dialog" aria-label="提单助手">
    <header class="bar">
      <strong>提单助手</strong>
      <el-button link class="act" @click="toFullscreen">全屏</el-button>
      <el-button link class="act" @click="open = false">收起</el-button>
    </header>
    <div class="content">
      <DraftMiniCard class="card" @expand="toFullscreen" />
      <ChatFlow compact class="chat" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.ball {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 2000;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: none;
  cursor: pointer;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 6px 18px rgba(24, 59, 105, 0.35);
  transition: transform 0.15s;
  &:hover {
    transform: translateY(-2px);
  }
  .dot {
    position: absolute;
    top: 6px;
    right: 6px;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--el-color-warning);
    border: 2px solid #fff;
  }
}
.widget {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 2000;
  width: 400px;
  max-width: calc(100vw - 32px);
  height: 660px;
  max-height: calc(100vh - 72px);
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #d6dde8;
  border-radius: 8px;
  box-shadow: 0 12px 32px rgba(24, 39, 66, 0.22);
  overflow: hidden;
}
@media (max-width: 480px) {
  .widget {
    right: 16px;
    bottom: 16px;
  }
}
.bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 12px;
  height: 42px;
  background: var(--app-header-bg);
  color: #fff;
  strong {
    margin-right: auto;
    font-size: 14px;
  }
  .act {
    color: #fff;
  }
}
.content {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.card {
  flex: none;
  max-height: 46%;
  overflow-y: auto;
}
.chat {
  flex: 1;
  min-height: 0;
}
</style>
