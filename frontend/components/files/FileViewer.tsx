'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Binary, Check, Copy, FileCode, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { cn, getErrorMessage } from '@/lib/utils'
import { FEEDBACK_TIMEOUT } from '@/lib/polling'
import { useFileContent } from '@/lib/hooks/useFileExplorer'
import { loadLanguageExtension } from './languageLoader'
import type { Extension } from '@codemirror/state'

// ============================================================================
// FileViewer Component
// ============================================================================

interface FileViewerProps {
  projectId: string
  filePath: string
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FileViewer({ projectId, filePath }: FileViewerProps) {
  const { data, isLoading, isError, error } = useFileContent(projectId, filePath)
  const [langExtension, setLangExtension] = useState<Extension | null>(null)
  const [CodeMirrorComponent, setCodeMirrorComponent] = useState<React.ComponentType<Record<string, unknown>> | null>(null)
  const [oneDarkTheme, setOneDarkTheme] = useState<Extension | null>(null)

  // Load CodeMirror dynamically (SSR-safe)
  useEffect(() => {
    let cancelled = false
    async function loadEditor() {
      const [cmModule, themeModule] = await Promise.all([
        import('@uiw/react-codemirror'),
        import('@codemirror/theme-one-dark'),
      ])
      if (!cancelled) {
        setCodeMirrorComponent(() => cmModule.default)
        setOneDarkTheme(themeModule.oneDark)
      }
    }
    loadEditor()
    return () => { cancelled = true }
  }, [])

  // Load language extension when file changes
  useEffect(() => {
    let cancelled = false
    if (data?.language) {
      loadLanguageExtension(data.language).then(ext => {
        if (!cancelled) setLangExtension(ext)
      })
    } else {
      setLangExtension(null)
    }
    return () => { cancelled = true }
  }, [data?.language])

  const extensions = useMemo(() => {
    const exts: Extension[] = []
    if (oneDarkTheme) exts.push(oneDarkTheme)
    if (langExtension) exts.push(langExtension)
    return exts
  }, [oneDarkTheme, langExtension])

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading file...
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-full items-center justify-center text-red-400">
        <AlertTriangle className="mr-2 h-5 w-5" />
        {error?.message ?? 'Failed to load file'}
      </div>
    )
  }

  if (!data) return null

  // Binary file state
  if (data.is_binary) {
    return (
      <div className="flex h-full flex-col">
        <FileInfoBar data={data} />
        <div className="flex flex-1 items-center justify-center text-slate-500">
          <div className="text-center">
            <Binary className="mx-auto mb-3 h-12 w-12 text-slate-700" />
            <p className="text-sm font-medium">{data.name}</p>
            <p className="mt-1 text-xs text-slate-600">
              Binary file ({formatSize(data.size)})
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <FileInfoBar data={data} />
      <div className="flex-1 overflow-auto">
        {CodeMirrorComponent ? (
          <CodeMirrorComponent
            value={data.content ?? ''}
            extensions={extensions}
            readOnly={true}
            editable={false}
            theme="dark"
            basicSetup={{
              lineNumbers: true,
              highlightActiveLineGutter: true,
              highlightActiveLine: true,
              foldGutter: true,
            }}
            style={{
              fontSize: '13px',
              height: '100%',
            }}
          />
        ) : (
          <pre className="p-4 text-sm text-slate-300 font-mono whitespace-pre-wrap">
            {data.content}
          </pre>
        )}
      </div>
    </div>
  )
}

// ============================================================================
// File Info Bar
// ============================================================================

interface FileInfoBarProps {
  data: {
    name: string
    lines: number
    size: number
    language: string | null
    truncated: boolean
    is_binary: boolean
    content: string | null
  }
}

function FileInfoBar({ data }: FileInfoBarProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    if (!data.content) return
    try {
      await navigator.clipboard.writeText(data.content)
      setCopied(true)
      setTimeout(() => setCopied(false), FEEDBACK_TIMEOUT)
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to copy file contents'))
    }
  }, [data.content])

  return (
    <div className="flex items-center gap-3 border-b border-slate-800 bg-slate-900/50 px-4 py-2 text-xs text-slate-400">
      <FileCode className="h-3.5 w-3.5 text-slate-500" />
      <span className="font-medium text-slate-300">{data.name}</span>
      {!data.is_binary && (
        <span>{data.lines} lines</span>
      )}
      <span>{formatSize(data.size)}</span>
      {data.language && (
        <span className={cn(
          'rounded-full px-2 py-0.5',
          'bg-emerald-500/10 text-emerald-400',
        )}>
          {data.language}
        </span>
      )}
      {data.truncated && (
        <span className="flex items-center gap-1 text-amber-400">
          <AlertTriangle className="h-3 w-3" />
          Truncated (file too large)
        </span>
      )}
      {/* Copy contents button */}
      {!data.is_binary && data.content && (
        <button
          type="button"
          className={cn(
            'ml-auto flex items-center gap-1.5 rounded px-2 py-0.5 transition-colors',
            'hover:bg-slate-800 hover:text-slate-200',
            copied && 'text-emerald-400',
          )}
          onClick={handleCopy}
          title="Copy file contents"
        >
          {copied ? (
            <>
              <Check className="h-3 w-3" />
              Copied
            </>
          ) : (
            <>
              <Copy className="h-3 w-3" />
              Copy
            </>
          )}
        </button>
      )}
    </div>
  )
}
