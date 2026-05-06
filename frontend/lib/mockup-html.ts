export function isHtmlMockupContent(
  content: string | null | undefined,
): boolean {
  const trimmed = content?.trimStart() ?? ''
  return (
    trimmed.startsWith('<!') ||
    trimmed.startsWith('<html') ||
    trimmed.startsWith('<HTML')
  )
}

export interface MockupAnnotation {
  id?: string | null
  note: string
  element_path?: string | null
  element_label?: string | null
  rect?: Record<string, number> | null
  created_at?: string | null
  source?: string
}

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
}

function stripTags(value: string): string {
  return value
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function compactText(value: string, maxLength: number): string {
  const compact = value.replace(/\s+/g, ' ').trim()
  return compact.length > maxLength
    ? `${compact.slice(0, maxLength - 1).trim()}...`
    : compact
}

export function describeMockupElement(element: HTMLElement): string {
  const bits = [element.tagName.toLowerCase()]
  if (element.id) bits.push(`#${element.id}`)
  if (element.className && typeof element.className === 'string') {
    const classes = element.className
      .split(/\s+/)
      .filter((item) => item && !item.startsWith('sf-editor-'))
      .slice(0, 2)
    if (classes.length) bits.push(`.${classes.join('.')}`)
  }
  const text = element.textContent?.trim()
  if (text) bits.push(`"${compactText(text, 48)}"`)
  return bits.join('')
}

export function buildMockupElementPath(element: HTMLElement): string {
  const segments: string[] = []
  let current: HTMLElement | null = element
  while (
    current &&
    current.tagName !== 'HTML' &&
    current.tagName !== 'BODY' &&
    segments.length < 8
  ) {
    let segment = current.tagName.toLowerCase()
    if (current.id) {
      segment += `#${current.id}`
      segments.unshift(segment)
      break
    }
    const classNames =
      typeof current.className === 'string'
        ? current.className
            .split(/\s+/)
            .filter((item) => item && !item.startsWith('sf-editor-'))
            .slice(0, 2)
        : []
    if (classNames.length) segment += `.${classNames.join('.')}`
    const siblings = Array.from(current.parentElement?.children ?? []).filter(
      (item) => item.tagName === current?.tagName,
    )
    if (siblings.length > 1) {
      segment += `:nth-of-type(${siblings.indexOf(current) + 1})`
    }
    segments.unshift(segment)
    current = current.parentElement
  }
  return segments.join(' > ')
}

export function extractStructuredMockupAnnotations(
  content: string | null | undefined,
  metadata?: Record<string, unknown> | null,
): MockupAnnotation[] {
  const raw = metadata?.annotations
  if (Array.isArray(raw)) {
    return raw
      .filter(
        (item): item is Record<string, unknown> =>
          typeof item === 'object' && item !== null,
      )
      .map((item) => ({
        id: typeof item.id === 'string' ? item.id : null,
        note: typeof item.note === 'string' ? compactText(item.note, 500) : '',
        element_path:
          typeof item.element_path === 'string' ? item.element_path : null,
        element_label:
          typeof item.element_label === 'string' ? item.element_label : null,
        rect:
          typeof item.rect === 'object' && item.rect !== null
            ? (item.rect as Record<string, number>)
            : null,
        created_at:
          typeof item.created_at === 'string' ? item.created_at : null,
        source: 'metadata',
      }))
      .filter((item) => item.note)
      .slice(0, 20)
  }

  return extractMockupAnnotations(content).map((note) => ({
    note,
    source: 'html',
  }))
}

export function extractMockupAnnotations(
  content: string | null | undefined,
): string[] {
  if (!content) return []

  const notes = new Set<string>()
  const attrPattern = /data-sf-mock-note-text=(["'])(.*?)\1/gi
  let attrMatch = attrPattern.exec(content)
  while (attrMatch !== null) {
    const note = decodeHtmlEntities(attrMatch[2] ?? '').trim()
    if (note) notes.add(note)
    attrMatch = attrPattern.exec(content)
  }

  const textPattern =
    /<[^>]*class=(["'])[^"']*sf-mock-note[^"']*\1[^>]*>([\s\S]*?)<\/[^>]+>/gi
  let textMatch = textPattern.exec(content)
  while (textMatch !== null) {
    const note = decodeHtmlEntities(stripTags(textMatch[2] ?? ''))
    if (note) notes.add(note)
    textMatch = textPattern.exec(content)
  }

  return Array.from(notes).slice(0, 20)
}

export function summarizeMockupForWorkContext(mockup: {
  mockup_id: string
  name: string
  description?: string | null
  version?: number | null
  page_path?: string | null
  content?: string | null
  metadata?: Record<string, unknown> | null
}): string {
  const parts = [
    `${mockup.name} (${mockup.mockup_id}${mockup.version ? ` v${mockup.version}` : ''})`,
  ]
  if (mockup.page_path) parts.push(`page ${mockup.page_path}`)
  if (mockup.description) parts.push(mockup.description)

  const notes = extractStructuredMockupAnnotations(
    mockup.content,
    mockup.metadata,
  )
  if (notes.length) {
    parts.push(
      `notes: ${notes
        .map((note) =>
          compactText(
            `${note.element_label ?? note.element_path ?? 'surface'}: ${note.note}`,
            220,
          ),
        )
        .join(' | ')
        .slice(0, 1200)}`,
    )
  }

  return parts.join(' - ').slice(0, 1600)
}
