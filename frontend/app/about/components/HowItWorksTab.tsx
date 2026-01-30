import { CheckCircle2, Layers, Target, Terminal } from 'lucide-react'
import { motion } from 'motion/react'

import { WorkflowVisualization } from './WorkflowVisualization'

const steps = [
  {
    number: '01',
    title: 'Define Your Vision',
    description:
      'Start by creating a project and defining features with clear acceptance criteria. This provides the structure AI agents need to work effectively.',
    icon: <Target className="w-5 h-5" />,
  },
  {
    number: '02',
    title: 'Create Tasks',
    description:
      'Break features into tasks with priorities and dependencies. Use labels for complexity and domain to help agents understand the work.',
    icon: <Layers className="w-5 h-5" />,
  },
  {
    number: '03',
    title: 'AI Execution',
    description:
      'AI agents claim tasks, execute implementation, and capture evidence. The integrated terminal provides full visibility into agent actions.',
    icon: <Terminal className="w-5 h-5" />,
  },
  {
    number: '04',
    title: 'Review & Verify',
    description:
      'Review captured evidence against acceptance criteria. Approve, request changes, or provide feedback to guide further development.',
    icon: <CheckCircle2 className="w-5 h-5" />,
  },
]

export function HowItWorksTab(): React.ReactElement {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* Workflow steps */}
      <div className="relative">
        {/* Connecting line */}
        <div
          className="absolute left-8 top-16 bottom-16 w-px hidden md:block"
          style={{
            background: 'linear-gradient(to bottom, #ff6600, #ff0066)',
            opacity: 0.3,
          }}
        />

        <div className="space-y-12">
          {steps.map((step, i) => (
            <motion.div
              key={step.number}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className="flex gap-8 items-start"
            >
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center flex-shrink-0 relative z-10"
                style={{
                  background:
                    'linear-gradient(135deg, rgba(255, 102, 0, 0.15) 0%, rgba(255, 0, 102, 0.15) 100%)',
                  border: '1px solid rgba(255, 102, 0, 0.2)',
                }}
              >
                <span
                  className="text-xl font-bold"
                  style={{
                    background:
                      'linear-gradient(135deg, #ff6600 0%, #ff0066 100%)',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                  }}
                >
                  {step.number}
                </span>
              </div>
              <div className="flex-1 pt-2">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-sunset-orange">{step.icon}</span>
                  <h3 className="display text-xl font-semibold text-white">
                    {step.title}
                  </h3>
                </div>
                <p className="text-slate-400 leading-relaxed max-w-xl">
                  {step.description}
                </p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Workflow visualization */}
      <div>
        <h2 className="display text-2xl font-semibold text-white mb-8 text-center">
          Task Lifecycle
        </h2>
        <WorkflowVisualization />
      </div>
    </motion.div>
  )
}
