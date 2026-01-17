'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Loader2,
  RotateCcw,
  Sparkles,
  XCircle,
} from 'lucide-react'
import Image from 'next/image'
import { useState } from 'react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  fetchMockupComparison,
  getScreenshotUrl,
  type MockupStatus,
  updateMockupStatus,
} from '@/lib/api/evidence'
import { cn } from '@/lib/utils'

interface MockupComparisonDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  entryId: number
  entryPath?: string
  onStatusChange?: () => void
}

const statusConfig: Record<
  MockupStatus,
  { label: string; color: string; icon: typeof CheckCircle2 }
> = {
  generated: {
    label: 'Generated',
    color: 'bg-slate-500/20 text-slate-400',
    icon: Sparkles,
  },
  pending_approval: {
    label: 'Pending Approval',
    color: 'bg-amber-500/20 text-amber-400',
    icon: Eye,
  },
  approved: {
    label: 'Approved',
    color: 'bg-green-500/20 text-green-400',
    icon: CheckCircle2,
  },
  rejected: {
    label: 'Rejected',
    color: 'bg-red-500/20 text-red-400',
    icon: XCircle,
  },
}

export function MockupComparisonDialog({
  open,
  onOpenChange,
  projectId,
  entryId,
  entryPath,
  onStatusChange,
}: MockupComparisonDialogProps) {
  const queryClient = useQueryClient()
  const [showDiff, setShowDiff] = useState(false)
  const [viewMode, setViewMode] = useState<'side-by-side' | 'slider'>(
    'side-by-side',
  )
  const [sliderPos, setSliderPos] = useState(50)

  const { data, isLoading, error } = useQuery({
    queryKey: ['mockup-comparison', projectId, entryId],
    queryFn: () => fetchMockupComparison(projectId, entryId),
    enabled: open,
  })

  const statusMutation = useMutation({
    mutationFn: ({
      evidenceId,
      status,
    }: {
      evidenceId: string
      status: MockupStatus
    }) => updateMockupStatus(projectId, evidenceId, status),
    onSuccess: (_, { status }) => {
      toast.success(`Mockup ${status === 'approved' ? 'approved' : 'rejected'}`)
      queryClient.invalidateQueries({
        queryKey: ['mockup-comparison', projectId, entryId],
      })
      queryClient.invalidateQueries({
        queryKey: ['entry-mockups', projectId, entryId],
      })
      onStatusChange?.()
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const mockup = data?.mockup
  const actual = data?.actualScreenshot

  const mockupUrl = mockup
    ? getScreenshotUrl(projectId, mockup.evidenceId)
    : null
  const actualUrl = actual
    ? getScreenshotUrl(projectId, actual.evidenceId)
    : null

  const currentStatus = mockup?.mockupStatus
  const StatusIcon = currentStatus ? statusConfig[currentStatus]?.icon : null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-phosphor-400" />
            Mockup Comparison
            {currentStatus && (
              <Badge
                variant="outline"
                className={cn('ml-2', statusConfig[currentStatus]?.color)}
              >
                {StatusIcon && <StatusIcon className="w-3 h-3 mr-1" />}
                {statusConfig[currentStatus]?.label}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription>
            {entryPath ? (
              <>
                Comparing mockup (target) vs actual screenshot for{' '}
                <code className="text-phosphor-400">{entryPath}</code>
              </>
            ) : (
              <>Comparing mockup (target) vs actual screenshot</>
            )}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex-1 flex items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-slate-500" />
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center py-12">
            <div className="text-center text-slate-400">
              <XCircle className="w-8 h-8 mx-auto mb-2 text-red-400" />
              <p>{(error as Error).message}</p>
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-auto space-y-4">
            {/* View Controls */}
            <div className="flex items-center justify-end gap-2">
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

            {/* Comparison View */}
            {viewMode === 'side-by-side' ? (
              <div className="grid grid-cols-2 gap-2">
                {/* Actual Screenshot */}
                <div className="rounded-lg border border-slate-700 overflow-hidden">
                  <div className="text-xs text-slate-400 px-3 py-1 bg-slate-800/50 flex items-center gap-1">
                    <ChevronLeft className="w-3 h-3" />
                    Actual (Current State)
                  </div>
                  <div className="relative aspect-video bg-slate-800">
                    {actualUrl ? (
                      <Image
                        src={actualUrl}
                        alt="Actual screenshot"
                        fill
                        className="object-contain"
                        unoptimized
                      />
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center text-slate-500">
                        No screenshot linked
                      </div>
                    )}
                  </div>
                </div>

                {/* Mockup */}
                <div className="rounded-lg border border-phosphor-700/50 overflow-hidden">
                  <div className="text-xs text-phosphor-400 px-3 py-1 bg-phosphor-900/30 flex items-center gap-1">
                    Mockup (Target State)
                    <ChevronRight className="w-3 h-3" />
                  </div>
                  <div className="relative aspect-video bg-slate-800">
                    {mockupUrl ? (
                      <Image
                        src={mockupUrl}
                        alt="Mockup"
                        fill
                        className={cn(
                          'object-contain',
                          showDiff && 'mix-blend-difference',
                        )}
                        unoptimized
                      />
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center text-slate-500">
                        No mockup available
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              /* Slider view */
              <div className="rounded-lg border border-slate-700 overflow-hidden">
                <div className="relative aspect-video bg-slate-800">
                  {/* Actual image (background) */}
                  {actualUrl && (
                    <Image
                      src={actualUrl}
                      alt="Actual"
                      fill
                      className="object-contain"
                      unoptimized
                    />
                  )}
                  {/* Mockup image with clip */}
                  {mockupUrl && (
                    <div
                      className="absolute inset-0 overflow-hidden"
                      style={{ width: `${sliderPos}%` }}
                    >
                      <div
                        className="relative w-full h-full"
                        style={{ width: `${100 / (sliderPos / 100)}%` }}
                      >
                        <Image
                          src={mockupUrl}
                          alt="Mockup"
                          fill
                          className="object-contain"
                          unoptimized
                        />
                      </div>
                    </div>
                  )}
                  {/* Slider control */}
                  <div
                    className="absolute top-0 bottom-0 w-1 bg-phosphor-500 cursor-ew-resize"
                    style={{ left: `${sliderPos}%` }}
                  />
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={sliderPos}
                  onChange={(e) => setSliderPos(Number(e.target.value))}
                  className="w-full accent-phosphor-500"
                />
                <div className="flex justify-between text-xs text-slate-400 px-2 pb-1">
                  <span>Actual</span>
                  <span>Mockup</span>
                </div>
              </div>
            )}

            {/* Metadata */}
            {mockup && (
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div className="bg-slate-800/50 rounded-lg p-3 space-y-1">
                  <div className="text-slate-400">Mockup Evidence</div>
                  <div className="font-mono text-xs text-slate-300">
                    {mockup.evidenceId}
                  </div>
                  <div className="text-xs text-slate-500">
                    Version {mockup.version} · Captured{' '}
                    {new Date(mockup.capturedAt).toLocaleDateString()}
                  </div>
                </div>
                {actual && (
                  <div className="bg-slate-800/50 rounded-lg p-3 space-y-1">
                    <div className="text-slate-400">Actual Screenshot</div>
                    <div className="font-mono text-xs text-slate-300">
                      {actual.evidenceId}
                    </div>
                    <div className="text-xs text-slate-500">
                      Version {actual.version} · Captured{' '}
                      {new Date(actual.capturedAt).toLocaleDateString()}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-700">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          {mockup && currentStatus !== 'approved' && (
            <>
              <Button
                variant="outline"
                onClick={() =>
                  statusMutation.mutate({
                    evidenceId: mockup.evidenceId,
                    status: 'rejected',
                  })
                }
                disabled={statusMutation.isPending}
                className="border-red-700 text-red-400 hover:bg-red-500/10"
              >
                {statusMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <XCircle className="w-4 h-4 mr-2" />
                )}
                Reject
              </Button>
              <Button
                onClick={() =>
                  statusMutation.mutate({
                    evidenceId: mockup.evidenceId,
                    status: 'approved',
                  })
                }
                disabled={statusMutation.isPending}
                className="bg-green-600 hover:bg-green-700"
              >
                {statusMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                )}
                Approve
              </Button>
            </>
          )}
          {mockup && currentStatus === 'rejected' && (
            <Button
              variant="outline"
              onClick={() =>
                statusMutation.mutate({
                  evidenceId: mockup.evidenceId,
                  status: 'pending_approval',
                })
              }
              disabled={statusMutation.isPending}
              className="border-amber-700 text-amber-400 hover:bg-amber-500/10"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Request Regeneration
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
