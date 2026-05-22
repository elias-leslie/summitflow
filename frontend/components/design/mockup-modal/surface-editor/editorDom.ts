import type { CreateMockupRequest, Mockup } from '@/lib/api/mockups'
import {
  buildMockupElementPath,
  describeMockupElement,
  extractStructuredMockupAnnotations,
  type MockupAnnotation,
} from '@/lib/mockup-html'
import { EDITOR_STYLE_ID, HOVER_CLASS, SELECTED_CLASS } from './constants'
import type { SelectedElementState } from './types'

export const editorDom = {
  getEditableElements(doc: Document): HTMLElement[] {
    return Array.from(
      doc.body?.querySelectorAll<HTMLElement>('*') ?? [],
    ).filter(
      (element) =>
        element.tagName !== 'SCRIPT' &&
        element.tagName !== 'STYLE' &&
        !element.closest(`[data-sf-editor-ui="true"]`),
    )
  },

  selectedStateFromElement(element: HTMLElement): SelectedElementState {
    return {
      id: element.dataset.sfEditorId ?? '',
      path: buildMockupElementPath(element),
      tag: element.tagName.toLowerCase(),
      label: describeMockupElement(element),
      text: element.textContent?.trim().slice(0, 2000) ?? '',
      color: element.style.color,
      backgroundColor: element.style.backgroundColor,
      margin: element.style.margin,
      padding: element.style.padding,
      borderRadius: element.style.borderRadius,
    }
  },

  stripEditorState(doc: Document): string {
    doc.getElementById(EDITOR_STYLE_ID)?.remove()
    for (const element of Array.from(
      doc.querySelectorAll(`.${SELECTED_CLASS}, .${HOVER_CLASS}`),
    )) {
      element.classList.remove(SELECTED_CLASS, HOVER_CLASS)
      element.removeAttribute('contenteditable')
    }
    for (const element of Array.from(
      doc.querySelectorAll('[data-sf-editor-id]'),
    )) {
      element.removeAttribute('data-sf-editor-id')
    }
    return `<!doctype html>\n${doc.documentElement.outerHTML}`
  },

  buildVersionPayload(
    source: Mockup,
    content: string,
    summary: string,
    metadata: Record<string, unknown>,
  ): CreateMockupRequest {
    return {
      name: `${source.name} edited`,
      description: `Surface-edited version of ${source.name}`,
      mockup_type: source.mockup_type,
      content,
      task_id: source.task_id ?? undefined,
      page_path: source.page_path ?? undefined,
      parent_mockup_id: source.id,
      generator: 'surface-editor',
      generation_prompt: summary,
      metadata,
    }
  },

  getElementByEditorId(
    doc: Document | null,
    id: string | null,
  ): HTMLElement | null {
    if (!doc || !id) return null
    return doc.querySelector<HTMLElement>(
      `[data-sf-editor-id="${CSS.escape(id)}"]`,
    )
  },

  getElementsByEditorIds(doc: Document | null, ids: string[]): HTMLElement[] {
    if (!doc || !ids.length) return []
    return ids
      .map((id) => editorDom.getElementByEditorId(doc, id))
      .filter((element): element is HTMLElement => Boolean(element))
  },

  applySelection(doc: Document, ids: string[]): void {
    for (const item of Array.from(doc.querySelectorAll(`.${SELECTED_CLASS}`))) {
      item.classList.remove(SELECTED_CLASS)
    }
    for (const id of ids) {
      editorDom.getElementByEditorId(doc, id)?.classList.add(SELECTED_CLASS)
    }
  },

  toggleSelectedIds(
    currentIds: string[],
    id: string,
    additive: boolean,
  ): string[] {
    if (!additive || !currentIds.length) return [id]
    return currentIds.includes(id)
      ? currentIds.filter((item) => item !== id)
      : [...currentIds, id]
  },

  extractAnnotationsForDraft(
    annotations: MockupAnnotation[],
    draftContent: string,
    metadata: Mockup['metadata'],
  ): MockupAnnotation[] {
    return annotations.length
      ? annotations
      : extractStructuredMockupAnnotations(draftContent, metadata)
  },

  buildEditorSummary(
    mockup: Mockup,
    annotations: MockupAnnotation[],
    dirty: boolean,
    draftContent: string,
  ): string {
    const draftNotes = editorDom.extractAnnotationsForDraft(
      annotations,
      draftContent,
      mockup.metadata,
    )
    const lines = [
      `Surface-edited mockup ${mockup.mockup_id} v${mockup.version}.`,
    ]
    if (dirty) lines.push('User made direct surface edits.')
    if (draftNotes.length) {
      lines.push('Anchored notes:')
      for (const item of draftNotes) {
        lines.push(
          `- ${item.element_label ?? item.element_path ?? 'surface'}: ${item.note}`,
        )
      }
    }
    return lines.join('\n')
  },

  serializeDraftDocument(doc: Document | null, fallback: string): string {
    if (!doc?.documentElement) return fallback
    const clone = doc.cloneNode(true) as Document
    return editorDom.stripEditorState(clone)
  },

  buildEditorMetadata(
    mockup: Mockup,
    annotations: MockupAnnotation[],
    draftContent: string,
  ): Record<string, unknown> {
    return {
      ...(mockup.metadata ?? {}),
      annotations: editorDom.extractAnnotationsForDraft(
        annotations,
        draftContent,
        mockup.metadata,
      ),
      edited_by: 'surface-editor',
      source_mockup_id: mockup.mockup_id,
      source_version: mockup.version,
      summary_version: 1,
      token_policy: {
        default_context: 'compact',
        full_html: 'on_request',
      },
    }
  },
}
