'use client'

import { useParams } from 'next/navigation'
import { DatabaseWorkbench } from '@/components/database/DatabaseWorkbench'

export function DatabaseWorkbenchClient() {
  const params = useParams<{ id: string }>()
  return <DatabaseWorkbench projectId={params.id} />
}
