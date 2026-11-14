/** 会话与草稿 store：悬浮窗与全屏工作台共用，写入 sessionStorage，刷新后恢复（FR-042）。 */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { errorMessage, http, type ApiErrorBody } from '@/api/http'
import type { ChatResponse, DraftData, DraftView, RecognizeResponse } from '@/api/types'
import type { AxiosError } from 'axios'
import { emitOrderCreated } from '@/bus/orderBus'

export interface ChatMessage {
  id: number
  role: 'user' | 'assistant'
  text: string
  failed?: boolean
  at: string
}

type QuickAction = 'new_sales' | 'new_purchase' | 'continue' | 'help'

const STORAGE_KEY = 'toa.draft-session'

function newSessionId() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function now() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

export const useDraftStore = defineStore('draft', () => {
  const sessionId = ref(newSessionId())
  const messages = ref<ChatMessage[]>([])
  const view = ref<DraftView | null>(null)
  const busy = ref(false)
  const saving = ref(false)
  const submitting = ref(false)
  let seq = 0

  const draftId = computed(() => view.value?.id ?? null)
  const submitted = computed(() => view.value?.status === 'submitted')

  // 恢复
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) {
      const s = JSON.parse(raw)
      sessionId.value = s.sessionId ?? sessionId.value
      messages.value = s.messages ?? []
      view.value = s.view ?? null
      seq = messages.value.reduce((m, x) => Math.max(m, x.id), 0)
    }
  } catch {
    /* 存储不可用时从空会话开始 */
  }

  watch(
    [sessionId, messages, view],
    () => {
      try {
        sessionStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ sessionId: sessionId.value, messages: messages.value, view: view.value }),
        )
      } catch {
        /* 忽略 */
      }
    },
    { deep: true },
  )

  function push(role: ChatMessage['role'], text: string, failed = false) {
    messages.value.push({ id: ++seq, role, text, failed, at: now() })
  }

  async function send(message: string) {
    const text = message.trim()
    if (!text || busy.value) return
    push('user', text)
    busy.value = true
    try {
      const { data } = await http.post<ChatResponse>('/chat', {
        session_id: sessionId.value,
        draft_id: submitted.value ? null : draftId.value,
        message: text,
      })
      push('assistant', data.reply, data.failed)
      if (data.draft) view.value = data.draft
    } catch (e) {
      push('assistant', `请求失败：${errorMessage(e)}`, true)
    } finally {
      busy.value = false
    }
  }

  async function quick(action: QuickAction) {
    if (busy.value) return
    const label = { new_sales: '新建销售订单', new_purchase: '新建采购订单', continue: '继续上次', help: '使用帮助' }[action]
    push('user', label)
    busy.value = true
    try {
      const { data } = await http.post<ChatResponse>('/chat', {
        session_id: sessionId.value,
        draft_id: draftId.value,
        action,
      })
      push('assistant', data.reply, data.failed)
      if (data.draft) view.value = data.draft
    } catch (e) {
      push('assistant', `请求失败：${errorMessage(e)}`, true)
    } finally {
      busy.value = false
    }
  }

  /** 预览区编辑后保存并重新校验（FR-031） */
  async function save(data: DraftData) {
    if (submitted.value) return
    saving.value = true
    try {
      const { data: v } = await http.post<DraftView>('/drafts', {
        session_id: sessionId.value,
        draft_id: draftId.value,
        data,
      })
      view.value = v
    } finally {
      saving.value = false
    }
  }

  async function submit(remark: string): Promise<{ ok: boolean; message: string }> {
    if (!draftId.value || submitting.value) return { ok: false, message: '' }
    submitting.value = true
    const wasReturned = view.value?.order_status === 'returned'
    try {
      const { data } = await http.post(`/drafts/${draftId.value}/submit`, { remark })
      const { data: v } = await http.get<DraftView>(`/drafts/${draftId.value}`)
      view.value = v
      const label = data.status === 'pending_special' ? '，超额订单已转待特批' : ''
      const head = wasReturned ? '已沿用原单号重新提交' : '提单成功'
      push('assistant', `${head}，订单编号 ${data.order_no}${label}。`)
      emitOrderCreated({ order_id: data.order_id, order_no: data.order_no, order_type: v.data.order_type, status: data.status })
      return { ok: true, message: data.order_no }
    } catch (e) {
      const body = (e as AxiosError<ApiErrorBody>).response?.data
      if (draftId.value) {
        try {
          const { data: v } = await http.get<DraftView>(`/drafts/${draftId.value}`)
          view.value = v
        } catch {
          /* 保留当前视图 */
        }
      }
      return { ok: false, message: typeof body?.detail === 'string' ? body.detail : errorMessage(e) }
    } finally {
      submitting.value = false
    }
  }

  /** 识别卡片一键应用：按识别结果新建草稿，并把识别过程写入对话流（FR-015） */
  async function applyRecognized(result: RecognizeResponse, filename: string) {
    saving.value = true
    try {
      const { data: v } = await http.post<DraftView>('/drafts', {
        session_id: sessionId.value,
        draft_id: null,
        data: result.data,
      })
      view.value = v
      push('user', `上传单据图片：${filename}`)
      push('assistant', result.reply)
    } finally {
      saving.value = false
    }
  }

  /** 载入被退回的订单继续修改，提交时沿用原单号（FR-038、FR-046） */
  async function loadReturned(orderId: number) {
    const { data: v } = await http.post<DraftView>(`/orders/${orderId}/edit`)
    view.value = v
    const comment = v.approval_comment ? `退回意见：${v.approval_comment}。` : ''
    push('assistant', `已载入退回订单 ${v.order_no}。${comment}可以继续对话或在右侧修改，提交后沿用原单号。`)
  }

  function setView(v: DraftView | null) {
    view.value = v
  }

  function reset() {
    sessionId.value = newSessionId()
    messages.value = []
    view.value = null
  }

  return { sessionId, messages, view, busy, saving, submitting, draftId, submitted, send, quick, save, submit, applyRecognized, loadReturned, setView, reset }
})
