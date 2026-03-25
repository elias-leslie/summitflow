'use client'

import { ChevronRight, Home } from 'lucide-react'
import Link from 'next/link'
import clsx from 'clsx'

// ============================================================================
// Types
// ============================================================================

export interface BreadcrumbItem {
  label: string
  href?: string
  icon?: React.ReactNode
}

interface BreadcrumbProps {
  items: BreadcrumbItem[]
  className?: string
}

// ============================================================================
// Breadcrumb Component
// ============================================================================

export function Breadcrumb({ items, className }: BreadcrumbProps) {
  if (items.length === 0) return null

  return (
    <nav
      className={clsx('flex items-center text-sm', className)}
      aria-label="Breadcrumb"
    >
      <ol className="flex items-center gap-1">
        {items.map((item, index) => {
          const isLast = index === items.length - 1

          return (
            <li key={index} className="flex items-center gap-1">
              {/* Separator */}
              {index > 0 && (
                <ChevronRight className="h-3.5 w-3.5 text-slate-600" />
              )}

              {/* Item */}
              {item.href && !isLast ? (
                <Link
                  href={item.href}
                  className="flex items-center gap-1.5 text-slate-400 hover:text-slate-200 transition-colors"
                >
                  {item.icon}
                  <span>{item.label}</span>
                </Link>
              ) : (
                <span
                  className={clsx(
                    'flex items-center gap-1.5',
                    isLast ? 'text-phosphor-400 font-medium' : 'text-slate-400',
                  )}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

// ============================================================================
// Convenience Component for Project Context
// ============================================================================

interface ProjectBreadcrumbProps {
  projectId: string
  projectName?: string
  goalCode?: string | null
  featureName?: string | null
  className?: string
}

export function ProjectBreadcrumb({
  projectId,
  projectName,
  goalCode,
  featureName,
  className,
}: ProjectBreadcrumbProps) {
  const items: BreadcrumbItem[] = [
    {
      label: projectName || projectId,
      href: `/projects/${projectId}`,
      icon: <Home className="h-3.5 w-3.5" />,
    },
  ]

  if (goalCode) {
    items.push({
      label: goalCode,
      href: `/projects/${projectId}/kanban?goal=${goalCode}`,
    })
  }

  if (featureName) {
    items.push({
      label: featureName,
    })
  }

  return <Breadcrumb items={items} className={className} />
}
