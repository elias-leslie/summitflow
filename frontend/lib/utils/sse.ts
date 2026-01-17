/**
 * SSE (Server-Sent Events) parsing utilities.
 */

export interface ParsedSSEEvent<T extends string = string> {
  type: T
  data: Record<string, unknown>
}

/**
 * Parse a single SSE event block into type and data.
 * @param eventBlock - Raw SSE event block (lines separated by \n)
 * @param defaultType - Default event type if none specified
 */
export function parseSSEEvent<T extends string = string>(
  eventBlock: string,
  defaultType: T,
): ParsedSSEEvent<T> | null {
  if (!eventBlock.trim()) return null

  const lines = eventBlock.split('\n')
  let eventType: T = defaultType
  let eventData: Record<string, unknown> = {}

  for (const line of lines) {
    if (line.startsWith('event: ')) {
      eventType = line.slice(7) as T
    } else if (line.startsWith('data: ')) {
      try {
        eventData = JSON.parse(line.slice(6))
      } catch {
        console.warn('Failed to parse SSE data:', line)
      }
    }
  }

  return { type: eventType, data: eventData }
}

/**
 * Process an SSE buffer and yield complete events.
 * Returns remaining buffer content (incomplete event).
 * @param buffer - Current buffer content
 * @param defaultType - Default event type if none specified
 */
export function* processSSEBuffer<T extends string = string>(
  buffer: string,
  defaultType: T,
): Generator<ParsedSSEEvent<T>, string> {
  const events = buffer.split('\n\n')
  const remaining = events.pop() || ''

  for (const eventBlock of events) {
    const parsed = parseSSEEvent<T>(eventBlock, defaultType)
    if (parsed) {
      yield parsed
    }
  }

  return remaining
}
