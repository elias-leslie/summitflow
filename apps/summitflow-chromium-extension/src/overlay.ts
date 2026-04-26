import type {
  AnnotationDraft,
  CollabAnchor,
  CollabAnnotation,
  CollabAnnotationKind,
} from './protocol'

interface OverlayCallbacks {
  onAnnotationDraft: (draft: AnnotationDraft) => void
  onPointer: (anchor: CollabAnchor) => void
}

interface PointerStart {
  x: number
  y: number
  scrollX: number
  scrollY: number
  target: Element | null
}

const HOST_ID = 'summitflow-cobrowser-overlay'
const MIN_BOX_SIZE = 8

export class SummitFlowOverlay {
  private readonly callbacks: OverlayCallbacks
  private readonly host: HTMLDivElement
  private readonly shadow: ShadowRoot
  private readonly layer: HTMLDivElement
  private readonly annotationLayer: HTMLDivElement
  private readonly toolbar: HTMLDivElement
  private tool: CollabAnnotationKind | 'idle' = 'idle'
  private sensitiveMode = true
  private pointerStart: PointerStart | null = null
  private draftBox: HTMLDivElement | null = null
  private lastPointerAt = 0

  constructor(callbacks: OverlayCallbacks) {
    this.callbacks = callbacks
    const existing = document.getElementById(HOST_ID)
    if (existing) {
      existing.remove()
    }

    this.host = document.createElement('div')
    this.host.id = HOST_ID
    this.host.style.position = 'fixed'
    this.host.style.inset = '0'
    this.host.style.zIndex = '2147483647'
    this.host.style.pointerEvents = 'none'
    document.documentElement.append(this.host)

    this.shadow = this.host.attachShadow({ mode: 'closed' })
    const style = document.createElement('style')
    style.textContent = styles
    this.shadow.append(style)

    this.annotationLayer = document.createElement('div')
    this.annotationLayer.className = 'sf-annotation-layer'

    this.layer = document.createElement('div')
    this.layer.className = 'sf-capture-layer'
    this.layer.addEventListener('pointerdown', this.handlePointerDown)
    this.layer.addEventListener('pointermove', this.handlePointerMove)
    this.layer.addEventListener('pointerup', this.handlePointerUp)
    this.layer.addEventListener('pointercancel', this.clearDraft)

    this.toolbar = this.buildToolbar()
    this.shadow.append(this.annotationLayer, this.layer, this.toolbar)
    document.addEventListener('pointermove', this.handleDocumentPointerMove, { passive: true })
    this.renderToolbarState()
  }

  setSensitiveMode(value: boolean): void {
    this.sensitiveMode = value
    this.renderToolbarState()
  }

  setTool(tool: CollabAnnotationKind | 'idle'): void {
    this.tool = tool
    this.layer.dataset.active = tool === 'idle' ? 'false' : 'true'
    this.renderToolbarState()
  }

  renderAnnotations(annotations: CollabAnnotation[]): void {
    this.annotationLayer.replaceChildren()
    for (const annotation of annotations) {
      this.annotationLayer.append(this.buildAnnotationElement(annotation))
    }
  }

  destroy(): void {
    document.removeEventListener('pointermove', this.handleDocumentPointerMove)
    this.host.remove()
  }

