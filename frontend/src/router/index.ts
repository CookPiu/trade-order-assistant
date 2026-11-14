import { createRouter, createWebHistory } from 'vue-router'
import { setUnauthorizedHandler } from '@/api/http'
import { ROLE_HOME, useSessionStore } from '@/stores/session'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/Login.vue'), meta: { public: true } },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        { path: '', name: 'home', redirect: () => ({ name: 'trade-orders' }) },
        { path: 'trade/orders', name: 'trade-orders', component: () => import('@/views/TradeOrders.vue'), meta: { title: '商贸订单' } },
        { path: 'workbench', name: 'workbench', component: () => import('@/views/Workbench.vue'), meta: { title: '提单工作台' } },
        { path: 'batch', name: 'batch', component: () => import('@/views/Batch.vue'), meta: { title: '批量导入与数据中心' } },
        { path: 'admin', name: 'admin', component: () => import('@/views/Admin.vue'), meta: { title: '主数据与系统配置' } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (to.meta.public) return true
  if (!(await session.restore())) return { name: 'login', query: { redirect: to.fullPath } }
  const name = String(to.name ?? '')
  if (name === 'home' || !session.canAccess(name)) {
    // 无权访问时跳到角色默认页（FR-045）
    return { name: ROLE_HOME[session.user!.role] }
  }
  return true
})

setUnauthorizedHandler(() => {
  const session = useSessionStore()
  session.logout()
  router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
})

export default router
