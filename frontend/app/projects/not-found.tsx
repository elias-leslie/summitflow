import { FolderKanban, Home, Search } from 'lucide-react'
import Link from 'next/link'

export default function ProjectsNotFound() {
  return (
    <div className="flex items-center justify-center h-full min-h-[400px] p-6">
      <div className="card p-8 text-center max-w-md">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-amber-500/10 flex items-center justify-center">
          <Search className="w-8 h-8 text-amber-400" />
        </div>
        <h2 className="display text-xl font-semibold text-slate-100 mb-2">
          Project not found
        </h2>
        <p className="text-slate-400 mb-6">
          The project you are looking for does not exist or may have been
          deleted.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Link href="/" className="btn-primary inline-flex items-center gap-2">
            <Home className="w-4 h-4" />
            Dashboard
          </Link>
          <Link
            href="/projects/new"
            className="btn-secondary inline-flex items-center gap-2"
          >
            <FolderKanban className="w-4 h-4" />
            New Project
          </Link>
        </div>
      </div>
    </div>
  )
}
