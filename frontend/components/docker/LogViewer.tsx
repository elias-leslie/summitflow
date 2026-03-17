'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { runtimeApi } from '@/lib/api/runtime'

interface LogViewerProps {
  service: string
  onClose: () => void
}

export function LogViewer({ service, onClose }: LogViewerProps) {
  const [streaming, setStreaming] = useState(false)
  const [streamLines, setStreamLines] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const { data: initialLogs } = useQuery({
    queryKey: ['runtime', 'logs', service],
    queryFn: () => runtimeApi.getLogs(service, 200),
    enabled: !streaming,
  })

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [initialLogs, streamLines])

  // SSE streaming
  useEffect(() => {
    if (!streaming) return

    const es = new EventSource(runtimeApi.logStreamUrl(service, 50))
    eventSourceRef.current = es

    es.onmessage = (event) => {
      setStreamLines((prev) => [...prev.slice(-1000), event.data])
    }

    es.onerror = () => {
      setStreaming(false)
      es.close()
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [streaming, service])

  const toggleStream = () => {
    if (streaming) {
      eventSourceRef.current?.close()
      setStreaming(false)
      setStreamLines([])
    } else {
      setStreaming(true)
    }
  }

  const lines = streaming
    ? streamLines
    : (initialLogs?.logs ?? '').split('\n').filter(Boolean)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-[90vw] max-w-4xl h-[70vh] bg-neutral-900 border border-neutral-700 rounded-xl flex flex-col shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-700">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-white">{service}</span>
            <span className="text-xs text-neutral-500">logs</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={toggleStream}
              className={`text-xs px-3 py-1 rounded transition-colors ${
                streaming
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-neutral-700 text-neutral-300 hover:bg-neutral-600'
              }`}
            >
              {streaming ? 'Stop streaming' : 'Stream'}
            </button>
            <button
              onClick={onClose}
              className="text-xs px-3 py-1 rounded bg-neutral-700 text-neutral-300 hover:bg-neutral-600 transition-colors"
            >
              Close
            </button>
          </div>
        </div>

        {/* Log content */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-auto p-4 font-mono text-xs leading-5 text-neutral-300"
        >
          {lines.length === 0 ? (
            <p className="text-neutral-500">No logs available</p>
          ) : (
            lines.map((line, i) => (
              <div key={i} className="hover:bg-neutral-800/50 px-1 -mx-1">
                {line}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
