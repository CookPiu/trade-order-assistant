import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { http, tokenStore } from '@/api/http'

export type Role = 'operator' | 'approver' | 'admin'

export interface CurrentUser {
  id: number
  username: string
  display_name: string
  role: Role
  dept_id: number
  dept_name: string
  dept_code: string
}

export const ROLE_LABEL: Record<Role, string> = {
  operator: '业务经办人',
  approver: '业务审批人',
  admin: '系统管理员',
}

/** 各角色可访问的页面与默认页（FR-045） */
export const ROLE_ROUTES: Record<Role, string[]> = {
  operator: ['trade-orders', 'workbench', 'batch'],
  approver: ['trade-orders'],
  admin: ['admin'],
}

export const ROLE_HOME: Record<Role, string> = {
  operator: 'trade-orders',
  approver: 'trade-orders',
  admin: 'admin',
}

export const useSessionStore = defineStore('session', () => {
  const user = ref<CurrentUser | null>(null)
  const loggedIn = computed(() => !!user.value)

  async function login(username: string, password: string) {
    const { data } = await http.post('/auth/login', { username, password })
    tokenStore.set(data.token)
    user.value = data.user
  }

  /** 页面刷新后用本地 token 恢复登录态 */
  async function restore(): Promise<boolean> {
    if (user.value) return true
    if (!tokenStore.get()) return false
    try {
      const { data } = await http.get('/auth/me')
      user.value = data
      return true
    } catch {
      tokenStore.clear()
      return false
    }
  }

  function logout() {
    tokenStore.clear()
    user.value = null
  }

  function canAccess(routeName: string) {
    return !!user.value && ROLE_ROUTES[user.value.role].includes(routeName)
  }

  return { user, loggedIn, login, restore, logout, canAccess }
})
