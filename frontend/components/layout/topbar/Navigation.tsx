import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useGitHealth } from '@/hooks/useGitHealth'
import { usePersonaName } from '@/hooks/usePersonaName'
import { GitStatusIndicator } from './GitStatusIndicator'
import { navItems } from './constants'

export function Navigation() {
  const pathname = usePathname()
  const gitHealth = useGitHealth()
  const personaName = usePersonaName()

  return (
    <nav className="hidden lg:flex items-center gap-1 ml-4">
      {navItems.map((item) => {
        const Icon = item.icon
        const isExternal = 'external' in item && item.external
        const isActive =
          !isExternal &&
          (pathname === item.href ||
            (item.href !== '/' && pathname.startsWith(item.href)))

        const activeStyles: Record<string, { bg: string; text: string }> = {
          outrun: { bg: 'bg-outrun-500/15', text: 'text-outrun-400' },
          violet: { bg: 'bg-violet-500/15', text: 'text-violet-400' },
          phosphor: { bg: 'bg-phosphor-500/15', text: 'text-phosphor-400' },
          rose: { bg: 'bg-rose-500/15', text: 'text-rose-400' },
          indigo: { bg: 'bg-indigo-500/15', text: 'text-indigo-400' },
        }
        const ac = activeStyles[item.activeColor] ?? activeStyles.indigo

        const className = clsx(
          'group flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200',
          isActive
            ? `${ac.bg} ${ac.text}`
            : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-300',
        )

        const iconClassName = clsx(
          'w-4 h-4 transition-colors duration-200',
          isActive
            ? ac.text
            : 'text-slate-500 group-hover:text-slate-400',
        )

        const content = (
          <>
            <Icon className={iconClassName} />
            <span>{item.id === 'chat' ? personaName : item.label}</span>
            {item.id === 'git' && <GitStatusIndicator state={gitHealth} />}
            {isExternal && (
              <ExternalLink className="w-3 h-3 text-slate-600 group-hover:text-slate-500" />
            )}
          </>
        )

        if (isExternal) {
          return (
            <a
              key={item.id}
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              className={className}
            >
              {content}
            </a>
          )
        }

        return (
          <Link key={item.id} href={item.href} className={className}>
            {content}
          </Link>
        )
      })}
    </nav>
  )
}
