'use client'

import { FolderOpen } from 'lucide-react'
import { Breadcrumb, type BreadcrumbItem } from '@/components/ui/breadcrumb'

interface FileBreadcrumbProps {
  projectId: string
  filePath: string
  className?: string
}

export function FileBreadcrumb({
  projectId,
  filePath,
  className,
}: FileBreadcrumbProps) {
  const segments = filePath.split('/')
  const items: BreadcrumbItem[] = [
    {
      label: projectId,
      href: `/projects/${projectId}/files`,
      icon: <FolderOpen className="h-3.5 w-3.5" />,
    },
  ]

  // Build breadcrumb items from path segments
  for (let i = 0; i < segments.length; i++) {
    const segment = segments[i]
    const isLast = i === segments.length - 1
    const segmentPath = segments.slice(0, i + 1).join('/')

    items.push({
      label: segment,
      // Last item has no link (rendered as current page by Breadcrumb)
      href: isLast ? undefined : `/projects/${projectId}/files?path=${encodeURIComponent(segmentPath)}`,
    })
  }

  return <Breadcrumb items={items} className={className} />
}
