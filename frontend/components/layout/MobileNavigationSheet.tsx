'use client'

import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { getProjectIdFromPathname } from '@/lib/project-config'
import { ProjectsAccordion } from './sidebar/ProjectsAccordion'
import { SidebarHeader } from './sidebar/SidebarHeader'
import { Navigation } from './topbar/Navigation'

interface MobileNavigationSheetProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function MobileNavigationSheet({
  open,
  onOpenChange,
}: MobileNavigationSheetProps) {
  const pathname = usePathname()
  const currentProjectId = getProjectIdFromPathname(pathname)
  const [expandedProjectId, setExpandedProjectId] = useState<string | null>(
    currentProjectId,
  )

  useEffect(() => {
    if (open && currentProjectId) {
      setExpandedProjectId(currentProjectId)
    }
  }, [currentProjectId, open])

  const closeAfterNavigation = (event: React.MouseEvent<HTMLDivElement>) => {
    if ((event.target as Element).closest('a')) {
      onOpenChange(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="left"
        className="max-w-sm border-l-0 border-r border-slate-700/80"
      >
        <div
          id="mobile-navigation"
          className="flex min-h-full flex-col"
          onClickCapture={closeAfterNavigation}
        >
          <SheetHeader className="relative z-10">
            <SheetTitle>Navigation</SheetTitle>
            <SheetDescription>
              Global tools and project workspaces
            </SheetDescription>
            <SheetClose />
          </SheetHeader>

          <SheetBody className="space-y-5 px-3 py-4">
            <section aria-labelledby="mobile-global-navigation-heading">
              <h3
                id="mobile-global-navigation-heading"
                className="section-header mb-2 px-2"
              >
                Global
              </h3>
              <Navigation stacked />
            </section>

            <section
              aria-labelledby="mobile-project-navigation-heading"
              className="border-t border-slate-800/70 pt-2"
            >
              <h3 id="mobile-project-navigation-heading" className="sr-only">
                Project navigation
              </h3>
              <SidebarHeader isCollapsed={false} />
              <ProjectsAccordion
                isCollapsed={false}
                expandedProjectId={expandedProjectId}
                onExpandProject={setExpandedProjectId}
              />
            </section>
          </SheetBody>
        </div>
      </SheetContent>
    </Sheet>
  )
}
