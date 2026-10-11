'use client'

import { useParams } from 'next/navigation'
import { UiDesignWorkspace } from '@/components/design/UiDesignWorkspace'

export function DesignClient(): React.ReactElement {
  const params = useParams()
  const projectId = params.id as string

  return (
    <div className="flex h-full flex-col p-4">
      <UiDesignWorkspace projectId={projectId} />
    </div>
  )
}
