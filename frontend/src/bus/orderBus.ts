/**
 * 订单事件总线（FR-043）。消息按 postMessage 格式组织，目前在同一窗口内投递；
 * 以后把助手改成 iframe 嵌入第三方商贸系统时，只需把 target 换成父窗口。
 */
export const BUS_SOURCE = 'trade-order-assistant'

export interface OrderCreatedPayload {
  order_id: number
  order_no: string
  order_type: 'sales' | 'purchase'
  status: string
}

export interface BusMessage {
  source: typeof BUS_SOURCE
  type: 'order:created'
  payload: OrderCreatedPayload
}

export function emitOrderCreated(payload: OrderCreatedPayload) {
  const msg: BusMessage = { source: BUS_SOURCE, type: 'order:created', payload }
  window.postMessage(msg, window.location.origin)
}

/** 订阅订单创建事件，返回取消订阅函数 */
export function onOrderCreated(handler: (p: OrderCreatedPayload) => void): () => void {
  const listener = (e: MessageEvent) => {
    if (e.origin !== window.location.origin) return
    const msg = e.data as BusMessage | undefined
    if (msg?.source === BUS_SOURCE && msg.type === 'order:created') handler(msg.payload)
  }
  window.addEventListener('message', listener)
  return () => window.removeEventListener('message', listener)
}
