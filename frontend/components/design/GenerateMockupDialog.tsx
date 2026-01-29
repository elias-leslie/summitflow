'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Scan,
  Sparkles,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { analyzePage, type AnalyzePageResponse } from '@/lib/api/mockups'
import { fetchExplorerEntries, type ExplorerEntry } from '@/lib/api/explorer'

interface GenerateMockupDialogProps {
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultUrl?: string
}

export function GenerateMockupDialog({
  projectId,
  open,
  onOpenChange,
  defaultUrl = '',
}: GenerateMockupDialogProps) {
  const [pageUrl, setPageUrl] = useState(defaultUrl)
  const [selectedPage, setSelectedPage] = useState<ExplorerEntry | null>(null)
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const [result, setResult] = useState<AnalyzePageResponse | null>(null)
  const queryClient = useQueryClient()
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Fetch pages from explorer
  const { data: pagesData, isLoading: isPagesLoading } = useQuery({
    queryKey: ['explorer-pages', projectId],
    queryFn: () => fetchExplorerEntries(projectId, { type: 'page', sort: 'path', dir: 'asc' }),
    enabled: open,
  })

  const pages = pagesData?.entries || []

  // Build full URL from page entry
  const buildPageUrl = (page: ExplorerEntry): string => {
    const port = page.metadata.port || 3001
    const path = page.path
    return `http://localhost:${port}${path}`
  }

  // Handle page selection
  const handlePageSelect = (page: ExplorerEntry) => {
    setSelectedPage(page)
    setPageUrl(buildPageUrl(page))
    setIsDropdownOpen(false)
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false)
      }
    }

    if (isDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isDropdownOpen])

  const analyzeMutation = useMutation({
    mutationFn: () => analyzePage(projectId, pageUrl),
    onSuccess: (data) => {
      setResult(data)
      if (data.success) {
        queryClient.invalidateQueries({ queryKey: ['mockups', projectId] })
        queryClient.invalidateQueries({ queryKey: ['mockup-stats', projectId] })
      }
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!pageUrl.trim()) return
    setResult(null)
    analyzeMutation.mutate()
  }

  const handleClose = () => {
    setPageUrl(defaultUrl)
    setResult(null)
    analyzeMutation.reset()
    onOpenChange(false)
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/80"
        onClick={handleClose}
      />

      {/* Dialog */}
      <div className="relative bg-slate-900 rounded-xl w-full max-w-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-outrun-400" />
            <h2 className="text-lg font-semibold text-white">
              Generate Design Mockup
            </h2>
          </div>
          <button
            onClick={handleClose}
            className="p-2 text-slate-400 hover:text-white"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          <p className="text-slate-400 mb-6">
            Analyze a page against design standards and generate improvement
            recommendations. The page will be captured and analyzed using Claude
            vision.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Select Page
              </label>

              {/* Custom Dropdown */}
              <div className="relative" ref={dropdownRef}>
                <button
                  type="button"
                  onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                  disabled={analyzeMutation.isPending || isPagesLoading}
                  className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg text-left text-white hover:border-outrun-500/50 focus:outline-none focus:ring-2 focus:ring-outrun-500 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed group"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      {isPagesLoading ? (
                        <span className="text-slate-400">Loading pages...</span>
                      ) : selectedPage ? (
                        <div className="space-y-0.5">
                          <div className="text-sm font-medium text-outrun-400">
                            {selectedPage.name}
                          </div>
                          <div className="text-xs text-slate-400 font-mono truncate">
                            {selectedPage.path}
                          </div>
                        </div>
                      ) : (
                        <span className="text-slate-400">Choose a page to analyze...</span>
                      )}
                    </div>
                    <ChevronDown
                      className={`w-5 h-5 text-slate-400 ml-3 transition-transform duration-200 ${
                        isDropdownOpen ? 'rotate-180 text-outrun-400' : ''
                      }`}
                    />
                  </div>
                </button>

                {/* Dropdown Menu */}
                {isDropdownOpen && !isPagesLoading && (
                  <div className="absolute z-10 w-full mt-2 bg-slate-850 border border-slate-700 rounded-lg shadow-2xl overflow-hidden">
                    <div className="max-h-[28rem] overflow-y-auto custom-scrollbar">
                      {pages.length === 0 ? (
                        <div className="px-4 py-8 text-center text-slate-400">
                          <p className="text-sm">No pages found</p>
                          <p className="text-xs mt-1">Run an explorer scan to discover pages</p>
                        </div>
                      ) : (
                        <div className="py-1">
                          {pages.map((page) => (
                            <button
                              key={page.id}
                              type="button"
                              onClick={() => handlePageSelect(page)}
                              className="w-full px-4 py-2 text-left hover:bg-slate-800 transition-colors duration-150 group border-b border-slate-800/50 last:border-b-0"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                  <div className="text-sm font-medium text-white group-hover:text-outrun-400 transition-colors">
                                    {page.name}
                                  </div>
                                  <div className="text-xs text-slate-400 font-mono truncate">
                                    {page.path}
                                  </div>
                                  {page.metadata.route_params && page.metadata.route_params.length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-1">
                                      {(page.metadata.route_params as string[]).map((param) => (
                                        <span
                                          key={param}
                                          className="text-2xs px-1.5 py-0.5 bg-slate-900 text-phosphor-400 rounded border border-slate-700"
                                        >
                                          {param}
                                        </span>
                                      ))}
                                    </div>
                                  )}
                                </div>
                                <div className={`px-2 py-0.5 rounded text-2xs font-medium shrink-0 ${
                                  page.healthStatus === 'healthy' ? 'bg-emerald-950/50 text-emerald-400' :
                                  page.healthStatus === 'warning' ? 'bg-amber-950/50 text-amber-400' :
                                  page.healthStatus === 'error' ? 'bg-rose-950/50 text-rose-400' :
                                  'bg-slate-800 text-slate-500'
                                }`}>
                                  {page.healthStatus}
                                </div>
                              </div>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <p className="mt-2 text-xs text-slate-500">
                {selectedPage ? (
                  <span className="font-mono text-phosphor-500">{pageUrl}</span>
                ) : (
                  'Select a page from your project to analyze its design'
                )}
              </p>
            </div>

            {/* Submit button */}
            <div className="flex justify-end gap-3 pt-4">
              <button
                type="button"
                onClick={handleClose}
                className="btn-secondary"
                disabled={analyzeMutation.isPending}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!pageUrl.trim() || analyzeMutation.isPending}
                className="btn-primary flex items-center gap-2"
              >
                {analyzeMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Analyzing...
                  </>
                ) : (
                  <>
                    <Scan className="w-4 h-4" />
                    Analyze Page
                  </>
                )}
              </button>
            </div>
          </form>

          {/* Result */}
          {result && (
            <div className="mt-6 border-t border-slate-800 pt-6">
              {result.success ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-emerald-400">
                    <CheckCircle2 className="w-5 h-5" />
                    <span className="font-medium">Analysis & Mockup Complete</span>
                  </div>
                  <div className="grid grid-cols-3 gap-4 text-sm">
                    <div className="card p-3">
                      <div className="text-slate-400 mb-1">Mockup ID</div>
                      <div className="text-white font-mono text-xs">
                        {result.mockup_id}
                      </div>
                    </div>
                    <div className="card p-3">
                      <div className="text-slate-400 mb-1">Issues Found</div>
                      <div className="text-white">{result.issues_found}</div>
                    </div>
                    <div className="card p-3">
                      <div className="text-slate-400 mb-1">Mockup Image</div>
                      <div className="text-white text-xs">
                        {result.mockup_image_path ? '✓ Generated' : '—'}
                      </div>
                    </div>
                  </div>
                  {result.recommendations && (
                    <div>
                      <div className="text-sm font-medium text-slate-300 mb-2">
                        Recommendations Preview
                      </div>
                      <div className="card p-3 max-h-48 overflow-auto">
                        <pre className="text-xs text-slate-300 whitespace-pre-wrap">
                          {result.recommendations.slice(0, 1000)}
                          {result.recommendations.length > 1000 && '...'}
                        </pre>
                      </div>
                    </div>
                  )}
                  <p className="text-sm text-slate-400">
                    View the full analysis in the mockup detail modal.
                  </p>
                </div>
              ) : (
                <div className="flex items-start gap-3 p-4 bg-rose-950/30 border border-rose-500/30 rounded-lg">
                  <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />
                  <div>
                    <div className="text-rose-400 font-medium">
                      Analysis Failed
                    </div>
                    <div className="text-slate-400 text-sm mt-1">
                      {result.error}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
