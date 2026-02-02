'use client'

import { hasScreenshot, type Mockup } from '@/lib/api/mockups'
import { useMockupModal } from './mockup-modal/useMockupModal'
import { ModalHeader } from './mockup-modal/ModalHeader'
import { PreviewArea } from './mockup-modal/PreviewArea'
import { DetailsSidebar } from './mockup-modal/DetailsSidebar'
import { DeleteConfirmDialog } from './mockup-modal/DeleteConfirmDialog'

interface MockupDetailModalProps {
  mockup: Mockup
  projectId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onStatusChange: () => void
}

export function MockupDetailModal({
  mockup,
  projectId,
  open,
  onOpenChange,
  onStatusChange,
}: MockupDetailModalProps) {
  const {
    updating,
    showHistory,
    showComparison,
    showDeleteConfirm,
    history,
    deleteMutation,
    setShowHistory,
    setShowComparison,
    setShowDeleteConfirm,
    handleStatusChange,
  } = useMockupModal(mockup, projectId, open, onOpenChange, onStatusChange)

  if (!open) return null

  const canCompare = hasScreenshot(mockup)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/80"
        onClick={() => onOpenChange(false)}
      />

      <div className="relative bg-slate-900 rounded-xl w-[95vw] max-w-[1600px] h-[90vh] overflow-hidden flex flex-col mx-4">
        <ModalHeader mockup={mockup} onClose={() => onOpenChange(false)} />

        <div className="flex-1 overflow-hidden flex flex-col lg:flex-row min-h-0">
          <PreviewArea
            mockup={mockup}
            projectId={projectId}
            showComparison={showComparison}
            showHistory={showHistory}
            canCompare={canCompare}
            onToggleComparison={() => setShowComparison(!showComparison)}
            onToggleHistory={() => setShowHistory(!showHistory)}
            onDelete={() => setShowDeleteConfirm(true)}
          />

          <DetailsSidebar
            mockup={mockup}
            updating={updating}
            showHistory={showHistory}
            history={history}
            onStatusChange={handleStatusChange}
          />
        </div>

        {showDeleteConfirm && (
          <DeleteConfirmDialog
            mockupName={mockup.name}
            isDeleting={deleteMutation.isPending}
            onConfirm={() => deleteMutation.mutate()}
            onCancel={() => setShowDeleteConfirm(false)}
          />
        )}
      </div>
    </div>
  )
}
