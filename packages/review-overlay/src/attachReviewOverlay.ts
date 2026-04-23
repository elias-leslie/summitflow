import { shadowStyles } from './shadowStyles'
import type {
  ReviewOverlayAnchor,
  ReviewOverlayConfig,
  ReviewOverlayHandle,
  RouteEvidenceItem,
} from './types'

interface PendingCapture {
  anchor: ReviewOverlayAnchor
  selector: string | null
}

interface OverlayState {
  open: boolean
  authDisabled: boolean
  authMessage: string | null
  evidence: RouteEvidenceItem[]
  pendingCapture: PendingCapture | null
}

const overlayRegistry = new Map<string, ReviewOverlayController>()

function normalizePageKey(pageKey: string): string {
  const trimmed = pageKey.trim()
  if (!trimmed) {
    return '/'
  }

  let pathname = trimmed
  try {
    const parsed = new URL(trimmed, window.location.href)
    pathname = parsed.pathname || trimmed
  } catch {
    pathname = trimmed.split('?')[0]?.split('#')[0] ?? trimmed
  }

  if (pathname !== '/') {
    pathname = pathname.replace(/\/+$/, '')
  }

  return pathname || '/'
}

function buildApiUrl(baseUrl: string, path: string): string {
  if (!baseUrl) {
    return path
  }
  if (baseUrl.startsWith('http://') || baseUrl.startsWith('https://')) {
    return new URL(path, `${baseUrl.replace(/\/$/, '')}/`).toString()
  }
  return `${baseUrl.replace(/\/$/, '')}${path}`
}

function bestEffortSelector(target: Element | null): string | null {
  if (!(target instanceof HTMLElement)) {
    return null
  }

  const dataTestId = target.getAttribute('data-testid')
  if (dataTestId) {
    return `[data-testid="${dataTestId}"]`
  }

  const dataTest = target.getAttribute('data-test')
  if (dataTest) {
    return `[data-test="${dataTest}"]`
  }

  if (target.id) {
    return `#${CSS.escape(target.id)}`
  }

  const ariaLabel = target.getAttribute('aria-label')
  if (ariaLabel) {
    return `[aria-label="${ariaLabel}"]`
  }

  const role = target.getAttribute('role')
  if (role) {
    return `[role="${role}"]`
  }

  return null
}

function buildAnchor(target: Element | null): ReviewOverlayAnchor {
  const rect = target?.getBoundingClientRect()
  const left = rect?.left ?? 0
  const top = rect?.top ?? 0
  const width = rect?.width ?? 0
  const height = rect?.height ?? 0

  return {
    coordinate_space: 'document_css_px',
    x: window.scrollX + left,
    y: window.scrollY + top,
    scroll_x: window.scrollX,
    scroll_y: window.scrollY,
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    bbox:
      rect && width > 0 && height > 0
        ? {
            left: window.scrollX + left,
            top: window.scrollY + top,
            width,
            height,
          }
        : undefined,
  }
}

function appendIframeQueryParams(rawUrl: string, projectId: string): string {
  const url = new URL(rawUrl, window.location.href)
  if (!url.searchParams.get('project') && !url.searchParams.get('projectId')) {
    url.searchParams.set('projectId', projectId)
  }
  if (!url.searchParams.get('allowedOrigins')) {
    url.searchParams.set('allowedOrigins', window.location.origin)
  }
  return url.toString()
}

class ReviewOverlayController {
  private config: ReviewOverlayConfig
  private readonly host: HTMLDivElement
  private readonly shadowRoot: ShadowRoot
  private readonly shell: HTMLDivElement
  private readonly pageKeyValue: HTMLSpanElement
  private readonly warning: HTMLDivElement
  private readonly evidenceList: HTMLDivElement
  private readonly composer: HTMLDivElement
  private readonly commentInput: HTMLTextAreaElement
  private readonly pinButton: HTMLButtonElement
  private readonly refreshButton: HTMLButtonElement
  private readonly submitButton: HTMLButtonElement
  private readonly iframe: HTMLIFrameElement
  private readonly closeButton: HTMLButtonElement
  private pinCaptureListener: ((event: MouseEvent) => void) | null = null
  private dragStopListener: (() => void) | null = null
  private state: OverlayState = {
    open: true,
    authDisabled: false,
    authMessage: null,
    evidence: [],
    pendingCapture: null,
  }

