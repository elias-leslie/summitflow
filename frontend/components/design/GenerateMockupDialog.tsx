'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { type ExplorerEntry, fetchExplorerEntries } from '@/lib/api/explorer'
import { type AnalyzePageResponse, analyzePage } from '@/lib/api/mockups'
import { AnalysisResult } from './mockup-dialog/AnalysisResult'
import { PageDropdown } from './mockup-dialog/PageDropdown'
import { SubmitButtons } from './mockup-dialog/SubmitButtons'

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

  // Fetch pages from explorer
  const { data: pagesData, isLoading: isPagesLoading } = useQuery({
    queryKey: ['explorer-pages', projectId],
    queryFn: () =>
      fetchExplorerEntries(projectId, {
        type: 'page',
        sort: 'path',
        dir: 'asc',
      }),
    enabled: open,
  })

  const pages = pagesData?.entries || []

  // Build full URL from page entry
  const buildPageUrl = (page: ExplorerEntry): string => {
    const scannedUrl = page.metadata.url
    if (typeof scannedUrl === 'string' && scannedUrl.length > 0) {
      return scannedUrl
    }

    const port = page.metadata.port
    return port ? `http://localhost:${port}${page.path}` : page.path
  }

  // Handle page selection
  const handlePageSelect = (page: ExplorerEntry) => {
    setSelectedPage(page)
    setPageUrl(buildPageUrl(page))
    setIsDropdownOpen(false)
  }

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
      <div className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm" onClick={handleClose} role="presentation" />

      {/* Dialog */}
      <div className="relative bg-slate-900 rounded-xl w-full max-w-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div className="flex items-center gap-3">
            <Sparkles className="w-5 h-5 text-outrun-400" />
            <h2 className="text-lg font-semibold text-slate-100 display">
              Generate Design Mockup
            </h2>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="p-2 text-slate-400 hover:text-white"
            aria-label="Close dialog"
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

              <PageDropdown
                selectedPage={selectedPage}
                pages={pages}
                isPagesLoading={isPagesLoading}
                isDropdownOpen={isDropdownOpen}
                isDisabled={analyzeMutation.isPending || isPagesLoading}
                onToggle={() => setIsDropdownOpen(!isDropdownOpen)}
                onSelect={handlePageSelect}
                onClose={() => setIsDropdownOpen(false)}
              />

              <p className="mt-2 text-xs text-slate-500">
                {selectedPage ? (
                  <span className="font-mono text-phosphor-500">{pageUrl}</span>
                ) : (
                  'Select a page from your project to analyze its design'
                )}
              </p>
            </div>

            <SubmitButtons
              isPending={analyzeMutation.isPending}
              isDisabled={!pageUrl.trim()}
              onCancel={handleClose}
            />
          </form>

          {/* Result */}
          {result && (
            <div className="mt-6 border-t border-slate-800 pt-6">
              <AnalysisResult result={result} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
