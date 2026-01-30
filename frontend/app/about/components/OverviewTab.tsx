import { Camera, CheckCircle2, Target } from 'lucide-react'
import { motion } from 'motion/react'

import { ArchitectureDiagram } from './ArchitectureDiagram'
import { ConceptCard } from './ConceptCard'
import { ScreenshotPlaceholder } from './ScreenshotPlaceholder'

export function OverviewTab(): React.ReactElement {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* What is SummitFlow */}
      <div className="grid md:grid-cols-2 gap-12 items-center">
        <div>
          <h2 className="display text-3xl font-semibold text-white mb-4">
            What is SummitFlow?
          </h2>
          <p className="text-slate-400 leading-relaxed mb-6">
            SummitFlow is a task-driven development platform that bridges human
            vision and AI execution. It provides a structured environment where
            AI agents can autonomously work on well-defined tasks while
            maintaining full visibility and control for developers.
          </p>
          <ul className="space-y-3">
            {[
              'Feature-based project organization',
              'Hierarchical task management with dependencies',
              'Evidence capture for verification',
              'Intelligent code exploration',
            ].map((item, i) => (
              <li key={i} className="flex items-center gap-3 text-slate-300">
                <CheckCircle2 className="w-5 h-5 text-phosphor-500 flex-shrink-0" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        {/* Screenshot placeholder */}
        <ScreenshotPlaceholder
          label="Dashboard Overview"
          description="Project cards with task stats and activity feed"
        />
      </div>

      {/* Core Concepts */}
      <div>
        <h2 className="display text-3xl font-semibold text-white mb-8 text-center">
          Core Concepts
        </h2>
        <div className="grid md:grid-cols-3 gap-6">
          <ConceptCard
            icon={<Target className="w-6 h-6" />}
            title="Features"
            description="High-level capabilities with acceptance criteria. Features define what success looks like and group related tasks together."
            color="orange"
          />
          <ConceptCard
            icon={<CheckCircle2 className="w-6 h-6" />}
            title="Tasks"
            description="Actionable work items with clear objectives. Tasks can have dependencies, priorities, and are tracked through their lifecycle."
            color="pink"
          />
          <ConceptCard
            icon={<Camera className="w-6 h-6" />}
            title="Evidence"
            description="Screenshots and artifacts that prove work is complete. Evidence links directly to acceptance criteria for verification."
            color="cyan"
          />
        </div>
      </div>

      {/* Architecture diagram */}
      <div>
        <h2 className="display text-3xl font-semibold text-white mb-8 text-center">
          Architecture
        </h2>
        <ArchitectureDiagram />
      </div>
    </motion.div>
  )
}
