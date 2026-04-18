'use client'

import { Edit2, Save, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface EditDeleteActionsProps {
  isEditing: boolean
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onDelete?: () => void
}

export function EditDeleteActions({
  isEditing,
  onEditStart,
  onEditCancel,
  onEditSave,
  onDelete,
}: EditDeleteActionsProps) {
  return (
    <div className="ml-auto flex items-center gap-2">
      {isEditing ? (
        <>
          <Button
            variant="outline"
            size="sm"
            onClick={onEditCancel}
            aria-label="Cancel edit"
          >
            <X className="h-4 w-4" />
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={onEditSave}
            aria-label="Save changes"
          >
            <Save className="h-4 w-4" />
          </Button>
        </>
      ) : (
        <>
          <Button
            variant="outline"
            size="sm"
            onClick={onEditStart}
            aria-label="Edit task"
          >
            <Edit2 className="h-4 w-4" />
          </Button>
          {onDelete && (
            <Button
              variant="outline"
              size="sm"
              onClick={onDelete}
              className="border-red-600 text-red-400 hover:bg-red-500/20"
              aria-label="Delete task"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </>
      )}
    </div>
  )
}
