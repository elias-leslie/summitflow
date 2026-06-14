'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageSquare, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { fetchAuthMe } from '@/lib/api/auth'
import { formatDate } from '@/lib/format'

export interface ArtifactComment {
  id: number
  author_email: string
  body: string
  created_at: string | null
  updated_at: string | null
}

interface ArtifactCommentsProps {
  queryKey: unknown[]
  fetchComments: () => Promise<ArtifactComment[]>
  addComment: (body: string) => Promise<ArtifactComment>
  updateComment: (commentId: number, body: string) => Promise<ArtifactComment>
  deleteComment: (commentId: number) => Promise<{ deleted: boolean }>
  onChanged?: () => void
}

export function ArtifactComments({
  queryKey,
  fetchComments,
  addComment,
  updateComment,
  deleteComment,
  onChanged,
}: ArtifactCommentsProps): React.ReactElement {
  const [body, setBody] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingBody, setEditingBody] = useState('')
  const queryClient = useQueryClient()
  const { data: me } = useQuery({ queryKey: ['auth-me'], queryFn: fetchAuthMe })
  const { data: comments = [], isLoading } = useQuery({
    queryKey,
    queryFn: fetchComments,
  })

  const refresh = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey })
    onChanged?.()
  }

  const addMutation = useMutation({
    mutationFn: addComment,
    onSuccess: async () => {
      setBody('')
      await refresh()
    },
  })
  const updateMutation = useMutation({
    mutationFn: ({
      commentId,
      nextBody,
    }: {
      commentId: number
      nextBody: string
    }) => updateComment(commentId, nextBody),
    onSuccess: async () => {
      setEditingId(null)
      setEditingBody('')
      await refresh()
    },
  })
  const deleteMutation = useMutation({
    mutationFn: deleteComment,
    onSuccess: refresh,
  })

  const busy =
    addMutation.isPending ||
    updateMutation.isPending ||
    deleteMutation.isPending
  const trimmedBody = body.trim()

  return (
    <section className="mt-5 border-t border-slate-800 pt-5">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-200">
          <MessageSquare className="h-4 w-4 text-cyan-300" />
          Comments
        </h3>
        <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
          {comments.length}
        </span>
      </div>

      <form
        className="mt-3 space-y-2"
        onSubmit={(event) => {
          event.preventDefault()
          if (!trimmedBody) return
          addMutation.mutate(trimmedBody)
        }}
      >
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          placeholder="Add a comment..."
          maxLength={4000}
          className="min-h-20 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:border-cyan-400 focus-visible:outline-none"
        />
        <div className="flex justify-end">
          <button
            type="submit"
            disabled={!trimmedBody || busy}
            className="btn-secondary disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add Comment
          </button>
        </div>
      </form>

      <div className="mt-4 space-y-3">
        {isLoading && (
          <p className="text-sm text-slate-500">Loading comments…</p>
        )}
        {!isLoading && comments.length === 0 && (
          <p className="text-sm text-slate-500">No comments yet.</p>
        )}
        {comments.map((comment) => {
          const canEdit = me?.email === comment.author_email
          const isEditing = editingId === comment.id

          return (
            <article key={comment.id} className="rounded-xl bg-slate-950 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs text-cyan-200">
                    {comment.author_email}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {comment.created_at
                      ? formatDate(comment.created_at)
                      : 'Just now'}
                  </p>
                </div>
                {canEdit && (
                  <div className="flex flex-shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(comment.id)
                        setEditingBody(comment.body)
                      }}
                      disabled={busy}
                      aria-label="Edit comment"
                      className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100 disabled:opacity-50"
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate(comment.id)}
                      disabled={busy}
                      aria-label="Delete comment"
                      className="rounded p-1 text-slate-400 hover:bg-rose-500/10 hover:text-rose-200 disabled:opacity-50"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                )}
              </div>

              {isEditing ? (
                <form
                  className="mt-3 space-y-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const nextBody = editingBody.trim()
                    if (!nextBody) return
                    updateMutation.mutate({ commentId: comment.id, nextBody })
                  }}
                >
                  <textarea
                    value={editingBody}
                    onChange={(event) => setEditingBody(event.target.value)}
                    maxLength={4000}
                    className="min-h-20 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus-visible:border-cyan-400 focus-visible:outline-none"
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(null)
                        setEditingBody('')
                      }}
                      className="btn-secondary"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={!editingBody.trim() || busy}
                      className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Save
                    </button>
                  </div>
                </form>
              ) : (
                <p className="mt-3 whitespace-pre-wrap text-sm text-slate-200">
                  {comment.body}
                </p>
              )}
            </article>
          )
        })}
      </div>
    </section>
  )
}
