import {
  Camera,
  CheckCircle2,
  FileCode2,
  Layers,
  Terminal,
  Users,
} from 'lucide-react'
import { motion } from 'motion/react'

import { FeatureCard } from './FeatureCard'
import { ScreenshotPlaceholder } from './ScreenshotPlaceholder'

const features = [
  {
    icon: <Layers className="w-6 h-6" />,
    title: 'Feature Management',
    description:
      'Organize work into features with acceptance criteria. Track progress as tasks complete and evidence is captured.',
    color: 'orange',
  },
  {
    icon: <CheckCircle2 className="w-6 h-6" />,
    title: 'Task Tracking',
    description:
      'Hierarchical tasks with dependencies, priorities, and labels. Full lifecycle management from creation to completion.',
    color: 'pink',
  },
  {
    icon: <FileCode2 className="w-6 h-6" />,
    title: 'Code Explorer',
    description:
      'Navigate your codebase with intelligent analysis. View files, database tables, API endpoints, and Celery tasks.',
    color: 'cyan',
  },
  {
    icon: <Camera className="w-6 h-6" />,
    title: 'Evidence Capture',
    description:
      'Screenshot and artifact capture linked to acceptance criteria. Version-controlled evidence for verification.',
    color: 'yellow',
  },
  {
    icon: <Terminal className="w-6 h-6" />,
    title: 'Integrated Terminal',
    description:
      'Full terminal access with command history. Execute CLI commands, run tests, and interact with your project.',
    color: 'purple',
  },
  {
    icon: <Users className="w-6 h-6" />,
    title: 'Multi-Project Support',
    description:
      'Manage multiple projects from a single dashboard. Each project has isolated configuration and task tracking.',
    color: 'green',
  },
]

export function FeaturesTab(): React.ReactElement {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* Feature grid */}
      <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
        {features.map((feature, i) => (
          <motion.div
            key={feature.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <FeatureCard {...feature} />
          </motion.div>
        ))}
      </div>

      {/* Feature showcase */}
      <div>
        <h2 className="display text-2xl font-semibold text-white mb-8 text-center">
          Feature Showcase
        </h2>
        <div className="grid md:grid-cols-2 gap-8">
          <ScreenshotPlaceholder
            label="Kanban Board"
            description="Visual task management with drag-and-drop"
          />
          <ScreenshotPlaceholder
            label="Evidence Gallery"
            description="Browse and review captured screenshots"
          />
        </div>
      </div>
    </motion.div>
  )
}
