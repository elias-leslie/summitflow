import { SummitFlowOverlay } from './overlay'
import type {
  AnnotationDraft,
  BackgroundToContentMessage,
  CollabAnnotation,
  CompactPageState,
  ContentToBackgroundMessage,
  ExtensionCommandResponse,
} from './protocol'

class ContentBridge {
  private readonly overlay: SummitFlowOverlay
  private sensitiveMode = true
  private annotations: CollabAnnotation[] = []
  private pageStateTimer: number | null = null
  private destroyed = false

  constructor() {
    this.overlay = new SummitFlowOverlay({
      onAnnotationDraft: (draft) => this.sendAnnotationDraft(draft),
      onPointer: (anchor) => this.send({ type: 'summitflow.pointer', anchor }),
    })
    this.overlay.setSensitiveMode(this.sensitiveMode)
    this.installLocationHooks()
    window.addEventListener('scroll', this.schedulePageState, { passive: true })
    window.addEventListener('resize', this.schedulePageState, { passive: true })
    window.addEventListener('summitflow-location-change', this.schedulePageState)
    document.addEventListener('visibilitychange', this.schedulePageState)
    this.schedulePageState()
  }

  handleMessage(message: BackgroundToContentMessage): void {
    if (this.destroyed) return
    if (message.type === 'summitflow.configure') {
      this.sensitiveMode = message.config.sensitiveMode
      this.overlay.setSensitiveMode(this.sensitiveMode)
      this.schedulePageState()
      return
    }
    if (message.type === 'summitflow.render_annotations') {
      this.annotations = message.annotations
      this.overlay.renderAnnotations(this.annotations)
      return
    }
    if (message.type === 'summitflow.set_tool') {
      this.overlay.setTool(message.config.tool)
      return
    }
    if (message.type === 'summitflow.destroy') {
      this.destroy()
    }
  }

  private readonly schedulePageState = (): void => {
    if (this.destroyed) return
    this.overlay.renderAnnotations(this.annotations)
    if (this.pageStateTimer !== null) return
    this.pageStateTimer = window.setTimeout(() => {
      this.pageStateTimer = null
      this.send({ type: 'summitflow.page_state', state: this.collectPageState() })
    }, 250)
  }

  private sendAnnotationDraft(draft: AnnotationDraft): void {
    this.sendWithNotice({ type: 'summitflow.annotation_draft', draft })
  }

  private collectPageState(): CompactPageState {
    const state: CompactPageState = {
      url: window.location.href,
      title: document.title,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      scroll_x: window.scrollX,
      scroll_y: window.scrollY,
    }
    if (!this.sensitiveMode) {
      state.dom_state_hash = hashCompactState([
        window.location.origin,
        window.location.pathname,
        document.readyState,
        String(document.body?.childElementCount ?? 0),
        String(document.links.length),
      ])
    }
    return state
  }

  private send(message: ContentToBackgroundMessage): void {
    try {
      chrome.runtime.sendMessage(message)
    } catch {
      // Extension context can disappear during reload.
    }
  }

  private sendWithNotice(message: ContentToBackgroundMessage): void {
    try {
      chrome.runtime.sendMessage(
        message,
        (response?: ExtensionCommandResponse) => {
          const error =
            chrome.runtime.lastError?.message ??
            (response?.ok === false
              ? response.error ?? 'Co-Browser request failed.'
              : null)
          if (error) {
            this.overlay.showNotice(error)
          }
        },
      )
    } catch {
      this.overlay.showNotice(
        'Co-Browser extension reloaded. Return to SummitFlow Design Review and click Pair.',
      )
    }
  }

  private installLocationHooks(): void {
    const notify = () => window.dispatchEvent(new Event('summitflow-location-change'))
    const originalPushState = history.pushState
    const originalReplaceState = history.replaceState
    history.pushState = function pushState(...args) {
      const result = originalPushState.apply(this, args)
      notify()
      return result
    }
    history.replaceState = function replaceState(...args) {
      const result = originalReplaceState.apply(this, args)
      notify()
      return result
    }
    window.addEventListener('popstate', notify)
  }

  private destroy(): void {
    this.destroyed = true
    window.removeEventListener('scroll', this.schedulePageState)
    window.removeEventListener('resize', this.schedulePageState)
    window.removeEventListener('summitflow-location-change', this.schedulePageState)
    document.removeEventListener('visibilitychange', this.schedulePageState)
    this.overlay.destroy()
  }
}

function isBackgroundMessage(message: unknown): message is BackgroundToContentMessage {
  return (
    typeof message === 'object' &&
    message !== null &&
    'type' in message &&
    typeof (message as { type?: unknown }).type === 'string' &&
    (message as { type: string }).type.startsWith('summitflow.')
  )
}

function hashCompactState(parts: string[]): string {
  let hash = 2166136261
  for (const part of parts.join('|')) {
    hash ^= part.charCodeAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

const pageWindow = window as typeof window & { __summitFlowCoBrowser?: ContentBridge }
if (!pageWindow.__summitFlowCoBrowser) {
  pageWindow.__summitFlowCoBrowser = new ContentBridge()
}

chrome.runtime.onMessage.addListener((message) => {
  if (isBackgroundMessage(message)) {
    pageWindow.__summitFlowCoBrowser?.handleMessage(message)
  }
})
