<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDraftStore } from '@/stores/draft'
import { ROLE_LABEL, ROLE_ROUTES, useSessionStore } from '@/stores/session'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()

const NAV: { name: string; label: string }[] = [
  { name: 'trade-orders', label: '商贸订单' },
  { name: 'workbench', label: '提单工作台' },
  { name: 'batch', label: '批量导入与数据中心' },
  { name: 'admin', label: '主数据与系统配置' },
]

const navItems = computed(() => {
  const role = session.user?.role
  return role ? NAV.filter((n) => ROLE_ROUTES[role].includes(n.name)) : []
})

function logout() {
  useDraftStore().reset()
  session.logout()
  router.replace({ name: 'login' })
}
</script>

<template>
  <div class="layout">
    <header class="header">
      <div class="brand">商贸业务系统</div>
      <nav class="nav">
        <router-link
          v-for="n in navItems"
          :key="n.name"
          :to="{ name: n.name }"
          class="nav-item"
          :class="{ active: route.name === n.name }"
        >
          {{ n.label }}
        </router-link>
      </nav>
      <div v-if="session.user" class="user">
        <span>{{ session.user.dept_name }} · {{ session.user.display_name }}（{{ ROLE_LABEL[session.user.role] }}）</span>
        <el-button link class="logout" @click="logout">退出</el-button>
      </div>
    </header>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>

<style scoped lang="scss">
.layout {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.header {
  height: 48px;
  flex: none;
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 16px;
  background: var(--app-header-bg);
  color: var(--app-header-fg);
}
.brand {
  font-weight: 600;
  font-size: 15px;
  white-space: nowrap;
}
.nav {
  display: flex;
  height: 100%;
  overflow-x: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  padding: 0 14px;
  color: rgba(255, 255, 255, 0.78);
  text-decoration: none;
  white-space: nowrap;
  border-bottom: 3px solid transparent;
  &:hover {
    color: #fff;
  }
  &.active {
    color: #fff;
    border-bottom-color: #8fb4e6;
  }
}
.user {
  margin-left: auto;
  white-space: nowrap;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.85);
}
.logout {
  color: #fff;
  margin-left: 8px;
}
.main {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
</style>
