import { ArrowRight } from 'lucide-react'
import Link from 'next/link'

export function FooterCTA(): React.ReactElement {
  return (
    <section className="border-t border-slate-800">
      <div className="max-w-6xl mx-auto px-8 py-16 text-center">
        <h2 className="display text-2xl font-semibold text-white mb-4">
          Ready to transform your development workflow?
        </h2>
        <p className="text-slate-400 mb-8 max-w-lg mx-auto">
          Get started with SummitFlow today and experience the future of
          AI-assisted software development.
        </p>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-lg font-medium text-white transition-all"
          style={{
            background: 'linear-gradient(135deg, #ff6600 0%, #ff0066 100%)',
            boxShadow: '0 0 30px rgba(255, 102, 0, 0.3)',
          }}
        >
          Go to Dashboard
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    </section>
  )
}
