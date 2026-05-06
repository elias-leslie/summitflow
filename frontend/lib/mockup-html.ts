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
}): string {
  const parts = [
    `${mockup.name} (${mockup.mockup_id}${mockup.version ? ` v${mockup.version}` : ''})`,
  ]
  if (mockup.page_path) parts.push(`page ${mockup.page_path}`)
  if (mockup.description) parts.push(mockup.description)

  const notes = extractMockupAnnotations(mockup.content)
  if (notes.length) {
    parts.push(
      `notes: ${notes
        .map((note) => note.slice(0, 180))
        .join(' | ')
        .slice(0, 1200)}`,
    )
  }

  return parts.join(' - ').slice(0, 1600)
}
