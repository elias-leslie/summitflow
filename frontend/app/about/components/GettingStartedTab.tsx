import { CheckCircle2 } from 'lucide-react'
import { motion } from 'motion/react'

import { ScreenshotPlaceholder } from './ScreenshotPlaceholder'

const commands = [
  {
    title: 'Find available work',
    command: 'st ready',
    description: 'List tasks that are ready to be worked on',
  },
  {
    title: 'Claim a task',
    command: 'st update <id> --status running',
    description: 'Mark a task as in progress',
  },
  {
    title: 'Complete a task',
    command: 'st close <id> --reason "Done"',
    description: 'Close with a summary of what was done',
  },
]

const setupSteps = [
  { step: 'Install and configure services', done: true },
  { step: 'Create your first project', done: true },
  { step: 'Define features with acceptance criteria', done: false },
  { step: 'Break features into tasks', done: false },
  { step: 'Run your first AI agent session', done: false },
]

export function GettingStartedTab(): React.ReactElement {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.3 }}
      className="space-y-16"
    >
      {/* Quick start guide */}
      <div className="grid md:grid-cols-2 gap-12">
        <div>
          <h2 className="display text-3xl font-semibold text-white mb-4">
            Quick Start
          </h2>
          <p className="text-slate-400 leading-relaxed mb-8">
            SummitFlow uses a CLI tool called{' '}
            <code className="mono text-phosphor-400 bg-slate-800 px-2 py-0.5 rounded">
              st
            </code>{' '}
            for task management. Here are the essential commands to get started.
          </p>

          <div className="space-y-4">
            {commands.map((cmd, i) => (
              <motion.div
                key={cmd.command}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                className="p-4 rounded-lg border border-slate-800 bg-slate-900/50"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-white">
                    {cmd.title}
                  </span>
                </div>
                <code className="mono text-sm text-phosphor-400 block mb-2">
                  {cmd.command}
                </code>
                <p className="text-xs text-slate-500">{cmd.description}</p>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Terminal preview */}
        <ScreenshotPlaceholder
          label="Terminal Interface"
          description="Integrated terminal with command history and output"
          dark
        />
      </div>

      {/* Setup steps */}
      <div>
        <h2 className="display text-2xl font-semibold text-white mb-8 text-center">
          Setup Checklist
        </h2>
        <div className="max-w-2xl mx-auto space-y-4">
          {setupSteps.map((item, i) => (
            <motion.div
              key={item.step}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.1 }}
              className={`
                flex items-center gap-4 p-4 rounded-lg border transition-colors
                ${
                  item.done
                    ? 'border-phosphor-500/30 bg-phosphor-500/5'
                    : 'border-slate-800 bg-slate-900/50'
                }
              `}
            >
              <div
                className={`
                w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0
                ${
                  item.done
                    ? 'bg-phosphor-500/20 text-phosphor-400'
                    : 'bg-slate-800 text-slate-600'
                }
              `}
              >
                {item.done ? (
                  <CheckCircle2 className="w-4 h-4" />
                ) : (
                  <span className="text-xs font-medium">{i + 1}</span>
                )}
              </div>
              <span className={item.done ? 'text-slate-300' : 'text-slate-500'}>
                {item.step}
              </span>
            </motion.div>
          ))}
        </div>
      </div>
    </motion.div>
  )
}
