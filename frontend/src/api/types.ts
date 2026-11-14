import type { ApiIssue } from './http'

export type OrderType = 'sales' | 'purchase'

export interface Candidate {
  code: string
  name: string
  spec: string
  unit: string
  score?: number
}

export interface DraftItem {
  raw_name: string
  material_code: string | null
  material_name: string
  spec: string
  unit: string
  quantity: string | number | null
  unit_price: string | number | null
  amount: string | number | null
  candidates: Candidate[]
}

export interface DraftData {
  order_type: OrderType
  contract_no: string | null
  party_name: string
  project_name: string
  address: string
  contact: string
  delivery_date: string | null
  remark: string
  biz_name: string
  purchase_mode: string
  biz_tag: string
  operator_name: string
  dept_name: string
  creator_name: string
  created_at: string
  items: DraftItem[]
}

export interface QuotaSummary {
  contract_no: string
  unit: string
  total_amount: string
  used_amount: string
  remaining_amount: string
  total_qty: string
  used_qty: string
  remaining_qty: string
  current_amount: string
  current_qty: string
  after_remaining_amount: string
  over_quota: boolean
  low_quota: boolean
}

export type DraftStatus = 'draft' | 'pending_confirm' | 'submitted'

export interface DraftView {
  id: string | null
  session_id: string | null
  status: DraftStatus
  data: DraftData
  issues: ApiIssue[]
  quota: QuotaSummary | null
  order_no: string | null
  order_status: string | null
  approval_comment: string
}

export interface ChatResponse {
  reply: string
  draft: DraftView | null
  failed: boolean
}

export interface RecognizeCardItem {
  raw_name: string
  spec: string
  quantity: string | null
  unit: string
  amount: string | null
  material_code: string | null
  material_name: string
}

export interface RecognizeResponse {
  image_hash: string
  card: {
    doc_type: string
    contract_no: string | null
    supplier: string
    consignee: string
    doc_date: string | null
    remark: string
    items: RecognizeCardItem[]
  }
  reply: string
  data: DraftData
  issues: ApiIssue[]
  quota: QuotaSummary | null
}

export interface OrderRow {
  id: number
  order_no: string
  order_type: OrderType
  contract_no: string
  party_name: string
  project_name: string
  total_amount: string
  status: string
  over_quota: boolean
  operator_name: string
  source: string
  submitted_at: string | null
}

export interface OrderDetail extends OrderRow {
  address: string
  contact: string
  dept_name: string
  biz_name: string
  purchase_mode: string
  biz_tag: string
  delivery_date: string
  total_qty: string
  remark: string
  approval_comment: string
  operator_id: number
  items: {
    seq: number
    material_code: string
    material_name: string
    spec: string
    quantity: string
    unit: string
    unit_price: string
    amount: string
  }[]
  quota: QuotaSummary | null
  audits: { action: string; username: string; created_at: string | null; detail: Record<string, unknown> }[]
}

export const AUDIT_LABEL: Record<string, string> = {
  submit: '提交订单',
  resubmit: '修改后重新提交',
  approve: '审核通过',
  return: '退回修改',
  reject: '驳回',
  login: '登录',
  chat: '对话提单',
  draft_save: '保存草稿',
  image_recognize: '图片识别',
  excel_import: 'Excel 导入',
  master_update: '主数据维护',
  param_update: '参数修改',
}

export function fmtTime(v: string | null | undefined): string {
  return v ? v.replace('T', ' ').slice(0, 19) : '—'
}

export interface ContractDetail {
  contract_no: string
  contract_type: OrderType
  party_name: string
  project_name: string
  expire_date: string
  items: { material_code: string; material_name: string; spec: string; unit: string; unit_price: string }[]
}

export const ORDER_TYPE_LABEL: Record<OrderType, string> = { sales: '销售订单', purchase: '采购订单' }

export const ORDER_STATUS_LABEL: Record<string, string> = {
  submitted: '已提交',
  pending_special: '待特批',
  approved: '已审核',
  returned: '退回',
  rejected: '驳回',
}

export function emptyDraft(order_type: OrderType = 'sales'): DraftData {
  return {
    order_type,
    contract_no: null,
    party_name: '',
    project_name: '',
    address: '',
    contact: '',
    delivery_date: null,
    remark: '',
    biz_name: '',
    purchase_mode: '',
    biz_tag: '',
    operator_name: '',
    dept_name: '',
    creator_name: '',
    created_at: '',
    items: [],
  }
}

export function money(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function qty(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 3 })
}
