'use client'

import { useDeferredValue, useState } from 'react'
import { Loader2, Search, Sparkles, X } from 'lucide-react'
import { Sheet, SheetBody, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import {
  useExplorerSymbolDetail,
  useExplorerSymbolSearch,
} from './hooks'

interface SymbolSearchPanelProps {
  projectId: string
}

const languageLabels: Record<string, string> = {
  python: 'Python',
  typescript: 'TypeScript',
  tsx: 'TSX',
}

export function SymbolSearchPanel({ projectId }: SymbolSearchPanelProps) {
  const [query, setQuery] = useState('')
  const [selectedSymbolId, setSelectedSymbolId] = useState<string | null>(null)
  const deferredQuery = useDeferredValue(query)
  const isSearching = query.trim() !== deferredQuery.trim()

  const searchQuery = useExplorerSymbolSearch(projectId, deferredQuery, {
    enabled: true,
    limit: 12,
  })
  const detailQuery = useExplorerSymbolDetail(projectId, selectedSymbolId, {
    contextLines: 4,
  })

  const results = searchQuery.data?.items ?? []
  const showEmpty =
    deferredQuery.trim().length >= 2 &&
    !searchQuery.isLoading &&
    !isSearching &&
    results.length === 0

  return (
    <>
      <div className="border-b border-slate-700/50 bg-slate-950/40">
        <div className="px-4 py-3">
          <div className="flex flex-col gap-3 rounded-xl border border-slate-700/60 bg-slate-900/70 p-3">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-300">
                <Sparkles className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-100">
                  Precision Code Search
                </p>
                <p className="text-xs text-slate-400">
                  Search indexed symbols and open exact source slices.
                </p>
              </div>
            </div>

            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Find functions, classes, hooks, or components"
                className="h-11 w-full rounded-lg border border-slate-700 bg-slate-950/70 pl-9 pr-10 text-sm text-slate-100 outline-none transition focus:border-cyan-400/60"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 transition hover:bg-slate-800 hover:text-slate-200"
                  aria-label="Clear code search"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>

            {query.trim().length < 2 ? (
              <p className="text-xs text-slate-500">
                Type at least 2 characters to search the indexed code graph.
              </p>
            ) : (
              <div className="rounded-lg border border-slate-800 bg-slate-950/60">
                {searchQuery.isLoading || isSearching ? (
                  <div className="flex items-center gap-2 px-3 py-4 text-sm text-slate-400">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Searching symbols...
                  </div>
                ) : null}

                {!searchQuery.isLoading && !isSearching && results.length > 0 ? (
                  <div className="divide-y divide-slate-800">
                    {results.map((symbol) => (
                      <button
                        key={symbol.symbol_id}
                        type="button"
                        onClick={() => setSelectedSymbolId(symbol.symbol_id)}
                        className="flex w-full items-start gap-3 px-3 py-3 text-left transition hover:bg-slate-900/80"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate text-sm font-medium text-slate-100">
                              {symbol.qualified_name}
                            </span>
                            <span className="rounded bg-cyan-500/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-cyan-300">
                              {symbol.kind}
                            </span>
                            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
                              {languageLabels[symbol.language] ?? symbol.language}
                            </span>
                          </div>
                          <p className="mt-1 truncate font-mono text-xs text-slate-400">
                            {symbol.signature}
                          </p>
                          <p className="mt-1 truncate text-xs text-slate-500">
                            {symbol.file_path}:{symbol.start_line}
                          </p>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : null}

                {showEmpty ? (
                  <div className="px-3 py-4 text-sm text-slate-500">
                    No indexed symbols matched.
                  </div>
                ) : null}

                {searchQuery.isError ? (
                  <div className="px-3 py-4 text-sm text-red-300">
                    Symbol search failed.
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </div>

      <Sheet
        open={Boolean(selectedSymbolId)}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedSymbolId(null)
          }
        }}
      >
        <SheetContent side="right" className="max-w-3xl border-l border-slate-700 bg-slate-950">
          <SheetHeader>
            <SheetClose onClose={() => setSelectedSymbolId(null)} />
            <SheetTitle>
              {detailQuery.data?.symbol.qualified_name ?? 'Symbol detail'}
            </SheetTitle>
            <SheetDescription>
              {detailQuery.data
                ? `${detailQuery.data.symbol.file_path}:${detailQuery.data.symbol.start_line}-${detailQuery.data.symbol.end_line}`
                : 'Loading symbol source'}
            </SheetDescription>
          </SheetHeader>

          <SheetBody className="space-y-6">
            {detailQuery.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading symbol detail...
              </div>
            ) : null}

            {detailQuery.isError ? (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
                Failed to load symbol detail.
              </div>
            ) : null}

            {detailQuery.data ? (
              <>
                <div className="grid gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-4 md:grid-cols-3">
                  <MetaBlock label="Kind" value={detailQuery.data.symbol.kind} />
                  <MetaBlock
                    label="Language"
                    value={
                      languageLabels[detailQuery.data.symbol.language] ??
                      detailQuery.data.symbol.language
                    }
                  />
                  <MetaBlock
                    label="Linked explorer entries"
                    value={String(detailQuery.data.related_entries.length)}
                  />
                </div>

                <div className="space-y-2">
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
                    Signature
                  </p>
                  <pre className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/70 p-4 font-mono text-sm text-cyan-100">
                    {detailQuery.data.symbol.signature}
                  </pre>
                </div>

                <div className="space-y-2">
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
                    Source
                  </p>
                  <pre className="max-h-[50vh] overflow-auto rounded-xl border border-slate-800 bg-slate-900/70 p-4 font-mono text-xs leading-6 text-slate-100">
                    {detailQuery.data.source}
                  </pre>
                </div>

                {detailQuery.data.related_entries.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-xs uppercase tracking-[0.2em] text-slate-500">
                      Related Explorer Entries
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {detailQuery.data.related_entries.map((entry) => (
                        <span
                          key={`${entry.entryType}:${entry.path}`}
                          className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-300"
                        >
                          {entry.entryType}: {entry.path}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}
          </SheetBody>
        </SheetContent>
      </Sheet>
    </>
  )
}

function MetaBlock({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 text-sm text-slate-100">{value}</p>
    </div>
  )
}