  readonly handle: ReviewOverlayHandle

  constructor(config: ReviewOverlayConfig) {
    this.config = config
    this.host = document.createElement('div')
    this.host.dataset.reviewOverlayHost = this.overlayId
    this.host.style.position = 'relative'

    this.shadowRoot = this.host.attachShadow({ mode: 'open' })

    const style = document.createElement('style')
    style.textContent = shadowStyles
    this.shadowRoot.appendChild(style)

    this.shell = document.createElement('div')
    this.shell.className = 'review-overlay-shell'
    this.shell.dataset.open = 'true'

    const header = document.createElement('div')
    header.className = 'review-overlay-header'

    const title = document.createElement('div')
    title.className = 'review-overlay-title'
    const titleStrong = document.createElement('strong')
    titleStrong.textContent = 'Review Overlay'
    this.pageKeyValue = document.createElement('span')
    title.append(titleStrong, this.pageKeyValue)

    const headerActions = document.createElement('div')
    headerActions.className = 'review-overlay-header-actions'
    this.closeButton = document.createElement('button')
    this.closeButton.type = 'button'
    this.closeButton.className = 'review-overlay-button-secondary'
    this.closeButton.textContent = 'Close'
    headerActions.append(this.closeButton)
    header.append(title, headerActions)

    const body = document.createElement('div')
    body.className = 'review-overlay-body'

    const chatPane = document.createElement('div')
    chatPane.className = 'review-overlay-chat'
    this.iframe = document.createElement('iframe')
    this.iframe.title = 'Agent Hub review chat'
    chatPane.append(this.iframe)

    const sidebar = document.createElement('div')
    sidebar.className = 'review-overlay-sidebar'

    this.warning = document.createElement('div')
    this.warning.className = 'review-overlay-warning'
    this.warning.dataset.visible = 'false'

    const sidebarHeader = document.createElement('h3')
    sidebarHeader.textContent = 'Route Evidence'

    const sidebarActions = document.createElement('div')
    sidebarActions.className = 'review-overlay-sidebar-actions'
    this.refreshButton = document.createElement('button')
    this.refreshButton.type = 'button'
    this.refreshButton.className = 'review-overlay-button-secondary'
    this.refreshButton.textContent = 'Refresh'
    this.pinButton = document.createElement('button')
    this.pinButton.type = 'button'
    this.pinButton.className = 'review-overlay-button'
    this.pinButton.dataset.testid = 'review-overlay-pin-button'
    this.pinButton.setAttribute('data-testid', 'review-overlay-pin-button')
    this.pinButton.textContent = 'Pin comment'
    sidebarActions.append(this.refreshButton, this.pinButton)

    this.composer = document.createElement('div')
    this.composer.className = 'review-overlay-composer'
    this.composer.dataset.visible = 'false'
    const composerText = document.createElement('p')
    composerText.textContent = 'Click a host element, then leave a note for this page.'
    this.commentInput = document.createElement('textarea')
    this.commentInput.placeholder = 'Describe what is right or wrong on the page...'
    this.commentInput.setAttribute('data-testid', 'review-overlay-comment-input')
    const composerActions = document.createElement('div')
    composerActions.className = 'review-overlay-composer-actions'
    const cancelButton = document.createElement('button')
    cancelButton.type = 'button'
    cancelButton.className = 'review-overlay-button-secondary'
    cancelButton.textContent = 'Cancel'
    this.submitButton = document.createElement('button')
    this.submitButton.type = 'button'
    this.submitButton.className = 'review-overlay-button'
    this.submitButton.textContent = 'Save note'
    this.submitButton.setAttribute('data-testid', 'review-overlay-submit-button')
    composerActions.append(cancelButton, this.submitButton)
    this.composer.append(composerText, this.commentInput, composerActions)

    this.evidenceList = document.createElement('div')
    this.evidenceList.className = 'review-overlay-evidence-list'

    sidebar.append(
      sidebarHeader,
      this.warning,
      sidebarActions,
      this.composer,
      this.evidenceList,
    )

    body.append(chatPane, sidebar)
    this.shell.append(header, body)
    this.shadowRoot.append(this.shell)
    ;(config.mountTarget ?? document.body).appendChild(this.host)

    this.bindEvents({ header, cancelButton })
    this.updateConfig(config, false)
    this.render()
    void this.refreshEvidence()

    this.handle = {
      open: () => this.open(),
      close: () => this.close(),
      destroy: () => this.destroy(),
    }
  }

