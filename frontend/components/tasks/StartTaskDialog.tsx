"use client";

import { useState } from "react";
import { clsx } from "clsx";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { TaskLogViewer } from "./TaskLogViewer";
import {
  createTask,
  startTask,
  type Feature,
  type Task,
  type AgentType,
} from "@/lib/api";
import { Bot, Sparkles, Loader2, CheckCircle } from "lucide-react";

interface StartTaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  feature: Feature;
}

type DialogState = "configure" | "running" | "complete";

export function StartTaskDialog({
  open,
  onOpenChange,
  projectId,
  feature,
}: StartTaskDialogProps) {
  const [agent, setAgent] = useState<AgentType>("gemini");
  const [allowDelegation, setAllowDelegation] = useState(false);
  const [state, setState] = useState<DialogState>("configure");
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleStart = async () => {
    setLoading(true);
    setError(null);

    try {
      // 1. Create the task
      const newTask = await createTask(projectId, {
        title: `Implement: ${feature.name}`,
        description: feature.description || `Implement feature ${feature.feature_id}`,
        feature_id: feature.id ?? undefined,
      });
      setTask(newTask);

      // 2. Start execution
      await startTask(projectId, newTask.id, {
        agent_type: agent,
        allow_delegation: allowDelegation,
      });

      // 3. Switch to running view
      setState("running");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start task");
    } finally {
      setLoading(false);
    }
  };

  const handleClose = () => {
    // Reset state when closing
    setState("configure");
    setTask(null);
    setError(null);
    onOpenChange(false);
  };

  // Calculate criteria progress
  const totalCriteria = feature.acceptance_criteria?.length || 0;
  const passedCriteria = feature.acceptance_criteria?.filter((c) => c.passed)?.length || 0;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent
        className={clsx(
          "w-full max-w-2xl",
          state === "running" && "max-w-4xl"
        )}
      >
        <DialogClose onClose={handleClose} />

        {state === "configure" && (
          <>
            <DialogHeader>
              <DialogTitle>Start Task</DialogTitle>
              <DialogDescription>
                Configure and start an AI agent to work on this feature
              </DialogDescription>
            </DialogHeader>

            <div className="p-5 space-y-6">
              {/* Feature Summary */}
              <div className="p-4 bg-slate-800/50 rounded-lg border border-slate-700">
                <h3 className="text-sm font-medium text-slate-300 mb-2">
                  Feature
                </h3>
                <p className="text-white font-medium">{feature.name}</p>
                {feature.description && (
                  <p className="text-sm text-slate-400 mt-1">{feature.description}</p>
                )}
                <div className="flex items-center gap-4 mt-3 text-xs text-slate-400">
                  <span>ID: {feature.feature_id}</span>
                  {feature.category && <span>Category: {feature.category}</span>}
                  <span>
                    Criteria: {passedCriteria}/{totalCriteria} passed
                  </span>
                </div>
              </div>

              {/* Agent Selection */}
              <div>
                <h3 className="text-sm font-medium text-slate-300 mb-3">
                  Select Agent
                </h3>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={() => setAgent("gemini")}
                    className={clsx(
                      "flex items-center gap-3 p-4 rounded-lg border transition-all",
                      agent === "gemini"
                        ? "border-phosphor-500 bg-phosphor-500/10"
                        : "border-slate-700 hover:border-slate-600"
                    )}
                  >
                    <Sparkles
                      className={clsx(
                        "w-5 h-5",
                        agent === "gemini" ? "text-phosphor-400" : "text-slate-400"
                      )}
                    />
                    <div className="text-left">
                      <p
                        className={clsx(
                          "font-medium",
                          agent === "gemini" ? "text-phosphor-400" : "text-white"
                        )}
                      >
                        Gemini
                      </p>
                      <p className="text-xs text-slate-500">Fast and free</p>
                    </div>
                  </button>

                  <button
                    onClick={() => setAgent("claude")}
                    className={clsx(
                      "flex items-center gap-3 p-4 rounded-lg border transition-all",
                      agent === "claude"
                        ? "border-phosphor-500 bg-phosphor-500/10"
                        : "border-slate-700 hover:border-slate-600"
                    )}
                  >
                    <Bot
                      className={clsx(
                        "w-5 h-5",
                        agent === "claude" ? "text-phosphor-400" : "text-slate-400"
                      )}
                    />
                    <div className="text-left">
                      <p
                        className={clsx(
                          "font-medium",
                          agent === "claude" ? "text-phosphor-400" : "text-white"
                        )}
                      >
                        Claude
                      </p>
                      <p className="text-xs text-slate-500">More capable</p>
                    </div>
                  </button>
                </div>
              </div>

              {/* Options */}
              <div>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={allowDelegation}
                    onChange={(e) => setAllowDelegation(e.target.checked)}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-phosphor-500 focus:ring-phosphor-500"
                  />
                  <div>
                    <p className="text-sm text-white">Allow delegation</p>
                    <p className="text-xs text-slate-500">
                      Let agents delegate tasks to each other for better results
                    </p>
                  </div>
                </label>
              </div>

              {/* Error */}
              {error && (
                <div className="p-3 bg-rose-950/50 border border-rose-800 rounded-lg">
                  <p className="text-sm text-rose-400">{error}</p>
                </div>
              )}

              {/* Actions */}
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-800">
                <Button variant="ghost" onClick={handleClose}>
                  Cancel
                </Button>
                <Button onClick={handleStart} disabled={loading}>
                  {loading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Starting...
                    </>
                  ) : (
                    "Start Task"
                  )}
                </Button>
              </div>
            </div>
          </>
        )}

        {state === "running" && task && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Loader2 className="w-5 h-5 animate-spin text-phosphor-400" />
                Task Running
              </DialogTitle>
              <DialogDescription>
                {task.title} - {agent.charAt(0).toUpperCase() + agent.slice(1)} agent
              </DialogDescription>
            </DialogHeader>

            <div className="p-5">
              <TaskLogViewer
                projectId={projectId}
                taskId={task.id}
                className="h-[400px]"
              />

              <div className="flex justify-end gap-3 pt-4 mt-4 border-t border-slate-800">
                <Button variant="ghost" onClick={handleClose}>
                  Close
                </Button>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
