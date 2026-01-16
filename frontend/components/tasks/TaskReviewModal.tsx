"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "motion/react";
import { Trash2, Check, Loader2, MessageSquare, FileText } from "lucide-react";
import { Dialog, DialogContent, DialogClose } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { TaskPreview } from "./TaskPreview";
import { DiscussionChat } from "./DiscussionChat";
import {
  acceptTask,
  getSubtasks,
  type Task,
  type Subtask,
} from "@/lib/api/tasks";

interface TaskReviewModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  task: Task;
  onAccept: (task: Task) => void;
  onDiscard: () => void;
}

export function TaskReviewModal({
  open,
  onOpenChange,
  projectId,
  task: initialTask,
  onAccept,
  onDiscard,
}: TaskReviewModalProps) {
  const [task, setTask] = useState<Task>(initialTask);
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [discussionHistory] = useState<never[]>([]);
  const [isAccepting, setIsAccepting] = useState(false);
  const [isDiscarding, setIsDiscarding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"preview" | "chat">("preview");

  // Fetch subtasks when modal opens
  useEffect(() => {
    if (open && task.id) {
      getSubtasks(projectId, task.id)
        .then((response) => {
          setSubtasks(response.subtasks);
        })
        .catch((err) => {
          console.error("Failed to fetch subtasks:", err);
        });
    }
  }, [open, projectId, task.id]);

  // Update task when it changes
  useEffect(() => {
    setTask(initialTask);
  }, [initialTask]);

  const handleTaskUpdated = useCallback(
    (updatedTask: Task) => {
      setTask(updatedTask);
      // Refresh subtasks if task was updated
      getSubtasks(projectId, updatedTask.id)
        .then((response) => {
          setSubtasks(response.subtasks);
        })
        .catch(console.error);
    },
    [projectId],
  );

  const handleAccept = async () => {
    setIsAccepting(true);
    setError(null);

    try {
      const acceptedTask = await acceptTask(projectId, task.id);
      onAccept(acceptedTask);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to accept task");
    } finally {
      setIsAccepting(false);
    }
  };

  const handleDiscard = async () => {
    setIsDiscarding(true);
    // In a real implementation, you'd call an API to delete or reset the task
    // For now, just call the callback
    setTimeout(() => {
      onDiscard();
      onOpenChange(false);
      setIsDiscarding(false);
    }, 300);
  };

  const handleClose = () => {
    if (!isAccepting && !isDiscarding) {
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className="w-full max-w-4xl h-[85vh] flex flex-col p-0 overflow-hidden"
        data-testid="task-review-modal"
      >
        <DialogClose onClose={handleClose} />

        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800">
          <h2 className="text-sm font-mono uppercase tracking-wider text-white">
            Review Task
          </h2>
          <p className="text-xs text-slate-500 mt-1 truncate max-w-lg">
            {task.title || task.raw_request?.slice(0, 60) + "..."}
          </p>
        </div>

        {/* Mobile Tab Switcher */}
        <div className="flex md:hidden border-b border-slate-800">
          <button
            onClick={() => setActiveTab("preview")}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${
              activeTab === "preview"
                ? "text-phosphor-400 border-b-2 border-phosphor-500"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <FileText className="w-4 h-4" />
            Preview
          </button>
          <button
            onClick={() => setActiveTab("chat")}
            className={`flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors ${
              activeTab === "chat"
                ? "text-phosphor-400 border-b-2 border-phosphor-500"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <MessageSquare className="w-4 h-4" />
            Discussion
          </button>
        </div>

        {/* Main Content */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Left Column - Task Preview (hidden on mobile when chat is active) */}
          <motion.div
            className={`${activeTab === "chat" ? "hidden md:flex" : "flex"} flex-col flex-1 md:flex-[3] md:border-r border-slate-800 overflow-hidden`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2 }}
          >
            <div className="flex-1 overflow-y-auto p-6">
              <TaskPreview
                task={task}
                subtasks={subtasks}
                highlightChanges={discussionHistory.length > 0}
              />
            </div>
          </motion.div>

          {/* Right Column - Discussion Chat (hidden on mobile when preview is active) */}
          <motion.div
            className={`${activeTab === "preview" ? "hidden md:flex" : "flex"} flex-col flex-1 md:flex-[2] min-h-0`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2, delay: 0.1 }}
          >
            {/* Desktop Header */}
            <div className="hidden md:flex items-center gap-2 px-4 py-3 border-b border-slate-800">
              <MessageSquare className="w-4 h-4 text-slate-500" />
              <h3 className="text-xs font-mono uppercase tracking-wider text-slate-400">
                Discussion
              </h3>
            </div>
            <div className="flex-1 min-h-0">
              <DiscussionChat
                projectId={projectId}
                taskId={task.id}
                initialHistory={discussionHistory}
                onTaskUpdated={handleTaskUpdated}
              />
            </div>
          </motion.div>
        </div>

        {/* Error */}
        {error && (
          <div className="px-6 py-2">
            <div className="p-2 bg-red-950/50 border border-red-800/50 rounded-md">
              <p className="text-xs text-red-400">{error}</p>
            </div>
          </div>
        )}

        {/* Footer Actions */}
        <div className="flex items-center justify-between gap-4 px-6 py-4 border-t border-slate-800 bg-slate-900/50">
          <Button
            variant="ghost"
            onClick={handleDiscard}
            disabled={isAccepting || isDiscarding}
            className="text-red-400 hover:text-red-300 hover:bg-red-950/30"
          >
            {isDiscarding ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Discarding...
              </>
            ) : (
              <>
                <Trash2 className="w-4 h-4 mr-2" />
                Discard
              </>
            )}
          </Button>

          <Button
            variant="primary"
            onClick={handleAccept}
            disabled={isAccepting || isDiscarding}
          >
            {isAccepting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Accepting...
              </>
            ) : (
              <>
                <Check className="w-4 h-4 mr-2" />
                Accept Task
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
