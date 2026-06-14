'use client'

import clsx from 'clsx'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useEffect } from 'react'
import { ConfirmDeleteDialog } from '@/components/shared/ConfirmDeleteDialog'
import { hasScreenshot, type Mockup } from '@/lib/api/mockups'
import { DetailsSidebar } from './mockup-modal/DetailsSidebar'
import {
  type MockupModalNavigation,
  ModalHeader,
} from './mockup-modal/ModalHeader'
import { PreviewArea } from './mockup-modal/PreviewArea'
import { RerunMockupDialog } from './mockup-modal/RerunMockupDialog'
import { useMockupModal } from './mockup-modal/useMockupModal'

interface MockupDetailModalProps {
  mockup: Mockup
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onStatusChange: () => void
  onRate: (mockupId: string, rating: number) => void
  onCommentsChanged: () => void
  onCreateIteration: (mockup: Mockup) => void
  onSelectMockup: (mockup: Mockup) => void
  navigation?: MockupModalNavigation
  readOnly?: boolean
  fetchHistory?: (projectId: string, mockupId: string) => Promise<Mockup[]>
  getImageUrl?: (projectId: string, mockupId: string) => string
  getScreenshotUrl?: (projectId: string, mockupId: string) => string
  isRating?: boolean
}

export function MockupDetailModal({
  mockup,
  projectId,
  open,
  onOpenChange,
  onStatusChange,
  onRate,
  onCommentsChanged,
  onCreateIteration,
  onSelectMockup,
  navigation,
  readOnly = false,
  fetchHistory,
  getImageUrl,
  getScreenshotUrl,
  isRating = false,
}: MockupDetailModalProps) {
  const {
    updating,
    showHistory,
    showComparison,
    showDeleteConfirm,
    showRerunDialog,
    showDetails,
    history,
    deleteMutation,
    setShowHistory,
    setShowComparison,
    setShowDeleteConfirm,
    setShowRerunDialog,
    setShowDetails,
    handleStatusChange,
  } = useMockupModal(mockup, projectId, open, onOpenChange, onStatusChange, {
    readOnly,
    fetchHistory,
  })

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const isEditableTarget =
        target?.tagName === 'INPUT' ||
        target?.tagName === 'TEXTAREA' ||
        target?.tagName === 'SELECT' ||
        target?.isContentEditable

      if (e.key === 'Escape') onOpenChange(false)
      if (showDeleteConfirm || showRerunDialog || isEditableTarget) return
      if (e.key === 'ArrowLeft' && navigation?.canGoPrevious) {
        e.preventDefault()
        navigation.onPrevious()
      }
      if (e.key === 'ArrowRight' && navigation?.canGoNext) {
        e.preventDefault()
        navigation.onNext()
      }
      if (e.key === ']' || e.key === '[') {
        e.preventDefault()
        setShowDetails((prev) => !prev)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [
    navigation,
    onOpenChange,
    open,
    showDeleteConfirm,
    showRerunDialog,
    setShowDetails,
  ])

  if (!open) return null

  const canCompare = hasScreenshot(mockup)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
      />

      <div className="relative bg-slate-900 rounded-xl w-[98vw] h-[94vh] overflow-hidden flex flex-col mx-2">
        <ModalHeader
          mockup={mockup}
          navigation={navigation}
          onClose={() => onOpenChange(false)}
        />

        <div className="flex-1 overflow-hidden flex flex-col lg:flex-row min-h-0 relative">
          <PreviewArea
            mockup={mockup}
            projectId={projectId}
            showComparison={showComparison}
            showHistory={showHistory}
            canCompare={canCompare}
            onToggleComparison={() => setShowComparison(!showComparison)}
            onToggleHistory={() => setShowHistory(!showHistory)}
            onCreateIteration={() => onCreateIteration(mockup)}
            onRerun={() => setShowRerunDialog(true)}
            onDelete={() => setShowDeleteConfirm(true)}
            readOnly={readOnly}
            getImageUrl={getImageUrl}
            getScreenshotUrl={getScreenshotUrl}
            onVersionCreated={(created) => {
              onStatusChange()
              setShowHistory(true)
              onSelectMockup(created)
            }}
          />

          {showDetails && (
            <DetailsSidebar
              mockup={mockup}
              projectId={projectId}
              updating={updating}
              showHistory={showHistory}
              history={history}
              isRating={isRating}
              onStatusChange={handleStatusChange}
              onRate={(rating) => onRate(mockup.mockup_id, rating)}
              onCommentsChanged={onCommentsChanged}
              onSelectHistoryMockup={onSelectMockup}
              readOnly={readOnly}
            />
          )}

          <button
            type="button"
            onClick={() => setShowDetails((prev) => !prev)}
            aria-label={showDetails ? 'Hide details (])' : 'Show details (])'}
            title={showDetails ? 'Hide details (])' : 'Show details (])'}
            className={clsx(
              'hidden lg:flex absolute top-1/2 -translate-y-1/2 z-10',
              'h-16 w-5 items-center justify-center',
              'rounded-l-md border border-r-0 border-slate-700',
              'bg-slate-800/90 hover:bg-slate-700 text-slate-400 hover:text-slate-100',
              'transition-colors backdrop-blur-sm',
              showDetails ? 'right-80' : 'right-0',
            )}
          >
            {showDetails ? (
              <ChevronRight className="w-3.5 h-3.5" />
            ) : (
              <ChevronLeft className="w-3.5 h-3.5" />
            )}
          </button>
        </div>

        {!readOnly && showDeleteConfirm && (
          <ConfirmDeleteDialog
            entityType="mockup"
            entityName={mockup.name}
            isDeleting={deleteMutation.isPending}
            onConfirm={() => deleteMutation.mutate()}
            onCancel={() => setShowDeleteConfirm(false)}
            positioning="absolute"
            zIndex="z-10"
          />
        )}

        {!readOnly && showRerunDialog && (
          <RerunMockupDialog
            mockup={mockup}
            projectId={projectId}
            onClose={() => setShowRerunDialog(false)}
            onCreated={(created) => {
              onStatusChange()
              setShowHistory(true)
              onSelectMockup(created)
            }}
          />
        )}
      </div>
    </div>
  )
}
