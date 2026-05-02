'use client'

import clsx from 'clsx'
import { Database } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { MouseEvent } from 'react'

export function DatabaseWorkbenchButton() {
  const pathname = usePathname()
  const isActive = pathname === '/database'

  const openWorkbench = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    const popup = window.open(
      '/database',
      'summitflow-db-workbench',
      'popup,width=1480,height=940,left=80,top=40',
    )
    if (popup) {
      popup.focus()
      return
    }
    window.location.href = '/database'
  }

  return (
    <Link
      href="/database"
      aria-label="Database workbench"
      title="Database workbench"
      onClick={openWorkbench}
      className={clsx(
        'rounded-lg p-2 transition-all duration-200',
        isActive
          ? 'bg-emerald-500/12 text-emerald-300 shadow-[0_0_0_1px_rgba(52,211,153,0.12)]'
          : 'text-slate-400 hover:bg-slate-800/50 hover:text-emerald-300',
      )}
    >
      <Database className="h-4 w-4" />
    </Link>
  )
}
