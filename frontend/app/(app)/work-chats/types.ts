import type { StreamStatus } from '@agent-hub/chat-ui'
import type { Mockup } from '@/lib/api/mockups'

export type WorkChatLayout =
  | 'horizontal'
  | 'vertical'
  | 'main-side'
  | 'two-by-two'
  | 'wide-grid'

export type RoutingMode = 'auto' | 'direct'

export interface WorkChatPane {
  id: string
  chatKey: number
  sessionId: string | null
  agentSlug: string
  routingMode: RoutingMode
  projectId: string | null
  taskId: string | null
  taskTitle: string | null
  taskSummary: string | null
  feedbackId: string | null
  designId: string | null
  artifactSummary: string | null
  verifierEnabled: boolean
  verifierChatKey: number
  verifierSessionId: string | null
  verifierSplitPercent: number
  verifierLoopCount: number
  verifierLastBuilderSessionId: string | null
}

export interface WorkStartCommand {
  key: number
  prompt: string
}

export interface WorkChatController {
  sendMessage: (content: string) => void
  cancelStream: () => void
  sessionId: string | null
  status: StreamStatus
}

export interface ArtifactOption {
  value: string
  label: string
  kind: 'feedback' | 'design'
  id: string
  linkedTaskId?: string | null
  mockup?: Mockup
}

export interface MockupEditorTarget {
  projectId: string
  mockupId: string
  paneId: string
}