  private buildToolbar(): HTMLDivElement {
    const toolbar = document.createElement('div')
    toolbar.className = 'sf-toolbar'

    const status = document.createElement('span')
    status.className = 'sf-status'
    status.dataset.status = 'sensitive'
    status.title = 'Sensitive mode'
    toolbar.append(status)

    const tools: Array<{ tool: CollabAnnotationKind | 'idle'; label: string; title: string }> = [
      { tool: 'idle', label: 'x', title: 'Pass through' },
      { tool: 'pin', label: '+', title: 'Pin' },
      { tool: 'box', label: '[]', title: 'Box' },
      { tool: 'highlight', label: 'HL', title: 'Highlight' },
      { tool: 'comment', label: '?', title: 'Comment' },
    ]
    for (const item of tools) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'sf-tool'
      button.dataset.tool = item.tool
      button.textContent = item.label
      button.title = item.title
      button.addEventListener('click', () => this.setTool(item.tool))
      toolbar.append(button)
    }
    return toolbar
  }

  private renderToolbarState(): void {
    this.toolbar.dataset.tool = this.tool
    const status = this.toolbar.querySelector<HTMLElement>('.sf-status')
    if (status) {
      status.dataset.status = this.sensitiveMode ? 'sensitive' : 'open'
      status.title = this.sensitiveMode ? 'Sensitive mode' : 'Capture enabled'
    }
    for (const button of this.toolbar.querySelectorAll<HTMLButtonElement>('.sf-tool')) {
      button.dataset.active = button.dataset.tool === this.tool ? 'true' : 'false'
    }
  }

  private buildAnnotationElement(annotation: CollabAnnotation): HTMLElement {
    const element = document.createElement('div')
    const box = annotation.kind === 'box' || annotation.kind === 'highlight'
    element.className = box ? 'sf-mark sf-mark-box' : 'sf-mark sf-mark-pin'
    element.dataset.kind = annotation.kind
    element.title = annotation.comment
    const rect = rectFromAnchor(annotation.anchor)
    element.style.left = `${rect.left}px`
    element.style.top = `${rect.top}px`
    if (box) {
      element.style.width = `${Math.max(MIN_BOX_SIZE, rect.width)}px`
      element.style.height = `${Math.max(MIN_BOX_SIZE, rect.height)}px`
    } else {
      element.textContent = annotation.kind === 'pointer' ? '*' : '+'
    }
    return element
  }

  private readonly handleDocumentPointerMove = (event: PointerEvent): void => {
    const now = performance.now()
    if (now - this.lastPointerAt < 120) return
    this.lastPointerAt = now
    this.callbacks.onPointer(anchorFromViewportPoint(event.clientX, event.clientY))
  }

  private readonly handlePointerDown = (event: PointerEvent): void => {
    if (this.tool === 'idle') return
    event.preventDefault()
    this.pointerStart = {
      x: event.clientX,
      y: event.clientY,
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      target: this.elementBelowOverlay(event.clientX, event.clientY),
    }
    this.layer.setPointerCapture(event.pointerId)
    if (this.tool === 'box' || this.tool === 'highlight') {
      this.draftBox = document.createElement('div')
      this.draftBox.className = 'sf-draft-box'
      this.layer.append(this.draftBox)
      this.updateDraftBox(event.clientX, event.clientY)
    }
  }

  private readonly handlePointerMove = (event: PointerEvent): void => {
    if (!this.pointerStart || !this.draftBox) return
    event.preventDefault()
    this.updateDraftBox(event.clientX, event.clientY)
  }

  private readonly handlePointerUp = (event: PointerEvent): void => {
    if (!this.pointerStart || this.tool === 'idle') return
    event.preventDefault()
    const start = this.pointerStart
    const anchor = anchorFromDrag(start, event.clientX, event.clientY)
    const selector = bestEffortSelector(start.target)
    const comment = window.prompt('Comment')?.trim()
    if (comment !== undefined) {
      this.callbacks.onAnnotationDraft({
        kind: this.tool,
        selector,
        anchor,
        comment: comment || 'Review mark',
        pageUrlSnapshot: window.location.href,
      })
    }
    this.clearDraft()
    this.layer.releasePointerCapture(event.pointerId)
  }

  private readonly clearDraft = (): void => {
    this.pointerStart = null
    this.draftBox?.remove()
    this.draftBox = null
  }

  private updateDraftBox(clientX: number, clientY: number): void {
    if (!this.pointerStart || !this.draftBox) return
    const left = Math.min(this.pointerStart.x, clientX)
    const top = Math.min(this.pointerStart.y, clientY)
    const width = Math.max(MIN_BOX_SIZE, Math.abs(clientX - this.pointerStart.x))
    const height = Math.max(MIN_BOX_SIZE, Math.abs(clientY - this.pointerStart.y))
    this.draftBox.style.left = `${left}px`
    this.draftBox.style.top = `${top}px`
    this.draftBox.style.width = `${width}px`
    this.draftBox.style.height = `${height}px`
  }

  private elementBelowOverlay(clientX: number, clientY: number): Element | null {
    const previousVisibility = this.host.style.visibility
    this.host.style.visibility = 'hidden'
    try {
      return document.elementFromPoint(clientX, clientY)
    } finally {
      this.host.style.visibility = previousVisibility
    }
  }
}

export function anchorFromViewportPoint(x: number, y: number): CollabAnchor {
  return {
    coordinate_space: 'viewport_css_px',
    x,
    y,
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    scroll_x: window.scrollX,
    scroll_y: window.scrollY,
  }
}

