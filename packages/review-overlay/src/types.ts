export interface ReviewOverlayAnchor {
  coordinate_space?: 'document_css_px'
  x: number
  y: number
  scroll_x: number
  scroll_y: number
  viewport_width: number
  viewport_height: number
  bbox?: {
    left?: number
    top?: number
    width?: number
    height?: number
  }
}

export interface RouteEvidenceItem {
  evidence_id: string
  project_id: string
  page_key: string
  page_url_snapshot: string | null
  comment: string
  selector: string | null
  anchor: ReviewOverlayAnchor
  created_by_kind: string
  created_by_display: string | null
  created_at: string | null
}

export interface ReviewOverlayConfig {
  projectId: string
  summitflowBaseUrl: string
  agentHubEmbedUrl: string
  getAuthHeaders: () => Promise<Record<string, string>> | Record<string, string>
  pageKey?: string
  resolvePageKey?: () => string
  pageUrlSnapshot?: string
  mountTarget?: HTMLElement
  overlayId?: string
}

export interface ReviewOverlayHandle {
  open: () => void
  close: () => void
  destroy: () => void
}
