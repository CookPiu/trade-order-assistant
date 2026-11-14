<script setup lang="ts">
/** 主数据与系统配置页（FR-050、FR-051、FR-052）：合同台账、物料字典与别名、参数配置、审计日志四个页签。 */
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AuditTab from '@/components/admin/AuditTab.vue'
import ContractTab from '@/components/admin/ContractTab.vue'
import MaterialTab from '@/components/admin/MaterialTab.vue'
import ParamsTab from '@/components/admin/ParamsTab.vue'

const TABS = ['contracts', 'materials', 'params', 'audit'] as const
type Tab = (typeof TABS)[number]

const route = useRoute()
const router = useRouter()
const initial = route.query.tab as Tab
const tab = ref<Tab>(TABS.includes(initial) ? initial : 'contracts')
watch(tab, (t) => router.replace({ query: { ...route.query, tab: t } }))
</script>

<template>
  <div class="admin-page">
    <section class="app-panel">
      <header class="head">
        <h2>主数据与系统配置</h2>
        <span class="sub">修改保存后，提单、识别和导入从下一次请求起使用新数据</span>
      </header>
      <el-tabs v-model="tab">
        <el-tab-pane label="合同台账" name="contracts" lazy><ContractTab /></el-tab-pane>
        <el-tab-pane label="物料字典与别名" name="materials" lazy><MaterialTab /></el-tab-pane>
        <el-tab-pane label="参数配置" name="params" lazy><ParamsTab /></el-tab-pane>
        <el-tab-pane label="审计日志" name="audit" lazy><AuditTab /></el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>

<style scoped lang="scss">
.admin-page {
  padding: 12px;
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
  h2 {
    font-size: 15px;
    margin: 0;
  }
  .sub {
    font-size: 12px;
    color: var(--app-text-secondary);
  }
}
</style>
