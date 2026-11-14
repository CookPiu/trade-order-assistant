<template>
  <div class="excel">
    <p>多行订单请在“批量导入与数据中心”页上传 Excel，逐行校验后批量提交。</p>
    <router-link :to="{ name: 'batch' }">
      <el-button type="primary">前往批量导入</el-button>
    </router-link>
  </div>
</template>

<style scoped>
.excel {
  padding: 32px 20px;
  text-align: center;
  color: var(--app-text-secondary);
}
</style>
