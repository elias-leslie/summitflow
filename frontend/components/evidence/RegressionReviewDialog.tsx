'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { buildApiUrl } from '@/lib/api-config'
import {
  AlertTriangle,
  Bug,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Loader2,
  Terminal,
} from 'lucide-react'
import Image from 'next/image'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

// ============================================================================
// Types
// ============================================================================

interface Regression {
  id: number
  evidence_id: number
  baseline_evidence_id: number | null
  regression_type: string
  pixel_diff_pct: number | null
  console_errors_added: number
  severity: string
  status: string
  linked_task_id: string | null
  created_at: string
}

interface EvidenceDetail {
  id: number
  capability_id: string
  criterion_id: string
  version: number
  project_id: string
  captured_at: string
  metadata?: {
    console?: {
      errors?: Array<{ text: string; source?: string }>
    }
  }
}

interface RegressionReviewDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  regression: Regression
  onReviewed?: () => void
}

// ============================================================================
// API Functions
// ============================================================================

async function fetchEvidenceById(
  projectId: string,
  evidenceId: number,
): Promise<EvidenceDetail | null> {
  try {
    const res = await fetch(
      buildApiUrl(`/api/projects/${projectId}/evidence/by-id/${evidenceId}`),
    )
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

async function reviewRegression(
  projectId: string,
  regressionId: number,
  verdict: 'accept_change' | 'confirm_regression',
  notes?: string,
): Promise<{ success: boolean }> {
  const res = await fetch(
    buildApiUrl(`/api/projects/${projectId}/evidence/regressions/${regressionId}/review`),
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ verdict, notes }),
    },
  )
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Review failed' }))
    throw new Error(error.detail || 'Review failed')
  }
  return res.json()
}

// ============================================================================
// Component
// ============================================================================

