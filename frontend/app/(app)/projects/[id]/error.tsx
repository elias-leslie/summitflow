'use client'

import { useEffect } from 'react'
import { ProjectRouteErrorState } from '@/components/projects/ProjectRouteStates'

interface ErrorProps {
  error: Error & { digest?: string }
  reset: () => void
}

export default function ProjectDetailError({ error, reset }: ErrorProps) {
  useEffect(() => {
    console.error('Project detail error:', error)
  }, [error])

  return <ProjectRouteErrorState error={error} reset={reset} scope="project" />
}
