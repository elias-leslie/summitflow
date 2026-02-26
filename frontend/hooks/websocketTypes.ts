// Shared types for WebSocket hooks

// Message types from backend
export type MessageType =
  | 'log'
  | 'progress'
  | 'model_change'
  | 'chat_message'
  | 'stop_signal'
  | 'connected'
  | 'error'

export interface WebSocketMessage {
  type: MessageType
  task_id: string
  data: Record<string, unknown>
  timestamp: string
  sequence: number
}

// Exponential backoff config
export const INITIAL_RECONNECT_DELAY = 1000
export const MAX_RECONNECT_DELAY = 30000
export const RECONNECT_MULTIPLIER = 2
