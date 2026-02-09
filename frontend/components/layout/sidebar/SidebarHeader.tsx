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
    <div className="flex items-center gap-2 px-3 py-3">
      <FolderKanban className="w-5 h-5 text-outrun-400" />
      <span className="text-sm font-semibold tracking-wide uppercase text-slate-300">
        Projects
      </span>
    </div>
  )
}
