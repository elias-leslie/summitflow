"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Check,
  Loader2,
  AlertCircle,
  Bot,
  FolderSearch,
  Target,
  ListChecks,
  Layers,
  ShieldCheck,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { fetchTask, type Task } from "@/lib/api/tasks";

interface EnrichmentProgressProps {
  projectId: string;
  task: Task;
  onComplete: (task: Task) => void;
  onError: (error: string) => void;
}

type StepStatus = "pending" | "active" | "completed";

interface ProgressStep {
  id: string;
  label: string;
  completedLabel?: string;
  icon: React.ElementType;
  status: StepStatus;
}

// Simulate enrichment progress based on elapsed time
// In reality, the backend would provide step-by-step updates
function estimateSteps(task: Task, elapsedMs: number): ProgressStep[] {
  const stepDuration = 4000; // Estimate ~4s per step

  const getStatus = (stepIndex: number): StepStatus => {
    const stepStart = stepIndex * stepDuration;
    if (elapsedMs >= stepStart + stepDuration) return "completed";
    if (elapsedMs >= stepStart) return "active";
    return "pending";
  };

  // Extract some info from the task if available
  const criteriaCount = task.acceptance_criteria?.length ?? 0;
  const capabilityName = task.capability?.name;

  return [
    {
      id: "context",
      label: "Gathering context from codebase...",
      completedLabel: "Found relevant files and patterns",
      icon: FolderSearch,
      status: getStatus(0),
    },
    {
      id: "capabilities",
      label: "Analyzing existing capabilities...",
      completedLabel: capabilityName
        ? `Linked to: ${capabilityName}`
        : "No direct matches",
      icon: Layers,
      status: getStatus(1),
    },
    {
      id: "objective",
      label: "Generating objective...",
      completedLabel: "Objective defined",
      icon: Target,
      status: getStatus(2),
    },
    {
      id: "criteria",
      label: "Creating acceptance criteria...",
      completedLabel:
        criteriaCount > 0
          ? `Generated ${criteriaCount} criteria`
          : "Generating criteria",
      icon: ListChecks,
      status: getStatus(3),
    },
    {
      id: "subtasks",
      label: "Building implementation subtasks...",
      completedLabel: "Subtasks created",
      icon: ListChecks,
      status: getStatus(4),
    },
    {
      id: "validation",
      label: "Cross-validating with Gemini...",
      completedLabel: "Validation complete",
      icon: ShieldCheck,
      status: getStatus(5),
    },
  ];
}

