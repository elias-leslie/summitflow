import { FolderKanban } from 'lucide-react'

interface SidebarHeaderProps {
  isCollapsed: boolean
}

export function SidebarHeader({ isCollapsed }: SidebarHeaderProps) {
  if (isCollapsed) {
    return (
      <div className="flex items-center justify-center py-3">
        <FolderKanban className="w-5 h-5 text-outrun-400" />
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2.5 px-3 py-3">
      <div className="rounded-md p-1 bg-outrun-500/8">
        <FolderKanban className="w-4 h-4 text-outrun-400" />
      </div>
      <span className="text-xs font-semibold tracking-[0.12em] uppercase text-slate-400 display">
        Projects
      </span>
    </div>
  )
}
