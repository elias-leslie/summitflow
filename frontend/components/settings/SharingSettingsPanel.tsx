'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Trash2, UserPlus } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  deleteShareUser,
  fetchShareUsers,
  type ShareUser,
  setShareUserProjectGrants,
  upsertShareUser,
} from '@/lib/api/auth'
import { getErrorMessage } from '@/lib/utils'

interface SharingSettingsPanelProps {
  projectId: string
}

function hasDesignGrant(user: ShareUser, projectId: string): boolean {
  return user.grants.some(
    (grant) => grant.project_id === projectId && grant.section === 'design',
  )
}

export function SharingSettingsPanel({
  projectId,
}: SharingSettingsPanelProps): React.ReactElement {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<'viewer' | 'owner'>('viewer')
  const [error, setError] = useState<string | null>(null)

  const { data: users, isLoading } = useQuery({
    queryKey: ['share-users'],
    queryFn: fetchShareUsers,
  })

  const viewers = useMemo(
    () => (users ?? []).filter((user) => user.role === 'viewer'),
    [users],
  )
  const owners = useMemo(
    () => (users ?? []).filter((user) => user.role === 'owner'),
    [users],
  )

  const refreshUsers = () =>
    queryClient.invalidateQueries({ queryKey: ['share-users'] })

  const upsertMutation = useMutation({
    mutationFn: () =>
      upsertShareUser({
        email: email.trim(),
        role,
        is_active: true,
      }),
    onSuccess: async () => {
      setEmail('')
      setRole('viewer')
      setError(null)
      await refreshUsers()
    },
    onError: (mutationError) => {
      setError(getErrorMessage(mutationError, 'Failed to save user'))
    },
  })

  const grantMutation = useMutation({
    mutationFn: ({ user, enabled }: { user: ShareUser; enabled: boolean }) =>
      setShareUserProjectGrants(
        user.email,
        projectId,
        enabled ? ['design'] : [],
      ),
    onSuccess: async () => {
      setError(null)
      await refreshUsers()
    },
    onError: (mutationError) => {
      setError(getErrorMessage(mutationError, 'Failed to save sharing grant'))
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (targetEmail: string) => deleteShareUser(targetEmail),
    onSuccess: async () => {
      setError(null)
      await refreshUsers()
    },
    onError: (mutationError) => {
      setError(getErrorMessage(mutationError, 'Failed to delete user'))
    },
  })

  if (isLoading) {
    return (
      <div className="card flex items-center justify-center p-8 text-slate-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading sharing settings...
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <section className="card rounded-xl p-6">
        <h2 className="text-base font-semibold text-slate-100">
          Add shared user
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Users authenticate through Cloudflare Access. SummitFlow uses this
          table to decide whether they are owners or read-only viewers.
        </p>

        {error && (
          <div className="mt-4 rounded-lg border border-rose-500/20 bg-rose-500/10 p-3 text-sm text-rose-300">
            {error}
          </div>
        )}

        <div className="mt-5 grid gap-3 md:grid-cols-[minmax(0,1fr)_160px_auto]">
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="brother@gmail.com"
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
          />
          <select
            value={role}
            onChange={(event) =>
              setRole(event.target.value as 'viewer' | 'owner')
            }
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
          >
            <option value="viewer">Viewer</option>
            <option value="owner">Owner</option>
          </select>
          <button
            type="button"
            onClick={() => upsertMutation.mutate()}
            disabled={!email.trim() || upsertMutation.isPending}
            className="btn-primary inline-flex items-center justify-center gap-2 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {upsertMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <UserPlus className="h-4 w-4" />
            )}
            Save user
          </button>
        </div>
      </section>

      <section className="card rounded-xl p-6">
        <h2 className="text-base font-semibold text-slate-100">
          Viewers for this project
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Design is the only shareable section in this first version.
        </p>

        <div className="mt-5 space-y-3">
          {viewers.length === 0 && (
            <div className="rounded-lg border border-dashed border-slate-700 p-4 text-sm text-slate-500">
              No viewers yet.
            </div>
          )}
          {viewers.map((user) => {
            const enabled = hasDesignGrant(user, projectId)
            return (
              <div
                key={user.email}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-3"
              >
                <div>
                  <p className="font-mono text-sm text-slate-100">
                    {user.email}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {user.is_active ? 'Active viewer' : 'Inactive viewer'}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(event) =>
                        grantMutation.mutate({
                          user,
                          enabled: event.target.checked,
                        })
                      }
                    />
                    Design
                  </label>
                  <button
                    type="button"
                    onClick={() => deleteMutation.mutate(user.email)}
                    disabled={deleteMutation.isPending}
                    className="btn-secondary inline-flex items-center gap-2 text-rose-300"
                  >
                    <Trash2 className="h-4 w-4" />
                    Remove
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </section>

      <section className="card rounded-xl p-6">
        <h2 className="text-base font-semibold text-slate-100">Owners</h2>
        <div className="mt-3 space-y-2">
          {owners.map((user) => (
            <div
              key={user.email}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-950/50 p-3"
            >
              <span className="font-mono text-sm text-slate-200">
                {user.email}
              </span>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(user.email)}
                disabled={deleteMutation.isPending}
                className="inline-flex items-center gap-2 text-sm text-rose-300 hover:text-rose-200 disabled:opacity-50"
              >
                Remove owner
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