  get overlayId(): string {
    return this.config.overlayId?.trim() || 'review-overlay'
  }

  updateConfig(nextConfig: ReviewOverlayConfig, refresh = true): void {
    this.config = nextConfig
    this.host.dataset.reviewOverlayHost = this.overlayId
    this.iframe.src = appendIframeQueryParams(this.config.agentHubEmbedUrl, this.config.projectId)
    this.pageKeyValue.textContent = normalizePageKey(this.resolvePageKey())
    if (refresh) {
      void this.refreshEvidence()
    }
  }

  open(): void {
    this.state.open = true
    this.render()
  }

  close(): void {
    this.state.open = false
    this.render()
  }

  destroy(): void {
    this.removePinCaptureListener()
    this.dragStopListener?.()
    overlayRegistry.delete(this.overlayId)
    this.host.remove()
  }

  private bindEvents({
    header,
    cancelButton,
  }: {
    header: HTMLDivElement
    cancelButton: HTMLButtonElement
  }): void {
    this.closeButton.addEventListener('click', () => this.close())
    this.refreshButton.addEventListener('click', () => {
      void this.refreshEvidence()
    })
    this.pinButton.addEventListener('click', () => this.enterPinMode())
    cancelButton.addEventListener('click', () => this.clearPendingCapture())
    this.submitButton.addEventListener('click', () => {
      void this.submitPendingCapture()
    })
    this.commentInput.addEventListener('input', () => this.renderComposerState())

    header.addEventListener('pointerdown', (event: PointerEvent) => {
      if (event.button !== 0) {
        return
      }
      const startX = event.clientX
      const startY = event.clientY
      const currentLeft = this.shell.getBoundingClientRect().left
      const currentTop = this.shell.getBoundingClientRect().top
      this.shell.style.right = 'auto'
      this.shell.style.left = `${currentLeft}px`
      this.shell.style.top = `${currentTop}px`

      const move = (moveEvent: PointerEvent) => {
        this.shell.style.left = `${currentLeft + moveEvent.clientX - startX}px`
        this.shell.style.top = `${Math.max(8, currentTop + moveEvent.clientY - startY)}px`
      }
      const stop = () => {
        window.removeEventListener('pointermove', move)
        window.removeEventListener('pointerup', stop)
      }

      window.addEventListener('pointermove', move)
      window.addEventListener('pointerup', stop)
      this.dragStopListener = stop
    })
  }

  private clearPendingCapture(): void {
    this.removePinCaptureListener()
    this.state.pendingCapture = null
    this.commentInput.value = ''
    this.render()
  }

  private resolvePageKey(): string {
    const explicit = this.config.pageKey?.trim()
    if (explicit) {
      return explicit
    }
    if (this.config.resolvePageKey) {
      const resolved = this.config.resolvePageKey()?.trim()
      if (resolved) {
        return resolved
      }
    }
    return window.location.pathname || '/'
  }

  private resolvePageUrlSnapshot(): string {
    return this.config.pageUrlSnapshot?.trim() || window.location.href
  }

  private async requestJson<T>(path: string, init?: RequestInit): Promise<T | null> {
    const authHeaders = await Promise.resolve(this.config.getAuthHeaders())
    const headers: Record<string, string> = {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...(authHeaders ?? {}),
      ...((init?.headers as Record<string, string> | undefined) ?? {}),
    }

    const response = await fetch(buildApiUrl(this.config.summitflowBaseUrl, path), {
      ...init,
      headers,
    })

    if (response.status === 401 || response.status === 403) {
      this.state.authDisabled = true
      this.state.authMessage = 'Authentication required. Chat still works, but save and list are disabled until SummitFlow auth succeeds.'
      this.state.evidence = []
      this.render()
      return null
    }

    if (!response.ok) {
      throw new Error(`Review overlay request failed: ${response.status}`)
    }

    this.state.authDisabled = false
    this.state.authMessage = null
    return (await response.json()) as T
  }

  private async refreshEvidence(): Promise<void> {
    const pageKey = normalizePageKey(this.resolvePageKey())
    this.pageKeyValue.textContent = pageKey
    const items = await this.requestJson<RouteEvidenceItem[]>(
      `/api/projects/${encodeURIComponent(this.config.projectId)}/route-evidence?page_key=${encodeURIComponent(pageKey)}&limit=10`,
    )
    if (items) {
      this.state.evidence = items
      this.render()
    }
  }

