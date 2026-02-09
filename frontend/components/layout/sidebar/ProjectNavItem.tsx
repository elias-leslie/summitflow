import clsx from 'clsx'
import Link from 'next/link'
import type { NavItemConfig } from './types'

interface ProjectNavItemProps {
  item: NavItemConfig
  href: string
  isActive: boolean
}

export function ProjectNavItem({ item, href, isActive }: ProjectNavItemProps) {
  const Icon = item.icon

  return (
    <Link
      href={href}
      className={clsx(
        'group flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200',
        isActive ? item.activeClasses : item.inactiveClasses,
      )}
    >
      <Icon
        className={clsx(
          'w-4 h-4 flex-shrink-0 transition-colors duration-200',
          isActive ? item.iconActiveClasses : item.iconInactiveClasses,
        )}
      />
      <span className="truncate">{item.label}</span>
    </Link>
  )
}