export function RegressionReviewDialog({
  open,
  onOpenChange,
  projectId,
  regression,
  onReviewed,
}: RegressionReviewDialogProps) {
  const queryClient = useQueryClient()
  const [showDiff, setShowDiff] = useState(false)
  const [notes, setNotes] = useState('')
  const [viewMode, setViewMode] = useState<'side-by-side' | 'slider'>(
    'side-by-side',
  )
  const [sliderPos, setSliderPos] = useState(50)

  // Fetch evidence details
  const { data: currentEvidence, isLoading: loadingCurrent } = useQuery({
    queryKey: ['evidence-detail', projectId, regression.evidence_id],
    queryFn: () => fetchEvidenceById(projectId, regression.evidence_id),
    enabled: open,
  })

  const { data: baselineEvidence, isLoading: loadingBaseline } = useQuery({
    queryKey: ['evidence-detail', projectId, regression.baseline_evidence_id],
    queryFn: () =>
      regression.baseline_evidence_id
        ? fetchEvidenceById(projectId, regression.baseline_evidence_id)
        : Promise.resolve(null),
    enabled: open && !!regression.baseline_evidence_id,
  })

  const reviewMutation = useMutation({
    mutationFn: (verdict: 'accept_change' | 'confirm_regression') =>
      reviewRegression(projectId, regression.id, verdict, notes || undefined),
    onSuccess: (_, verdict) => {
      toast.success(
        verdict === 'accept_change'
          ? 'Change accepted - baseline updated'
          : 'Regression confirmed - bug task will be created',
      )
      queryClient.invalidateQueries({ queryKey: ['regressions', projectId] })
      onReviewed?.()
      onOpenChange(false)
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const isLoading = loadingCurrent || loadingBaseline
  const hasBaseline = !!regression.baseline_evidence_id && !!baselineEvidence

  // Build screenshot URLs
  const currentScreenshotUrl = currentEvidence
    ? `/api/projects/${projectId}/evidence/${currentEvidence.capability_id}/${currentEvidence.criterion_id}/screenshot?version=${currentEvidence.version}`
    : null
  const baselineScreenshotUrl =
    hasBaseline && baselineEvidence
      ? `/api/projects/${projectId}/evidence/${baselineEvidence.capability_id}/${baselineEvidence.criterion_id}/screenshot?version=${baselineEvidence.version}`
      : null

  // Extract console errors
  const currentErrors = currentEvidence?.metadata?.console?.errors ?? []
  const baselineErrors = baselineEvidence?.metadata?.console?.errors ?? []
  const newErrors = currentErrors.filter(
    (e) => !baselineErrors.some((b) => b.text === e.text),
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-amber-500" />
            Regression Review
            <span className="text-sm font-normal text-slate-400">
              #{regression.id}
            </span>
          </DialogTitle>
          <DialogDescription>
            {regression.regression_type === 'visual' ? (
              <>
                Visual difference detected (
                {regression.pixel_diff_pct?.toFixed(2)}% change)
              </>
            ) : regression.regression_type === 'console_errors' ? (
              <>
                +{regression.console_errors_added} new console errors detected
              </>
            ) : (
              <>Regression detected: {regression.regression_type}</>
            )}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-slate-500" />
          </div>
        ) : (
          <div className="flex-1 overflow-auto space-y-4">
            {/* Screenshot Comparison */}
            {currentScreenshotUrl && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-300">
                    Screenshot Comparison
                  </span>
                  <div className="flex items-center gap-2">
                    {hasBaseline && (
                      <>
                        <button
                          onClick={() => setViewMode('side-by-side')}
                          className={cn(
                            'px-2 py-1 text-xs rounded',
                            viewMode === 'side-by-side'
                              ? 'bg-phosphor-500/20 text-phosphor-400'
                              : 'text-slate-400 hover:text-white',
                          )}
                        >
                          Side by Side
                        </button>
                        <button
                          onClick={() => setViewMode('slider')}
                          className={cn(
                            'px-2 py-1 text-xs rounded',
                            viewMode === 'slider'
                              ? 'bg-phosphor-500/20 text-phosphor-400'
                              : 'text-slate-400 hover:text-white',
                          )}
                        >
                          Slider
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => setShowDiff(!showDiff)}
                      className={cn(
                        'px-2 py-1 text-xs rounded flex items-center gap-1',
                        showDiff
                          ? 'bg-amber-500/20 text-amber-400'
                          : 'text-slate-400 hover:text-white',
                      )}
                    >
                      {showDiff ? (
                        <EyeOff className="w-3 h-3" />
                      ) : (
                        <Eye className="w-3 h-3" />
                      )}
                      Diff
                    </button>
                  </div>
                </div>

                {!hasBaseline ? (
                  <div className="rounded-lg border border-slate-700 overflow-hidden">
                    <div className="text-xs text-slate-400 px-3 py-1 bg-slate-800/50">
                      Current (No baseline)
                    </div>
                    <div className="relative aspect-video bg-slate-800">
                      <Image
                        src={currentScreenshotUrl}
                        alt="Current screenshot"
                        fill
                        className="object-contain"
                        unoptimized
                      />
                    </div>
                  </div>
                ) : viewMode === 'side-by-side' ? (
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-lg border border-slate-700 overflow-hidden">
                      <div className="text-xs text-slate-400 px-3 py-1 bg-slate-800/50 flex items-center gap-1">
                        <ChevronLeft className="w-3 h-3" />
                        Baseline (v{baselineEvidence?.version})
                      </div>
                      <div className="relative aspect-video bg-slate-800">
                        {baselineScreenshotUrl && (
                          <Image
                            src={baselineScreenshotUrl}
                            alt="Baseline screenshot"
                            fill
                            className="object-contain"
                            unoptimized
                          />
                        )}
                      </div>
                    </div>
                    <div className="rounded-lg border border-amber-700/50 overflow-hidden">
                      <div className="text-xs text-amber-400 px-3 py-1 bg-amber-900/30 flex items-center gap-1">
                        Current (v{currentEvidence?.version})
                        <ChevronRight className="w-3 h-3" />
                      </div>
                      <div className="relative aspect-video bg-slate-800">
                        <Image
                          src={currentScreenshotUrl}
                          alt="Current screenshot"
                          fill
                          className={cn(
                            'object-contain',
                            showDiff && 'mix-blend-difference',
                          )}
                          unoptimized
                        />
                      </div>
                    </div>
                  </div>
                ) : (
                  /* Slider view */
                  <div className="rounded-lg border border-slate-700 overflow-hidden">
                    <div className="relative aspect-video bg-slate-800">
                      {/* Baseline image */}
                      {baselineScreenshotUrl && (
                        <Image
                          src={baselineScreenshotUrl}
                          alt="Baseline"
                          fill
                          className="object-contain"
                          unoptimized
                        />
                      )}
                      {/* Current image with clip */}
                      <div
                        className="absolute inset-0 overflow-hidden"
                        style={{ width: `${sliderPos}%` }}
                      >
                        <div
                          className="relative w-full h-full"
                          style={{ width: `${100 / (sliderPos / 100)}%` }}
                        >
                          <Image
                            src={currentScreenshotUrl}
                            alt="Current"
                            fill
                            className="object-contain"
                            unoptimized
                          />
                        </div>
                      </div>
                      {/* Slider control */}
                      <div
                        className="absolute top-0 bottom-0 w-1 bg-amber-500 cursor-ew-resize"
                        style={{ left: `${sliderPos}%` }}
                      />
                    </div>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={sliderPos}
                      onChange={(e) => setSliderPos(Number(e.target.value))}
                      className="w-full accent-amber-500"
                    />
                  </div>
                )}
              </div>
            )}

            {/* Console Errors Diff */}
            {regression.console_errors_added > 0 && newErrors.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
                  <Terminal className="w-4 h-4 text-red-400" />
                  New Console Errors (+{newErrors.length})
                </div>
                <div className="space-y-1 max-h-40 overflow-auto">
                  {newErrors.map((error, idx) => (
                    <div
                      key={idx}
                      className="bg-red-500/10 border border-red-500/20 rounded px-3 py-2 text-xs font-mono text-red-300"
                    >
                      {error.text}
                      {error.source && (
                        <div className="text-red-400/60 mt-0.5">
                          {error.source}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Review Notes */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-300">
                Notes (optional)
              </label>
              <Textarea
                placeholder="Add context about this change..."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="h-20 resize-none"
              />
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-700">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="outline"
            onClick={() => reviewMutation.mutate('accept_change')}
            disabled={reviewMutation.isPending}
            className="border-green-700 text-green-400 hover:bg-green-500/10"
          >
            {reviewMutation.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <CheckCircle2 className="w-4 h-4 mr-2" />
            )}
            Accept Change
          </Button>
          <Button
            variant="destructive"
            onClick={() => reviewMutation.mutate('confirm_regression')}
            disabled={reviewMutation.isPending}
          >
            {reviewMutation.isPending ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Bug className="w-4 h-4 mr-2" />
            )}
            Confirm Regression
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
