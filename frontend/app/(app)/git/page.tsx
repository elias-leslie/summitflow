import { Suspense } from 'react'
import { GitClient } from './GitClient'

export default function GitPage() {
  // GitClient reads its filter from the URL (useSearchParams), which needs a Suspense boundary.
  return (
    <Suspense>
      <GitClient />
    </Suspense>
  )
}