export function EnrichmentProgress({
  projectId,
  task: initialTask,
  onComplete,
  onError,
}: EnrichmentProgressProps) {
  const [task, setTask] = useState<Task>(initialTask);
  const [startTime] = useState(Date.now());
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const pollRef = useRef<NodeJS.Timeout | null>(null);
  const progressRef = useRef<NodeJS.Timeout | null>(null);

  const steps = estimateSteps(task, elapsedMs);
  const completedCount = steps.filter((s) => s.status === "completed").length;

  // Poll for task updates
  const pollTask = useCallback(async () => {
    try {
      const updatedTask = await fetchTask(projectId, task.id);
      setTask(updatedTask);

      if (updatedTask.enrichment_status === "review") {
        // Enrichment complete
        onComplete(updatedTask);
      } else if (updatedTask.enrichment_status === "failed") {
        // Enrichment failed
        setError(updatedTask.error_message || "Enrichment failed");
        onError(updatedTask.error_message || "Enrichment failed");
      }
    } catch (err) {
      // Don't fail on polling errors, just log
      console.error("Failed to poll task:", err);
    }
  }, [projectId, task.id, onComplete, onError]);

  // Start polling on mount
  useEffect(() => {
    if (task.enrichment_status !== "enriching") return;

    pollRef.current = setInterval(pollTask, 2000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [task.enrichment_status, pollTask]);

  // Progress animation timer
  useEffect(() => {
    if (task.enrichment_status !== "enriching") return;

    progressRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startTime);
    }, 100);

    return () => {
      if (progressRef.current) clearInterval(progressRef.current);
    };
  }, [task.enrichment_status, startTime]);

  const handleRetry = async () => {
    setIsRetrying(true);
    setError(null);
    // In a real implementation, you'd call an API to retry enrichment
    // For now, just reset and re-poll
    setElapsedMs(0);
    await pollTask();
    setIsRetrying(false);
  };

  return (
    <div className="relative">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative">
          <Bot className="w-6 h-6 text-phosphor-400" />
          {/* Pulsing indicator */}
          <motion.div
            className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-phosphor-400"
            animate={{
              scale: [1, 1.3, 1],
              opacity: [1, 0.6, 1],
            }}
            transition={{
              duration: 1.5,
              repeat: Infinity,
              ease: "easeInOut",
            }}
          />
        </div>
        <div>
          <h3 className="text-sm font-mono uppercase tracking-wider text-white">
            Agent Working
          </h3>
          <p className="text-xs text-slate-500">
            Opus 4.5 + Gemini 3 • {Math.round(elapsedMs / 1000)}s elapsed
          </p>
        </div>
      </div>

      {/* Progress Steps */}
      <div className="space-y-1">
        <AnimatePresence mode="popLayout">
          {steps.map((step, index) => (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{
                opacity: step.status === "pending" ? 0.4 : 1,
                x: 0,
              }}
              transition={{
                duration: 0.3,
                delay: index * 0.1,
              }}
              className="flex items-center gap-3 py-2 px-3 rounded-md
                transition-colors duration-300"
              style={{
                backgroundColor:
                  step.status === "active"
                    ? "rgba(59, 130, 246, 0.08)"
                    : "transparent",
              }}
            >
              {/* Step Icon */}
              <div className="relative w-5 h-5 flex-shrink-0">
                {step.status === "completed" ? (
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: "spring", stiffness: 400, damping: 15 }}
                    className="w-5 h-5 rounded-full bg-phosphor-500/20 flex items-center justify-center"
                  >
                    <Check className="w-3 h-3 text-phosphor-400" />
                  </motion.div>
                ) : step.status === "active" ? (
                  <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
                ) : (
                  <step.icon className="w-5 h-5 text-slate-600" />
                )}
              </div>

              {/* Step Label */}
              <div className="flex-1 min-w-0">
                <span
                  className={`text-sm font-medium transition-colors duration-300 ${
                    step.status === "completed"
                      ? "text-slate-300"
                      : step.status === "active"
                        ? "text-white"
                        : "text-slate-500"
                  }`}
                >
                  {step.status === "completed" && step.completedLabel
                    ? step.completedLabel
                    : step.label}
                </span>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Progress Bar */}
      <div className="mt-6">
        <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-phosphor-600 to-blue-500 rounded-full"
            initial={{ width: 0 }}
            animate={{ width: `${(completedCount / steps.length) * 100}%` }}
            transition={{ duration: 0.4, ease: "easeOut" }}
          />
        </div>
        <div className="flex justify-between mt-2">
          <span className="text-xs text-slate-500">
            {completedCount}/{steps.length} steps
          </span>
          <span className="text-xs text-slate-500">
            {Math.round((completedCount / steps.length) * 100)}% complete
          </span>
        </div>
      </div>

      {/* Error State */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="mt-6 p-4 bg-red-950/50 border border-red-800/50 rounded-lg"
          >
            <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <p className="text-sm text-red-400 font-medium">
                  Enrichment Failed
                </p>
                <p className="text-xs text-red-400/70 mt-1">{error}</p>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-3 border-red-800/50 text-red-400 hover:bg-red-950/50"
              onClick={handleRetry}
              disabled={isRetrying}
            >
              {isRetrying ? (
                <>
                  <Loader2 className="w-3 h-3 mr-2 animate-spin" />
                  Retrying...
                </>
              ) : (
                <>
                  <RefreshCw className="w-3 h-3 mr-2" />
                  Retry Enrichment
                </>
              )}
            </Button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Subtle background glow when active */}
      <div
        className="absolute inset-0 -z-10 opacity-30 pointer-events-none rounded-lg"
        style={{
          background:
            "radial-gradient(ellipse at top, rgba(16, 185, 129, 0.05) 0%, transparent 60%)",
        }}
      />
    </div>
  );
}