  private enterPinMode(): void {
    if (this.state.authDisabled) {
      return
    }

    this.removePinCaptureListener()
    this.state.pendingCapture = null
    this.commentInput.value = ''
    this.open()
    this.render()

    this.pinCaptureListener = (event: MouseEvent) => {
      const targetNode = event.target instanceof Node ? event.target : null
      if (targetNode && this.host.contains(targetNode)) {
        return
      }

      event.preventDefault()
      event.stopPropagation()

      const targetElement = event.target instanceof Element ? event.target : null
      this.state.pendingCapture = {
        anchor: buildAnchor(targetElement),
        selector: bestEffortSelector(targetElement),
      }
      this.removePinCaptureListener()
      this.render()
      this.commentInput.focus()
    }

    document.addEventListener('click', this.pinCaptureListener, true)
  }

  private removePinCaptureListener(): void {
    if (!this.pinCaptureListener) {
      return
    }
    document.removeEventListener('click', this.pinCaptureListener, true)
    this.pinCaptureListener = null
  }

  private async submitPendingCapture(): Promise<void> {
    if (!this.state.pendingCapture || this.state.authDisabled) {
      return
    }

    const comment = this.commentInput.value.trim()
    if (!comment) {
      this.renderComposerState()
      return
    }

    const created = await this.requestJson<RouteEvidenceItem>(
      `/api/projects/${encodeURIComponent(this.config.projectId)}/route-evidence`,
      {
        method: 'POST',
        body: JSON.stringify({
          page_key: normalizePageKey(this.resolvePageKey()),
          page_url_snapshot: this.resolvePageUrlSnapshot(),
          comment,
          selector: this.state.pendingCapture.selector,
          anchor: this.state.pendingCapture.anchor,
        }),
      },
    )

    if (!created) {
      return
    }

    this.state.pendingCapture = null
    this.commentInput.value = ''
    await this.refreshEvidence()
  }

  private renderComposerState(): void {
    const hasPendingCapture = Boolean(this.state.pendingCapture)
    this.composer.dataset.visible = hasPendingCapture ? 'true' : 'false'
    this.submitButton.disabled = this.state.authDisabled || !hasPendingCapture || !this.commentInput.value.trim()
  }

  private renderEvidenceList(): void {
    this.evidenceList.innerHTML = ''

    if (this.state.evidence.length === 0) {
      const empty = document.createElement('div')
      empty.className = 'review-overlay-empty'
      empty.textContent = this.state.authDisabled
        ? 'Route evidence is unavailable until SummitFlow authentication succeeds.'
        : 'No route evidence yet. Use Pin comment to capture feedback for this page.'
      this.evidenceList.append(empty)
      return
    }

    for (const item of this.state.evidence) {
      const wrapper = document.createElement('div')
      wrapper.className = 'review-overlay-evidence-item'
      const meta = document.createElement('strong')
      meta.textContent = item.created_by_display
        ? `${item.created_by_display}${item.created_at ? ` · ${item.created_at}` : ''}`
        : item.created_at || 'Saved evidence'
      const comment = document.createElement('p')
      comment.textContent = item.comment
      wrapper.append(meta, comment)
      this.evidenceList.append(wrapper)
    }
  }

  private render(): void {
    this.shell.dataset.open = this.state.open ? 'true' : 'false'
    this.warning.dataset.visible = this.state.authMessage ? 'true' : 'false'
    this.warning.textContent = this.state.authMessage ?? ''
    this.pageKeyValue.textContent = normalizePageKey(this.resolvePageKey())
    this.refreshButton.disabled = this.state.authDisabled
    this.pinButton.disabled = this.state.authDisabled
    this.renderComposerState()
    this.renderEvidenceList()
  }
}

export function attachReviewOverlay(config: ReviewOverlayConfig): ReviewOverlayHandle {
  const overlayId = config.overlayId?.trim() || 'review-overlay'
  const existing = overlayRegistry.get(overlayId)
  if (existing) {
    existing.updateConfig(config)
    existing.open()
    return existing.handle
  }

  const controller = new ReviewOverlayController(config)
  overlayRegistry.set(overlayId, controller)
  return controller.handle
}
