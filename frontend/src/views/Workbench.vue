<script setup lang="ts">
/** 全屏提单工作台（FR-041）：左侧多模态提单交互区，右侧订单草稿预览与核验区。 */
import { ref } from 'vue'
import ChatFlow from '@/components/InputPanels/ChatFlow.vue'
import ExcelPanel from '@/components/InputPanels/ExcelPanel.vue'
import ImagePanel from '@/components/InputPanels/ImagePanel.vue'
import DraftPreview from '@/components/DraftPreview.vue'

const panel = ref<'text' | 'image' | 'excel'>('text')
</script>

<template>
  <div class="workbench">
    <section class="left app-panel">
      <el-segmented
        v-model="panel"
        :options="[
          { label: '文本对话', value: 'text' },
          { label: '图片识别', value: 'image' },
          { label: 'Excel 导入', value: 'excel' },
        ]"
        block
        class="switch"
      />
      <div class="panel-body">
        <ChatFlow v-show="panel === 'text'" />
        <ImagePanel v-if="panel === 'image'" @applied="panel = 'text'" />
        <ExcelPanel v-if="panel === 'excel'" />
      </div>
    </section>
    <section class="right app-panel">
      <DraftPreview />
    </section>
  </div>
</template>

<style scoped lang="scss">
.workbench {
  height: 100%;
  box-sizing: border-box;
  padding: 12px;
  display: grid;
  grid-template-columns: minmax(340px, 2fr) minmax(0, 3fr);
  gap: 12px;
}
@media (max-width: 960px) {
  .workbench {
    grid-template-columns: 1fr;
    grid-auto-rows: minmax(480px, auto);
    height: auto;
  }
}
.left,
.right {
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.switch {
  margin: 10px 12px 0;
}
.panel-body {
  flex: 1;
  min-height: 0;
}
</style>
