'use client'

import { FolderOpen } from 'lucide-react'
import { Breadcrumb, type BreadcrumbItem } from '@/components/ui/breadcrumb'

interface FileBreadcrumbProps {
  rootLabel: string
  rootHref: string
  filePath: string
  className?: string
}

export function FileBreadcrumb({
  rootLabel,
  rootHref,
  filePath,
  className,
}: FileBreadcrumbProps) {
  const isAbsolute = filePath.startsWith('/')
  const segments = filePath.split('/').filter(Boolean)
  const items: BreadcrumbItem[] = [
    {
      label: isAbsolute ? '/' : rootLabel,
      href: rootHref,
      icon: <FolderOpen className="h-3.5 w-3.5" />,
    },
  ]

  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index]
    const isLast = index === segments.length - 1
    const segmentPath = `${isAbsolute ? '/' : ''}${segments
      .slice(0, index + 1)
      .join('/')}`

    items.push({
      label: segment,
      href: isLast
        ? undefined
        : `${rootHref}?path=${encodeURIComponent(segmentPath)}`,
    })
  }

  return <Breadcrumb items={items} className={className} />
}
