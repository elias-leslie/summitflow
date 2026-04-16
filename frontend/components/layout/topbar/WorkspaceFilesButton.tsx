"use client"

import clsx from 'clsx'
import { FolderTree } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

export function WorkspaceFilesButton() {
  const pathname = usePathname()
  const isActive = pathname === '/files' || pathname.startsWith('/files/')

  return (
    <Link
      href="/files"
      aria-label="Global files"
      title="Global files"
      className={clsx(
        'rounded-lg p-2 transition-all duration-200',
        isActive
          ? 'bg-emerald-500/12 text-emerald-300 shadow-[0_0_0_1px_rgba(52,211,153,0.12)]'
          : 'text-slate-400 hover:bg-slate-800/50 hover:text-emerald-300',
      )}
    >
      <FolderTree className="h-4 w-4" />
    </Link>
  )
}
