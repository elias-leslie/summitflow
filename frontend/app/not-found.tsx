import { FileQuestion, Home } from 'lucide-react'
import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="flex items-center justify-center h-full min-h-[400px] p-6">
      <div className="card-elevated p-10 text-center max-w-md relative overflow-hidden">
        {/* Atmospheric glow behind icon */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-32 bg-outrun-500/8 rounded-full blur-3xl pointer-events-none" />
        <div className="relative">
          <div className="w-18 h-18 mx-auto mb-5 rounded-2xl bg-outrun-500/10 border border-outrun-500/20 flex items-center justify-center animate-in stagger-1">
            <FileQuestion className="w-9 h-9 text-outrun-400" />
          </div>
          <h2 className="display text-2xl font-bold text-slate-100 mb-2 tracking-tight animate-in stagger-2">
            Page not found
          </h2>
          <p className="text-sm text-slate-400 mb-8 leading-relaxed animate-in stagger-3">
            The page you are looking for does not exist or has been moved.
          </p>
          <Link
            href="/"
            className="btn-primary inline-flex items-center gap-2 animate-in stagger-4"
          >
            <Home className="w-4 h-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    </div>
  )
}
