import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  createPullRequest,
  deleteWorktree,
  mergeWorktree,
  pushWorktree,
} from '@/lib/api'

interface UseWorktreeMutationsProps {
  projectId: string
  showToast: (message: string, type: 'success' | 'error') => void
  setDeleteTarget: (target: string | null) => void
  setActiveModal: (modal: null) => void
}

export function useWorktreeMutations({
  projectId,
  showToast,
  setDeleteTarget,
  setActiveModal,
}: UseWorktreeMutationsProps) {
  const queryClient = useQueryClient()

  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteWorktree(projectId, taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worktrees', projectId] })
      setDeleteTarget(null)
      showToast('Worktree deleted', 'success')
    },
    onError: () => showToast('Failed to delete worktree', 'error'),
  })

  const mergeMutation = useMutation({
    mutationFn: (taskId: string) => mergeWorktree(projectId, taskId, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worktrees', projectId] })
      setActiveModal(null)
      showToast('Merged to main successfully', 'success')
    },
    onError: () => showToast('Merge failed - check for conflicts', 'error'),
  })

  const pushMutation = useMutation({
    mutationFn: (taskId: string) => pushWorktree(projectId, taskId),
    onSuccess: (data) => {
      showToast(`Pushed ${data.branch} to origin`, 'success')
    },
    onError: () => showToast('Push failed', 'error'),
  })

  const prMutation = useMutation({
    mutationFn: ({
      taskId,
      title,
      body,
    }: {
      taskId: string
      title: string
      body: string
    }) => createPullRequest(taskId, { title, body }),
    onSuccess: (data) => {
      setActiveModal(null)
      showToast('Pull request created', 'success')
      window.open(data.pr_url, '_blank')
    },
    onError: () => showToast('Failed to create PR', 'error'),
  })

  return {
    deleteMutation,
    mergeMutation,
    pushMutation,
    prMutation,
  }
}
