'use client'

import {
  FileEdit,
  FileMinus,
  FilePlus,
  FileText,
  Globe,
  MessageSquareQuote,
} from 'lucide-react'

// =============================================================================
// Type Detection for Step Specs
// =============================================================================

export type SpecType = 'api' | 'prompt' | 'file' | 'generic'

export interface SpecRecord {
  [key: string]: unknown
}

/** Check if a value looks like a file path */
function looksLikeFilePath(value: unknown): boolean {
  if (typeof value !== 'string') return false
  // Starts with ~, /, ./, or has file extension
  return /^[~./]|^[A-Za-z]:[/\\]|\.\w+$/.test(value)
}

/** Detect spec type from keys and values */
function detectSpecType(spec: SpecRecord): SpecType {
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

// =============================================================================
// Type-Specific Spec Renderers
// =============================================================================

/** Method badge for API specs */
function MethodBadge({ method }: { method: string }) {
  const colors: Record<string, string> = {
    GET: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    POST: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    PUT: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    PATCH: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    DELETE: 'bg-red-500/20 text-red-400 border-red-500/30',
  }
  const colorClass =
    colors[method.toUpperCase()] ||
    'bg-slate-500/20 text-slate-400 border-slate-500/30'

  return (
    <span
      className={`px-1.5 py-0.5 text-2xs font-mono font-semibold rounded border ${colorClass}`}
    >
      {method.toUpperCase()}
    </span>
  )
}

/** API spec renderer with method badge and endpoint */
function ApiSpecRenderer({ spec }: { spec: SpecRecord }) {
  const method =
    (spec.method as string) || (spec.http_method as string) || 'GET'
  const endpoint =
    (spec.endpoint as string) ||
    (spec.path as string) ||
    (spec.url as string) ||
    (spec.route as string) ||
    ''

  // Extract other fields for additional info
  const otherFields = Object.entries(spec).filter(
    ([key]) =>
      !['method', 'http_method', 'endpoint', 'path', 'url', 'route'].includes(
        key.toLowerCase(),
      ),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 font-mono">
        <Globe className="w-3.5 h-3.5 text-blue-400" />
        <MethodBadge method={method} />
        <code className="text-xs text-slate-200 bg-slate-800/60 px-2 py-0.5 rounded">
          {endpoint || '(no endpoint)'}
        </code>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string'
                  ? value
                  : JSON.stringify(value, null, 2)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Highlight template variables in text ({{var}} or {var} patterns) */
function HighlightTemplateVars({ text }: { text: string }) {
  // Match both {{var}} and {var} patterns
  const parts = text.split(/(\{\{?\w+\}?\})/g)

  return (
    <>
      {parts.map((part, i) => {
        if (part.match(/^\{\{?\w+\}?\}$/)) {
          return (
            <span key={i} className="text-purple-400 font-semibold">
              {part}
            </span>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

/** Prompt spec renderer with quoted text and variable highlighting */
function PromptSpecRenderer({ spec }: { spec: SpecRecord }) {
  const promptFields = [
    'prompt',
    'template',
    'message',
    'system',
    'user',
    'assistant',
  ]
  const mainPrompt = promptFields
    .map((f) => spec[f])
    .find((v) => typeof v === 'string') as string | undefined

  const otherFields = Object.entries(spec).filter(
    ([key]) => !promptFields.includes(key.toLowerCase()),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <MessageSquareQuote className="w-3.5 h-3.5 text-purple-400 mt-0.5 flex-shrink-0" />
        <div className="flex-1">
          {mainPrompt ? (
            <blockquote className="text-xs text-slate-300 italic border-l-2 border-purple-500/40 pl-3 py-1 bg-purple-500/5 rounded-r">
              <HighlightTemplateVars text={mainPrompt} />
            </blockquote>
          ) : (
            <span className="text-2xs text-slate-500">(no prompt text)</span>
          )}
        </div>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string' ? (
                  <HighlightTemplateVars text={value} />
                ) : (
                  JSON.stringify(value)
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Operation badge for file specs */
function OperationBadge({ operation }: { operation: string }) {
  const op = operation.toLowerCase()
  const config: Record<
    string,
    { icon: typeof FileText; color: string; label: string }
  > = {
    create: {
      icon: FilePlus,
      color: 'bg-emerald-500/20 text-emerald-400',
      label: 'CREATE',
    },
    modify: {
      icon: FileEdit,
      color: 'bg-amber-500/20 text-amber-400',
      label: 'MODIFY',
    },
    update: {
      icon: FileEdit,
      color: 'bg-amber-500/20 text-amber-400',
      label: 'UPDATE',
    },
    delete: {
      icon: FileMinus,
      color: 'bg-red-500/20 text-red-400',
      label: 'DELETE',
    },
    read: {
      icon: FileText,
      color: 'bg-blue-500/20 text-blue-400',
      label: 'READ',
    },
  }
  const {
    icon: Icon,
    color,
    label,
  } = config[op] || {
    icon: FileText,
    color: 'bg-slate-500/20 text-slate-400',
    label: op.toUpperCase(),
  }

  return (
    <span
      className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-2xs font-semibold ${color}`}
    >
      <Icon className="w-3 h-3" />
      {label}
    </span>
  )
}

/** File spec renderer with clickable path and operation badge */
function FileSpecRenderer({ spec }: { spec: SpecRecord }) {
  const filePath =
    (spec.file as string) ||
    (spec.filepath as string) ||
    (spec.file_path as string) ||
    (spec.path as string) ||
    (spec.filename as string) ||
    ''
  const operation =
    (spec.operation as string) ||
    (spec.action as string) ||
    (spec.create
      ? 'create'
      : spec.modify
        ? 'modify'
        : spec.delete
          ? 'delete'
          : '')

  const otherFields = Object.entries(spec).filter(
    ([key]) =>
      ![
        'file',
        'filepath',
        'file_path',
        'path',
        'filename',
        'operation',
        'action',
        'create',
        'modify',
        'delete',
      ].includes(key.toLowerCase()),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <FileText className="w-3.5 h-3.5 text-orange-400" />
        {operation && <OperationBadge operation={operation} />}
        <code className="text-xs text-slate-200 bg-slate-800/60 px-2 py-0.5 rounded font-mono truncate max-w-xs">
          {filePath || '(no file path)'}
        </code>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string' ? value : JSON.stringify(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Generic spec renderer as key-value table */
function GenericSpecRenderer({ spec }: { spec: SpecRecord }) {
  const entries = Object.entries(spec)

  if (entries.length === 0) {
    return <span className="text-2xs text-slate-500">(empty spec)</span>
  }

  return (
    <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <span className="text-2xs text-slate-500 font-mono text-right">
            {key}:
          </span>
          <span className="text-2xs text-amber-300/80 break-all">
            {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Main spec renderer that delegates to type-specific renderer */
export function SpecRenderer({ spec }: { spec: SpecRecord }) {
  const specType = detectSpecType(spec)

  switch (specType) {
    case 'api':
      return <ApiSpecRenderer spec={spec} />
    case 'prompt':
      return <PromptSpecRenderer spec={spec} />
    case 'file':
      return <FileSpecRenderer spec={spec} />
    default:
      return <GenericSpecRenderer spec={spec} />
  }
}