function anchorFromDrag(start: PointerStart, endX: number, endY: number): CollabAnchor {
  const left = Math.min(start.x, endX)
  const top = Math.min(start.y, endY)
  return {
    coordinate_space: 'viewport_css_px',
    x: left,
    y: top,
    width: Math.max(MIN_BOX_SIZE, Math.abs(endX - start.x)),
    height: Math.max(MIN_BOX_SIZE, Math.abs(endY - start.y)),
    viewport_width: window.innerWidth,
    viewport_height: window.innerHeight,
    scroll_x: start.scrollX,
    scroll_y: start.scrollY,
  }
}

function rectFromAnchor(anchor: CollabAnchor): {
  left: number
  top: number
  width: number
  height: number
} {
  return {
    left: anchor.scroll_x + anchor.x - window.scrollX,
    top: anchor.scroll_y + anchor.y - window.scrollY,
    width: anchor.width ?? MIN_BOX_SIZE,
    height: anchor.height ?? MIN_BOX_SIZE,
  }
}

function bestEffortSelector(target: Element | null): string | null {
  if (!(target instanceof HTMLElement)) return null
  const dataTestId = target.getAttribute('data-testid')
  if (dataTestId) return `[data-testid="${escapeSelector(dataTestId)}"]`
  const dataTest = target.getAttribute('data-test')
  if (dataTest) return `[data-test="${escapeSelector(dataTest)}"]`
  if (target.id) return `#${escapeSelector(target.id)}`
  const ariaLabel = target.getAttribute('aria-label')
  if (ariaLabel) return `[aria-label="${escapeSelector(ariaLabel)}"]`
  const role = target.getAttribute('role')
  if (role) return `[role="${escapeSelector(role)}"]`
  return null
}

function escapeSelector(value: string): string {
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
    return CSS.escape(value)
  }
  return value.replace(/["\\]/g, '\\$&')
}

const styles = `
:host {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.sf-annotation-layer,
.sf-capture-layer {
  position: fixed;
  inset: 0;
}
.sf-annotation-layer {
  pointer-events: none;
}
.sf-capture-layer {
  cursor: crosshair;
  pointer-events: none;
}
.sf-capture-layer[data-active="true"] {
  pointer-events: auto;
}
.sf-toolbar {
  align-items: center;
  background: rgba(12, 20, 31, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.32);
  border-radius: 8px;
  box-shadow: 0 12px 36px rgba(15, 23, 42, 0.28);
  display: flex;
  gap: 4px;
  padding: 6px;
  pointer-events: auto;
  position: fixed;
  right: 16px;
  top: 16px;
}
.sf-status {
  border-radius: 999px;
  display: inline-block;
  height: 10px;
  margin: 0 5px;
  width: 10px;
}
.sf-status[data-status="sensitive"] {
  background: #f97316;
}
.sf-status[data-status="open"] {
  background: #22c55e;
}
.sf-tool {
  background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.42);
  border-radius: 6px;
  color: #e2e8f0;
  cursor: pointer;
  font: 600 11px/1 ui-sans-serif, system-ui, sans-serif;
  height: 28px;
  min-width: 28px;
  padding: 0 7px;
}
.sf-tool:hover,
.sf-tool[data-active="true"] {
  background: #0f766e;
  border-color: #5eead4;
  color: white;
}
.sf-mark {
  box-sizing: border-box;
  position: fixed;
}
.sf-mark-box {
  background: rgba(45, 212, 191, 0.14);
  border: 2px solid #14b8a6;
  border-radius: 4px;
  box-shadow: 0 0 0 1px rgba(15, 23, 42, 0.3);
}
.sf-mark-box[data-kind="highlight"] {
  background: rgba(250, 204, 21, 0.24);
  border-color: #facc15;
}
.sf-mark-pin {
  align-items: center;
  background: #0f766e;
  border: 2px solid #ccfbf1;
  border-radius: 999px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.3);
  color: white;
  display: flex;
  font: 700 12px/1 ui-sans-serif, system-ui, sans-serif;
  height: 24px;
  justify-content: center;
  margin-left: -12px;
  margin-top: -12px;
  width: 24px;
}
.sf-draft-box {
  background: rgba(56, 189, 248, 0.12);
  border: 2px dashed #38bdf8;
  border-radius: 4px;
  box-sizing: border-box;
  position: fixed;
}
`
