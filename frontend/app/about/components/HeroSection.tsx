import { BarChart3, GitBranch, Shield, Target } from 'lucide-react'
import { motion } from 'motion/react'

export function HeroSection(): React.ReactElement {
  return (
    <section className="relative overflow-hidden">
      {/* Atmospheric background */}
      <div className="absolute inset-0 bg-gradient-to-b from-slate-900 via-slate-950 to-slate-950" />
      <div
        className="absolute inset-0 opacity-30"
        style={{
          backgroundImage: `
            radial-gradient(ellipse 80% 50% at 50% -20%, rgba(255, 102, 0, 0.15), transparent),
            radial-gradient(ellipse 60% 40% at 70% 10%, rgba(255, 0, 102, 0.1), transparent)
          `,
        }}
      />

      {/* Grid overlay */}
      <div
        className="absolute inset-0 opacity-20"
        style={{
          backgroundImage: `
            linear-gradient(to right, rgba(255, 0, 102, 0.08) 1px, transparent 1px),
            linear-gradient(to bottom, rgba(255, 0, 102, 0.08) 1px, transparent 1px)
          `,
          backgroundSize: '48px 48px',
          maskImage: 'linear-gradient(to bottom, black 50%, transparent 100%)',
        }}
      />

      <div className="relative z-10 max-w-6xl mx-auto px-8 pt-16 pb-12">
        {/* Logo mark */}
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.6 }}
          className="flex items-center gap-3 mb-8"
        >
          <div
            className="w-12 h-12 rounded-2xl flex items-center justify-center"
            style={{
              background:
                'linear-gradient(135deg, rgba(255, 102, 0, 0.2) 0%, rgba(255, 0, 102, 0.2) 100%)',
              border: '1px solid rgba(255, 102, 0, 0.3)',
              boxShadow: '0 0 30px rgba(255, 102, 0, 0.15)',
            }}
          >
            <Target className="w-6 h-6 text-sunset-orange" />
          </div>
          <span className="text-sm font-medium tracking-widest uppercase text-slate-500">
            AI Development Platform
          </span>
        </motion.div>

        {/* Headline */}
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="display text-5xl md:text-6xl font-bold tracking-tight mb-6"
          style={{
            background: 'linear-gradient(135deg, #ffffff 0%, #94a3b8 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
          }}
        >
          Build Software with
          <br />
          <span
            style={{
              background:
                'linear-gradient(90deg, #fff200 0%, #ff6600 50%, #ff0066 100%)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            Autonomous Intelligence
          </span>
        </motion.h1>

        {/* Subheadline */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="text-xl text-slate-400 max-w-2xl leading-relaxed mb-10"
        >
          SummitFlow orchestrates AI agents to execute development tasks with
          precision. Define your vision, track progress through features and
          tasks, and let intelligent automation handle the implementation.
        </motion.p>

        {/* Trust indicators */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="flex flex-wrap gap-6 text-sm text-slate-500"
        >
          <div className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-phosphor-500" />
            <span>Self-Hosted & Secure</span>
          </div>
          <div className="flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-phosphor-500" />
            <span>Git-Native Workflow</span>
          </div>
          <div className="flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-phosphor-500" />
            <span>Evidence-Based Progress</span>
          </div>
        </motion.div>
      </div>
    </section>
  )
}
