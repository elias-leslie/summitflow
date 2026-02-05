import { FileQuestion, Home } from 'lucide-react'
import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="flex items-center justify-center h-full min-h-[400px] p-6">
      <div className="card p-8 text-center max-w-md">
        <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-amber-500/10 flex items-center justify-center">
          <FileQuestion className="w-8 h-8 text-amber-400" />
        </div>
        <h2 className="display text-xl font-semibold text-white mb-2">
          Page not found
        </h2>
        <p className="text-slate-400 mb-6">
          The page you are looking for does not exist or has been moved.
        </p>
        <Link href="/" className="btn-primary inline-flex items-center gap-2">
          <Home className="w-4 h-4" />
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}
