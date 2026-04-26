export type CollabAnnotationKind = 'pin' | 'box' | 'highlight' | 'pointer' | 'comment'

export interface CollabAnchor {
  coordinate_space: 'viewport_css_px'
  x: number
  y: number
  width?: number
  height?: number
  viewport_width: number
  viewport_height: number
  scroll_x: number
  scroll_y: number
}

export interface CollabAnnotation {
  annotation_id: string
  kind: CollabAnnotationKind
  selector?: string | null
  anchor: CollabAnchor
  comment: string
  created_by_display?: string | null
}

export interface CompactPageState {
  url?: string
  title?: string
  viewport_width?: number
  viewport_height?: number
  scroll_x?: number
  scroll_y?: number
  dom_state_hash?: string
}

export interface ConnectorSessionConfig {
  apiBaseUrl: string
  sessionId: string
  pairingId: string
  connectorToken: string
  sensitiveMode: boolean
}

export interface OverlayToolConfig {
  tool: CollabAnnotationKind | 'idle'
}

export interface AnnotationDraft {
  kind: CollabAnnotationKind
  selector: string | null
  anchor: CollabAnchor
  comment: string
  pageUrlSnapshot: string
}

export type ContentToBackgroundMessage =
  | { type: 'summitflow.page_state'; state: CompactPageState }
  | { type: 'summitflow.annotation_draft'; draft: AnnotationDraft }
  | { type: 'summitflow.pointer'; anchor: CollabAnchor }

export type BackgroundToContentMessage =
  | { type: 'summitflow.configure'; config: Omit<ConnectorSessionConfig, 'connectorToken'> }
  | { type: 'summitflow.render_annotations'; annotations: CollabAnnotation[] }
  | { type: 'summitflow.set_tool'; config: OverlayToolConfig }
  | { type: 'summitflow.destroy' }

export type ExtensionCommandMessage =
  | { type: 'summitflow.configure_session'; config: ConnectorSessionConfig }
  | { type: 'summitflow.revoke_session' }
  | { type: 'summitflow.inject_overlay' }

export interface ExtensionCommandResponse {
  ok: boolean
  error?: string
}
