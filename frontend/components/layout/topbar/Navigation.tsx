import clsx from 'clsx'
import { ExternalLink } from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useGitHealth } from '@/hooks/useGitHealth'
import { usePersonaName } from '@/hooks/usePersonaName'
import { navItems } from './constants'
import { GitStatusIndicator } from './GitStatusIndicator'

export function Navigation({ compact = false }: { compact?: boolean }) {
  const pathname = usePathname()
  const gitHealth = useGitHealth()
  const personaName = usePersonaName()
  const labelClassName = compact ? 'hidden' : 'hidden lg:inline'
  const externalIconClassName = compact ? 'hidden' : 'hidden lg:block'

  return (
    <nav
      className={clsx(
        'flex min-w-0 w-full items-center justify-center gap-1 overflow-hidden transition-all duration-300',
        compact ? 'max-w-sm lg:max-w-md' : 'max-w-md lg:max-w-lg',
      )}
    >
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
          cyan: { bg: 'bg-cyan-500/15', text: 'text-cyan-400' },
        }
        const ac = activeStyles[item.activeColor] ?? activeStyles.indigo

        const label = item.id === 'chat' ? personaName : item.label

        const className = clsx(
          'group flex items-center gap-2 rounded-lg text-sm font-medium transition-all duration-200',
          compact ? 'p-2' : 'p-2 lg:px-3 lg:py-1.5',
          isActive
            ? `${ac.bg} ${ac.text}`
            : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-300',
        )

        const iconClassName = clsx(
          'w-4 h-4 transition-colors duration-200',
          isActive ? ac.text : 'text-slate-500 group-hover:text-slate-400',
        )

        const content = (
          <>
            <Icon className={iconClassName} />
            <span className={labelClassName}>{label}</span>
            {item.id === 'git' && <GitStatusIndicator state={gitHealth} />}
            {isExternal && (
              <ExternalLink
                className={clsx(
                  'h-3 w-3 text-slate-600 group-hover:text-slate-500',
                  externalIconClassName,
                )}
              />
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
              title={label}
            >
              {content}
            </a>
          )
        }

        return (
          <Link
            key={item.id}
            href={item.href}
            className={className}
            title={label}
          >
            {content}
          </Link>
        )
      })}
    </nav>
  )
}
