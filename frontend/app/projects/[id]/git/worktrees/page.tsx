'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import type { WorktreeInfo } from '@/lib/api'
import { CleanupModal } from './components/CleanupModal'
import { DiffModal } from './components/DiffModal'
import { EmptyState } from './components/EmptyState'
import { ErrorState } from './components/ErrorState'
import { LoadingSpinner } from './components/LoadingSpinner'
import { MergeModal } from './components/MergeModal'
import { PageHeader } from './components/PageHeader'
import { PRModal } from './components/PRModal'
import { Toast } from './components/Toast'
import { WorktreeCard } from './components/WorktreeCard'
import { useToast } from './hooks/useToast'
import { useWorktreeMutations } from './hooks/useWorktreeMutations'
import { useWorktrees } from './hooks/useWorktrees'

type ModalType = 'diff' | 'merge' | 'pr' | 'cleanup' | null

export default function WorktreesPage() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()
  const { toast, showToast } = useToast()
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [activeModal, setActiveModal] = useState<ModalType>(null)
  const [selectedWorktree, setSelectedWorktree] = useState<WorktreeInfo | null>(
    null,
  )

  const {
    data: worktreesData,
    isLoading,
    error,
    refetch,
  } = useWorktrees(projectId)

  const { deleteMutation, mergeMutation, pushMutation, prMutation } =
    useWorktreeMutations({
      projectId,
      showToast,
      setDeleteTarget,
      setActiveModal,
    })

  const handleDelete = (taskId: string) => {
    if (deleteTarget === taskId) {
      deleteMutation.mutate(taskId)
    } else {
      setDeleteTarget(taskId)
      setTimeout(() => setDeleteTarget(null), 3000)
    }
  }

  const openModal = (modal: ModalType, worktree?: WorktreeInfo) => {
    setActiveModal(modal)
    if (worktree) setSelectedWorktree(worktree)
  }

  const handleCleanupSuccess = () => {
    queryClient.invalidateQueries({ queryKey: ['worktrees', projectId] })
    showToast('Cleanup complete', 'success')
  }

  if (isLoading) {
    return <LoadingSpinner />
  }

  if (error) {
    return <ErrorState onRetry={() => refetch()} />
  }

  const worktrees = worktreesData?.worktrees ?? []

  return (
    <div className="p-6 space-y-6">
      {toast && <Toast message={toast.message} type={toast.type} />}

      <PageHeader
        projectId={projectId}
        worktreeCount={worktrees.length}
        onCleanup={() => openModal('cleanup')}
      />

      {worktrees.length > 0 ? (
        <section className="space-y-3">
          {worktrees.map((wt) => (
            <WorktreeCard
              key={wt.task_id}
              worktree={wt}
              projectId={projectId}
              deleteTarget={deleteTarget}
              onDelete={handleDelete}
              isDeleting={
                deleteMutation.isPending && deleteTarget === wt.task_id
              }
              onViewDiff={() => openModal('diff', wt)}
              onMerge={() => openModal('merge', wt)}
              onPush={() => pushMutation.mutate(wt.task_id)}
              onCreatePR={() => openModal('pr', wt)}
              isPushing={pushMutation.isPending}
            />
          ))}
        </section>
      ) : (
        <EmptyState />
      )}

      {activeModal === 'diff' && selectedWorktree && (
        <DiffModal
          projectId={projectId}
          worktree={selectedWorktree}
          onClose={() => setActiveModal(null)}
        />
      )}

      {activeModal === 'merge' && selectedWorktree && (
        <MergeModal
          worktree={selectedWorktree}
          onClose={() => setActiveModal(null)}
          onConfirm={() => mergeMutation.mutate(selectedWorktree.task_id)}
          isPending={mergeMutation.isPending}
        />
      )}

      {activeModal === 'pr' && selectedWorktree && (
        <PRModal
          worktree={selectedWorktree}
          onClose={() => setActiveModal(null)}
          onConfirm={(title, body) =>
            prMutation.mutate({
              taskId: selectedWorktree.task_id,
              title,
              body,
            })
          }
          isPending={prMutation.isPending}
        />
      )}

      {activeModal === 'cleanup' && (
        <CleanupModal
          projectId={projectId}
          onClose={() => setActiveModal(null)}
          onSuccess={handleCleanupSuccess}
        />
      )}
    </div>
  )
}
