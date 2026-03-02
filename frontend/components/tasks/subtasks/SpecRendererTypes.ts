// =============================================================================
// Type Detection for Step Specs
// =============================================================================

export type SpecType = 'api' | 'prompt' | 'file' | 'generic'

export interface SpecRecord {
  [key: string]: unknown
}

/** Check if a value looks like a file path */
export function looksLikeFilePath(value: unknown): boolean {
  if (typeof value !== 'string') return false
  // Starts with ~, /, ./, or has file extension
  return /^[~./]|^[A-Za-z]:[/\\]|\.\w+$/.test(value)
}

/** Detect spec type from keys and values */
export function detectSpecType(spec: SpecRecord): SpecType {
  const keys = Object.keys(spec).map((k) => k.toLowerCase())

  // File spec: has file-specific keys OR path that looks like a file path
  if (
    keys.some((k) =>
      [
        'file',
        'filepath',
        'file_path',
        'filename',
        'operation',
        'create',
        'modify',
        'delete',
      ].includes(k),
    ) ||
    (keys.includes('path') && looksLikeFilePath(spec.path || spec.Path))
  ) {
    return 'file'
  }

  // API spec: has endpoint, method, url, or api-related keys
  // Note: "path" alone is ambiguous, so require method or endpoint for API
  if (
    keys.some((k) => ['endpoint', 'method', 'url', 'api', 'route'].includes(k))
  ) {
    return 'api'
  }

  // Prompt spec: has prompt, template, or message-related keys
  if (
    keys.some((k) =>
      ['prompt', 'template', 'message', 'system', 'user', 'assistant'].includes(
        k,
      ),
    )
  ) {
    return 'prompt'
  }

  return 'generic'
}
