'use client'

import { MessageSquare } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { ChatPanel } from '@agent-hub/chat-ui'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { TaskSummaryCard } from './TaskSummaryCard'
import { useTaskIdeation } from './useTaskIdeation'
import type { TaskIdeationDialogProps } from './taskIdeationTypes'
import { AGENT_SLUG, CHAT_TITLE } from './taskIdeationTypes'

export type { TaskIdeationDialogProps }

export function TaskIdeationDialog({
  open,
  onOpenChange,
  projectId,
}: TaskIdeationDialogProps) {
  const {
    taskData,
    isSubmitting,
    error,
    apiConfig,
    handleMessagesChange,
    handleClose,
    handleBackToChat,
    handleCreateAndStart,
    updateField,
    handleAddLabel,
    handleRemoveLabel,
  } = useTaskIdeation(projectId, onOpenChange)

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="w-full max-w-4xl h-[80vh] flex flex-col overflow-hidden">
        <DialogClose onClose={handleClose} />
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 font-mono tracking-wider text-sm uppercase">
            <MessageSquare className="w-4 h-4 text-phosphor-400" />
            {CHAT_TITLE}
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 min-h-0 relative">
          <AnimatePresence mode="wait">
            {taskData ? (
              <motion.div
                key="summary"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.2 }}
                className="h-full overflow-y-auto p-5"
              >
                <TaskSummaryCard
                  taskData={taskData}
                  isSubmitting={isSubmitting}
                  error={error}
                  onUpdateField={updateField}
                  onAddLabel={handleAddLabel}
                  onRemoveLabel={handleRemoveLabel}
                  onCreateAndStart={handleCreateAndStart}
                  onBackToChat={handleBackToChat}
                />
              </motion.div>
            ) : (
              <motion.div
                key="chat"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="h-full chat-outrun"
              >
                <ChatPanel
                  agentSlug={AGENT_SLUG}
                  toolsEnabled
                  apiConfig={apiConfig}
                  modelsEndpoint={`${getAgentHubProxyBase()}/models`}
                  title={CHAT_TITLE}
                  onMessagesChange={handleMessagesChange}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </DialogContent>
    </Dialog>
  )
}
