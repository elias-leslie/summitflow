"use client"

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  Binary,
  Check,
  Copy,
  Download,
  FileCode,
  Loader2,
} from 'lucide-react'
import { toast } from 'sonner'
import type { Extension } from '@codemirror/state'
import { getFileDownloadUrl, type FileBrowserScope } from '@/lib/api/files'
import { useFileContent } from '@/lib/hooks/useFileExplorer'
import { FEEDBACK_TIMEOUT } from '@/lib/polling'
import { cn, getErrorMessage } from '@/lib/utils'
import { loadLanguageExtension } from './languageLoader'

interface FileViewerProps {
  scope: FileBrowserScope
  filePath: string
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function FileViewer({ scope, filePath }: FileViewerProps) {
  const { data, isLoading, isError, error } = useFileContent(scope, filePath)
  const [langExtension, setLangExtension] = useState<Extension | null>(null)
  const [CodeMirrorComponent, setCodeMirrorComponent] = useState<React.ComponentType<Record<string, unknown>> | null>(null)
  const [oneDarkTheme, setOneDarkTheme] = useState<Extension | null>(null)

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
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    if (data?.language) {
      loadLanguageExtension(data.language).then((extension) => {
        if (!cancelled) setLangExtension(extension)
      })
    } else {
      setLangExtension(null)
    }
    return () => {
      cancelled = true
    }
  }, [data?.language])

  const extensions = useMemo(() => {
    const items: Extension[] = []
    if (oneDarkTheme) items.push(oneDarkTheme)
    if (langExtension) items.push(langExtension)
    return items
  }, [langExtension, oneDarkTheme])

  const downloadUrl = useMemo(
    () => getFileDownloadUrl(scope, filePath),
    [filePath, scope],
  )

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

  if (data.is_binary) {
    return (
      <div className="flex h-full flex-col">
        <FileInfoBar data={data} downloadUrl={downloadUrl} />
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
      <FileInfoBar data={data} downloadUrl={downloadUrl} />
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
            style={{ fontSize: '13px', height: '100%' }}
          />
        ) : (
          <pre className="whitespace-pre-wrap p-4 font-mono text-sm text-slate-300">
            {data.content}
          </pre>
        )}
      </div>
    </div>
  )
}

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
  downloadUrl: string
}

function FileInfoBar({ data, downloadUrl }: FileInfoBarProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    if (!data.content) return
    try {
      await navigator.clipboard.writeText(data.content)
      setCopied(true)
      setTimeout(() => setCopied(false), FEEDBACK_TIMEOUT)
    } catch (error) {
      toast.error(getErrorMessage(error, 'Failed to copy file contents'))
    }
  }, [data.content])

  return (
    <div className="flex items-center gap-3 border-b border-slate-800 bg-slate-900/50 px-4 py-2 text-xs text-slate-400">
      <FileCode className="h-3.5 w-3.5 text-slate-500" />
      <span className="font-medium text-slate-300">{data.name}</span>
      {!data.is_binary ? <span>{data.lines} lines</span> : null}
      <span>{formatSize(data.size)}</span>
      {data.language ? (
        <span className={cn('rounded-full px-2 py-0.5', 'bg-emerald-500/10 text-emerald-400')}>
          {data.language}
        </span>
      ) : null}
      {data.truncated ? (
        <span className="flex items-center gap-1 text-amber-400">
          <AlertTriangle className="h-3 w-3" />
          Truncated (file too large)
        </span>
      ) : null}
      <div className="ml-auto flex items-center gap-2">
        <a
          href={downloadUrl}
          download={data.name}
          className="flex items-center gap-1.5 rounded px-2 py-0.5 transition-colors hover:bg-slate-800 hover:text-slate-200"
          title="Download file"
        >
          <Download className="h-3 w-3" />
          Download
        </a>
        {!data.is_binary && data.content ? (
          <button
            type="button"
            className={cn(
              'flex items-center gap-1.5 rounded px-2 py-0.5 transition-colors',
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
        ) : null}
      </div>
    </div>
  )
}
