'use client'

import { ArrowLeft, CheckCircle2, Loader2, Rocket, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { TaskType } from '@/lib/api/tasks-types'
import {
  COMPLEXITY_OPTIONS,
  PRIORITY_OPTIONS,
  TYPE_OPTIONS,
} from './taskIdeationTypes'
import type { Complexity, TaskSummaryCardProps } from './taskIdeationTypes'

function ComplexityBadge({ complexity }: { complexity: Complexity }) {
  const variantMap: Record<Complexity, 'phosphor' | 'amber' | 'rose'> = {
    simple: 'phosphor',
    standard: 'amber',
    complex: 'rose',
  }
  return <Badge variant={variantMap[complexity]}>{complexity}</Badge>
}

function PriorityBadge({ priority }: { priority: number }) {
  const labels: Record<number, string> = { 0: 'P0', 1: 'P1', 2: 'P2', 3: 'P3', 4: 'P4' }
  const variants: Record<number, 'rose' | 'amber' | 'default' | 'slate'> = {
    0: 'rose',
    1: 'amber',
    2: 'default',
    3: 'slate',
    4: 'slate',
  }
  return (
    <Badge variant={variants[priority] ?? 'default'}>
      {labels[priority] ?? `P${priority}`}
    </Badge>
  )
}

export function TaskSummaryCard({
  taskData,
  isSubmitting,
  error,
  onUpdateField,
  onAddLabel,
  onRemoveLabel,
  onCreateAndStart,
  onBackToChat,
}: TaskSummaryCardProps) {
  const [newLabel, setNewLabel] = useState('')

  const handleLabelKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      onAddLabel(newLabel)
      setNewLabel('')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <CheckCircle2 className="w-5 h-5 text-phosphor-400" />
        <h3 className="text-lg font-semibold text-slate-100">Task Ready for Creation</h3>
      </div>

      <div className="rounded-lg border border-phosphor-500/20 bg-slate-800/50 p-5 space-y-5">
        <div className="space-y-2">
          <Label htmlFor="ideation-title">Title</Label>
          <Input
            id="ideation-title"
            value={taskData.title}
            onChange={(e) => onUpdateField('title', e.target.value)}
            disabled={isSubmitting}
            placeholder="Task title"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="ideation-description">Description</Label>
          <Textarea
            id="ideation-description"
            value={taskData.description}
            onChange={(e) => onUpdateField('description', e.target.value)}
            disabled={isSubmitting}
            rows={6}
            placeholder="Task description"
          />
        </div>

        <div className="grid grid-cols-3 gap-4">
          <div className="space-y-2">
            <Label>Priority</Label>
            <Select
              value={String(taskData.priority)}
              onValueChange={(v) => onUpdateField('priority', parseInt(v, 10))}
              disabled={isSubmitting}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRIORITY_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Type</Label>
            <Select
              value={taskData.task_type}
              onValueChange={(v) => onUpdateField('task_type', v as TaskType)}
              disabled={isSubmitting}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Complexity</Label>
            <Select
              value={taskData.complexity}
              onValueChange={(v) => onUpdateField('complexity', v as Complexity)}
              disabled={isSubmitting}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMPLEXITY_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-2">
          <Label>Labels</Label>
          <div className="flex flex-wrap gap-2 min-h-[32px]">
            {taskData.labels.map((label) => (
              <Badge
                key={label}
                variant="outline"
                className="gap-1"
                onClick={isSubmitting ? undefined : () => onRemoveLabel(label)}
              >
                {label}
                {!isSubmitting && <X className="w-3 h-3" />}
              </Badge>
            ))}
          </div>
          <Input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            onKeyDown={handleLabelKeyDown}
            disabled={isSubmitting}
            placeholder="Type a label and press Enter"
            className="mt-1"
          />
        </div>

        <div className="flex items-center gap-3 pt-2">
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <PriorityBadge priority={taskData.priority} />
            <Badge variant="default">{taskData.task_type}</Badge>
            <ComplexityBadge complexity={taskData.complexity} />
          </div>
        </div>
      </div>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="p-3 bg-red-950/50 border border-red-800/50 rounded-md"
          >
            <p className="text-sm text-red-400">{error}</p>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex gap-3">
        <Button variant="ghost" onClick={onBackToChat} disabled={isSubmitting}>
          <ArrowLeft className="w-4 h-4" />
          Back to Chat
        </Button>
        <div className="flex-1" />
        <Button
          variant="primary"
          onClick={onCreateAndStart}
          disabled={isSubmitting || !taskData.title.trim()}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Creating...
            </>
          ) : (
            <>
              <Rocket className="w-4 h-4" />
              Create & Start
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
