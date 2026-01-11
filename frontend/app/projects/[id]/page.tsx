"use client";

import { useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import Link from "next/link";
import { fetchProject } from "@/lib/api";
import { TasksTab } from "@/components/tasks/TasksTab";
import { type TaskFilterValues } from "@/components/tasks/TaskFilters";
import { EvidenceTab } from "@/components/evidence/EvidenceTab";
import { ExplorerTab } from "@/components/explorer/ExplorerTab";
import type { ExplorerType } from "@/components/explorer/types";
import { TaskKanbanBoard } from "@/components/kanban/TaskKanbanBoard";
import { TaskDetailDrawer } from "@/components/kanban/TaskDetailDrawer";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { MemoryCaptureIndicator } from "@/components/memory/MemoryCaptureIndicator";
import {
  fetchTasks,
  updateTaskStatus,
  type Task,
  type TaskStatus,
} from "@/lib/api";
import { useTabPersistence, type TabId } from "@/lib/hooks/useTabPersistence";

export default function ProjectDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const projectId = params.id as string;

  // Tab persistence hook (handles localStorage and URL sync)
  const urlTab = searchParams.get("tab") as TabId | null;
  const urlExplorerType = searchParams.get("type") as ExplorerType | null;
  const { activeTab, explorerType, setExplorerType } = useTabPersistence({
    projectId,
    urlTab,
    urlExplorerType,
  });

  // Get task filter params from URL
  const urlTaskStatus = searchParams.get("status");
  const urlTaskType = searchParams.get("taskType");
  const taskInitialFilters: Partial<TaskFilterValues> = {};
  if (
    urlTaskStatus &&
    [
      "all",
      "active",
      "blocked",
      "pending",
      "running",
      "completed",
      "failed",
    ].includes(urlTaskStatus)
  ) {
    taskInitialFilters.status = urlTaskStatus as TaskFilterValues["status"];
  }
  if (urlTaskType && ["all", "feature", "bug", "task"].includes(urlTaskType)) {
    taskInitialFilters.type = urlTaskType as TaskFilterValues["type"];
  }

  // Get evidence entry_id filter from URL
  const urlEntryId = searchParams.get("entry_id");
  const evidenceEntryId = urlEntryId ? parseInt(urlEntryId, 10) : undefined;

  // Handler to clear evidence entry filter
  const handleClearEvidenceEntryFilter = () => {
    router.replace(`/projects/${projectId}?tab=evidence`, { scroll: false });
  };

  // Update URL when explorer type changes (without full navigation)
  const handleExplorerTypeChange = (type: ExplorerType) => {
    setExplorerType(type);
    const newUrl = `/projects/${projectId}?tab=explorer&type=${type}`;
    router.replace(newUrl, { scroll: false });
  };

  // Kanban state
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [createTaskDialogOpen, setCreateTaskDialogOpen] = useState(false);

  const {
    data: project,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });

  // Tasks for Kanban (fetch with feature context)
  const { data: kanbanTasksData, refetch: refetchKanbanTasks } = useQuery({
    queryKey: ["tasks-kanban", projectId],
    queryFn: () => fetchTasks(projectId, { include: "feature", limit: 500 }),
    staleTime: 30000,
    enabled: activeTab === "kanban",
  });
  const kanbanTasks = kanbanTasksData?.tasks ?? [];

  // Kanban handlers
  const handleTaskStatusChange = async (
    taskId: string,
    newStatus: TaskStatus,
  ) => {
    try {
      await updateTaskStatus(projectId, taskId, newStatus);
      refetchKanbanTasks();
    } catch (err) {
      console.error("Failed to update task status:", err);
    }
  };

  const handleTaskClick = (task: Task) => {
    setSelectedTask(task);
    setDrawerOpen(true);
  };

  const handleNewTask = () => {
    setCreateTaskDialogOpen(true);
  };

  const handleCreateDialogChange = (open: boolean) => {
    setCreateTaskDialogOpen(open);
    if (!open) {
      // Refetch tasks when dialog closes (after create)
      refetchKanbanTasks();
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="w-8 h-8 border-2 border-outrun-500/30 border-t-outrun-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="card p-8 text-center max-w-md">
          <AlertCircle className="w-10 h-10 text-rose-500 mx-auto mb-4" />
          <h2 className="display text-lg font-semibold text-white mb-2">
            Project Not Found
          </h2>
          <p className="text-slate-400 mb-6">
            The project you&apos;re looking for doesn&apos;t exist or
            couldn&apos;t be loaded.
          </p>
          <Link href="/" className="btn-primary inline-flex items-center gap-2">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-6rem)] flex flex-col">
      {/* Tab Content - Full height, no header redundancy */}
      <section className="flex-1 overflow-hidden">
        {activeTab === "kanban" && (
          <div className="h-full overflow-auto p-4">
            <TaskKanbanBoard
              tasks={kanbanTasks}
              projectId={projectId}
              onStatusChange={handleTaskStatusChange}
              onTaskClick={handleTaskClick}
              onNewTask={handleNewTask}
            />
            <TaskDetailDrawer
              task={selectedTask}
              projectId={projectId}
              open={drawerOpen}
              onOpenChange={setDrawerOpen}
              onStatusChange={handleTaskStatusChange}
            />
            <CreateTaskDialog
              open={createTaskDialogOpen}
              onOpenChange={handleCreateDialogChange}
              projectId={projectId}
            />
          </div>
        )}
        {activeTab === "tasks" && (
          <div className="h-full overflow-auto p-4">
            <TasksTab
              projectId={projectId}
              initialFilters={taskInitialFilters}
            />
          </div>
        )}
        {activeTab === "evidence" && (
          <div className="h-full overflow-auto p-4">
            <EvidenceTab
              projectId={projectId}
              entryId={evidenceEntryId}
              onClearEntryFilter={
                evidenceEntryId ? handleClearEvidenceEntryFilter : undefined
              }
            />
          </div>
        )}
        {activeTab === "explorer" && (
          <div className="h-full overflow-auto p-4">
            <ExplorerTab
              projectId={projectId}
              initialType={explorerType}
              onTypeChange={handleExplorerTypeChange}
            />
          </div>
        )}
      </section>
    </div>
  );
}
