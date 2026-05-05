'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { HardDrive, Loader2, Plus } from 'lucide-react'
import Link from 'next/link'
import { StorageBackendCard } from '@/components/backup/StorageBackendCard'
import { fetchStorageBackends } from '@/lib/api/backups'

export default function StorageBackendsPage() {
  const queryClient = useQueryClient()
  const { data: backends, isLoading } = useQuery({
    queryKey: ['storage-backends'],
    queryFn: fetchStorageBackends,
  })

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['storage-backends'] })
  }

  return (
    <main className="content-container py-8">
      <header className="mb-8 flex items-start justify-between hero-glow">
        <div className="relative z-10">
          <h1 className="text-2xl font-bold text-slate-100 display tracking-tight flex items-center gap-3">
            <HardDrive className="w-6 h-6 text-slate-400" />
            Storage Backends
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage where backups are stored
          </p>
        </div>
        <Link
          href="/backups/setup"
          className="relative z-10 flex items-center gap-2 btn-primary text-sm"
        >
          <Plus className="w-4 h-4" />
          Add Backend
        </Link>
      </header>

      {isLoading ? (
        <div className="flex items-center justify-center h-48">
          <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
        </div>
      ) : !backends?.length ? (
        <div className="p-12 bg-slate-800/50 rounded-lg border border-slate-700 text-center">
          <HardDrive className="w-12 h-12 text-slate-500 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-slate-300 mb-2">
            No storage backends
          </h3>
          <p className="text-slate-400 mb-4">
            Set up a storage backend to start writing backups to SMB or a local
            path.
          </p>
          <Link
            href="/backups/setup"
            className="btn-primary inline-flex items-center gap-2 text-sm"
          >
            <Plus className="w-4 h-4" />
            Set up storage
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {backends.map((backend) => (
            <StorageBackendCard
              key={backend.id}
              backend={backend}
              onRefresh={handleRefresh}
            />
          ))}
        </div>
      )}
    </main>
  )
}
