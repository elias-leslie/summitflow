'use client'

import { useEffect } from 'react'
import { ProjectRouteErrorState } from '@/components/projects/ProjectRouteStates'

interface ErrorProps {
  error: Error & { digest?: string }
  reset: () => void
}

export default function ProjectsError({ error, reset }: ErrorProps) {
  useEffect(() => {
    console.error('Projects error:', error)
  }, [error])

  return <ProjectRouteErrorState error={error} reset={reset} scope="projects" />
}
