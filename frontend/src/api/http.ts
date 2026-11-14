import axios, { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

export interface ApiIssue {
  field: string
  level: 'error' | 'over' | 'warning' | 'info'
  message: string
}

export interface ApiErrorBody {
  detail?: string | { msg: string }[]
  issues?: ApiIssue[] | null
}

const TOKEN_KEY = 'toa.token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export const http = axios.create({ baseURL: '/api', timeout: 90_000 })

http.interceptors.request.use((cfg) => {
  const t = tokenStore.get()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

export function errorMessage(e: unknown): string {
  const err = e as AxiosError<ApiErrorBody>
  const detail = err.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('；')
  if (err.code === 'ECONNABORTED') return '请求超时，请稍后重试'
  return err.message || '请求失败'
}

http.interceptors.response.use(
  (r) => r,
  (e: AxiosError<ApiErrorBody>) => {
    if (e.response?.status === 401 && !e.config?.url?.includes('/auth/login')) {
      // 登录过期：跳转登录，本地草稿保留在 sessionStorage
      tokenStore.clear()
      onUnauthorized?.()
      ElMessage.warning('登录已过期，请重新登录')
    }
    return Promise.reject(e)
  },
)
