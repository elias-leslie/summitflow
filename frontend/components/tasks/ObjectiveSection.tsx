'use client'

import { AlertTriangle, Check, Pencil, Target, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'

interface ObjectiveSectionProps {
  objective: string | null | undefined
  onEdit?: (text: string) => void
  readOnly?: boolean
}

export function ObjectiveSection({
  objective,
  onEdit,
  readOnly = false,
}: ObjectiveSectionProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(objective || '')

  const handleSave = () => {
    if (onEdit && editValue.trim()) {
      onEdit(editValue.trim())
    }
    setIsEditing(false)
  }

  const handleCancel = () => {
    setEditValue(objective || '')
    setIsEditing(false)
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-phosphor-400" />
          <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
            Objective
          </h4>
        </div>
        {!readOnly && onEdit && !isEditing && objective && (
          <button
            type="button"
            onClick={() => setIsEditing(true)}
            className="p-1 rounded hover:bg-slate-800 text-slate-500 hover:text-slate-300 transition-colors"
          >
            <Pencil className="w-3 h-3" />
          </button>
        )}
      </div>

      <AnimatePresence mode="wait">
        {isEditing ? (
          <motion.div
            key="editor"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="space-y-2"
          >
            <textarea
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              className="w-full px-4 py-3 bg-slate-800 border border-slate-700 rounded-lg
                text-sm text-slate-100 placeholder:text-slate-500 resize-none
                focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
              rows={3}
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={handleCancel}>
                <X className="w-3 h-3 mr-1" />
                Cancel
              </Button>
              <Button size="sm" onClick={handleSave}>
                <Check className="w-3 h-3 mr-1" />
                Save
              </Button>
            </div>
          </motion.div>
        ) : objective ? (
          <motion.div
            key="display"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="p-4 bg-phosphor-500/5 border border-phosphor-500/20 rounded-lg"
          >
            <p className="text-sm text-slate-100 leading-relaxed">{objective}</p>
          </motion.div>
        ) : (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="p-4 bg-amber-500/5 border border-amber-500/20 rounded-lg flex items-center gap-2"
          >
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <p className="text-sm text-amber-400">No objective defined</p>
            {!readOnly && onEdit && (
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                className="ml-auto text-xs text-amber-400 hover:text-amber-300 underline"
              >
                Add one
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  )
}
