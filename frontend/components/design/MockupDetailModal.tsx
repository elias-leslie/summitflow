'use client'

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
  onCreateIteration: (mockup: Mockup) => void
  onSelectMockup: (mockup: Mockup) => void
  navigation?: MockupModalNavigation
}

export function MockupDetailModal({
  mockup,
  projectId,
  open,
  onOpenChange,
  onStatusChange,
  onCreateIteration,
  onSelectMockup,
  navigation,
}: MockupDetailModalProps) {
  const {
    updating,
    showHistory,
    showComparison,
    showDeleteConfirm,
    showRerunDialog,
    history,
    deleteMutation,
    setShowHistory,
    setShowComparison,
    setShowDeleteConfirm,
    setShowRerunDialog,
    handleStatusChange,
  } = useMockupModal(mockup, projectId, open, onOpenChange, onStatusChange)

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
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [navigation, onOpenChange, open, showDeleteConfirm, showRerunDialog])

  if (!open) return null

  const canCompare = hasScreenshot(mockup)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-slate-950/90 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
      />

      <div className="relative bg-slate-900 rounded-xl w-[95vw] max-w-[1600px] h-[90vh] overflow-hidden flex flex-col mx-4">
        <ModalHeader
          mockup={mockup}
          navigation={navigation}
          onClose={() => onOpenChange(false)}
        />

        <div className="flex-1 overflow-hidden flex flex-col lg:flex-row min-h-0">
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
            onVersionCreated={(created) => {
              onStatusChange()
              setShowHistory(true)
              onSelectMockup(created)
            }}
          />

          <DetailsSidebar
            mockup={mockup}
            updating={updating}
            showHistory={showHistory}
            history={history}
            onStatusChange={handleStatusChange}
            onSelectHistoryMockup={onSelectMockup}
          />
        </div>

        {showDeleteConfirm && (
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

        {showRerunDialog && (
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
