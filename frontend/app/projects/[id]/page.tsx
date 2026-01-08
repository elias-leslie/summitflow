"use client";

import { useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import Link from "next/link";
import {
  fetchProject,
  createRoundtableSession,
  streamRoundtableMessage,
  generateFeaturesFromRoundtable,
  generateVisionFromRoundtable,
  generateGoalsFromRoundtable,
  generateSpecFromRoundtable,
  acceptSpecFromRoundtable,
  saveVisionFromRoundtable,
  saveGoalsFromRoundtable,
  updateRoundtableTools,
  updateRoundtableAgentConfig,
  resolvePermission,
  type GeneratedFeature,
  type GeneratedMission,
  type GeneratedNarrative,
  type GeneratedGoal,
  type PermissionRequest,
} from "@/lib/api";
import { type AgentConfig } from "@/components/settings/AgentConfigPanel";
import { TasksTab } from "@/components/tasks/TasksTab";
import { type TaskFilterValues } from "@/components/tasks/TaskFilters";
import { EvidenceTab } from "@/components/evidence/EvidenceTab";
import { ExplorerTab } from "@/components/explorer/ExplorerTab";
import type { ExplorerType } from "@/components/explorer/types";
import { TaskKanbanBoard } from "@/components/kanban/TaskKanbanBoard";
import { TaskDetailDrawer } from "@/components/kanban/TaskDetailDrawer";
import { RoundtableChat, type ChatMessage, type GeneratedVision } from "@/components/roundtable/RoundtableChat";
import { PermissionDialog } from "@/components/roundtable/PermissionDialog";
import { SessionList } from "@/components/roundtable/SessionList";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { MemoryCaptureIndicator } from "@/components/memory/MemoryCaptureIndicator";
import { fetchTasks, updateTaskStatus, type Task, type TaskStatus } from "@/lib/api";
import { useRoundtableSession } from "@/lib/hooks/useRoundtableSession";
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
  if (urlTaskStatus && ["all", "active", "blocked", "pending", "running", "completed", "failed"].includes(urlTaskStatus)) {
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

  // Roundtable session state (extracted to hook)
  const {
    sessionId: roundtableSessionId,
    setSessionId: setRoundtableSessionId,
    mode: roundtableMode,
    setMode: setRoundtableMode,
    messages: roundtableMessages,
    setMessages: setRoundtableMessages,
    // sessionLoaded not used in this component
    toolsEnabled,
    setToolsEnabled,
    writeEnabled,
    setWriteEnabled,
    yoloMode,
    setYoloMode,
    toolStats,
    setToolStats,
    agentOverride,
    setAgentOverride,
    modelOverride,
    setModelOverride,
    generatedSpec,
    setGeneratedSpec,
    selectSession: handleSelectSession,
    clearSession: handleNewRoundtableSession,
  } = useRoundtableSession(projectId);

  // Remaining roundtable UI state
  const [roundtableLoading, setRoundtableLoading] = useState(false);
  const [streamingAgent, setStreamingAgent] = useState<"claude" | "gemini" | null>(null);
  const [roundtableError, setRoundtableError] = useState<string | null>(null);

  // Permission prompting state
  const [pendingPermission, setPendingPermission] = useState<PermissionRequest | null>(null);
  const [permissionLoading, setPermissionLoading] = useState(false);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });

  // Tasks for Kanban (fetch with feature context)
  const {
    data: kanbanTasksData,
    refetch: refetchKanbanTasks,
  } = useQuery({
    queryKey: ["tasks-kanban", projectId],
    queryFn: () => fetchTasks(projectId, { include: "feature", limit: 500 }),
    staleTime: 30000,
    enabled: activeTab === "kanban",
  });
  const kanbanTasks = kanbanTasksData?.tasks ?? [];

  // Kanban handlers
  const handleTaskStatusChange = async (taskId: string, newStatus: TaskStatus) => {
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

  // Wrapper to clear error when starting new session
  const handleNewSession = () => {
    handleNewRoundtableSession();
    setRoundtableError(null);
  };

  // Wrapper to handle session selection with error handling
  const handleSessionSelect = async (sessionId: string) => {
    try {
      await handleSelectSession(sessionId);
      setRoundtableError(null);
    } catch (err) {
      console.error("Failed to load session:", err);
      setRoundtableError("Failed to load session");
    }
  };

  const handleToolsChange = async (settings: { toolsEnabled?: boolean; writeEnabled?: boolean; yoloMode?: boolean }) => {
    // Optimistically update UI
    const prevToolsEnabled = toolsEnabled;
    const prevWriteEnabled = writeEnabled;
    const prevYoloMode = yoloMode;

    if (settings.toolsEnabled !== undefined) setToolsEnabled(settings.toolsEnabled);
    if (settings.writeEnabled !== undefined) setWriteEnabled(settings.writeEnabled);
    if (settings.yoloMode !== undefined) setYoloMode(settings.yoloMode);

    // If we have a session, persist the change
    if (roundtableSessionId) {
      try {
        const result = await updateRoundtableTools(projectId, roundtableSessionId, settings);
        setToolsEnabled(result.tools_enabled);
        setWriteEnabled(result.write_enabled);
        setYoloMode(result.yolo_mode);
        setToolStats(result.tool_stats);
      } catch (err) {
        // Revert on error
        setToolsEnabled(prevToolsEnabled);
        setWriteEnabled(prevWriteEnabled);
        setYoloMode(prevYoloMode);
        console.error("Failed to update tools settings:", err);
      }
    }
  };

  // Agent config handler
  const handleAgentConfigChange = async (config: AgentConfig) => {
    // Optimistically update UI
    const prevAgentOverride = agentOverride;
    const prevModelOverride = modelOverride;

    setAgentOverride(config.agentOverride);
    setModelOverride(config.modelOverride);

    // If we have a session, persist the change
    if (roundtableSessionId) {
      try {
        const result = await updateRoundtableAgentConfig(projectId, roundtableSessionId, {
          agent_override: config.agentOverride,
          model_override: config.modelOverride,
        });
        setAgentOverride(result.agent_override);
        setModelOverride(result.model_override);
      } catch (err) {
        // Revert on error
        setAgentOverride(prevAgentOverride);
        setModelOverride(prevModelOverride);
        console.error("Failed to update agent config:", err);
      }
    }
  };

  // Permission handlers
  const handleResolvePermission = async (approve: boolean) => {
    if (!pendingPermission || !roundtableSessionId) return;
    setPermissionLoading(true);
    try {
      await resolvePermission(projectId, roundtableSessionId, pendingPermission.permission_id, approve);
      setPendingPermission(null);
    } catch (error) {
      console.error(`Failed to ${approve ? "approve" : "deny"} permission:`, error);
    } finally {
      setPermissionLoading(false);
    }
  };

  const handleApprovePermission = () => handleResolvePermission(true);
  const handleDenyPermission = () => handleResolvePermission(false);

  const handleSendMessage = async (
    message: string
  ) => {
    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      // Create session if needed
      let sessionId = roundtableSessionId;
      if (!sessionId) {
        const session = await createRoundtableSession(projectId, {
          mode: roundtableMode,
          toolsEnabled,
          writeEnabled,
          yoloMode,
        });
        sessionId = session.session_id;
        setRoundtableSessionId(sessionId);
        setToolsEnabled(session.tools_enabled);
        setWriteEnabled(session.write_enabled);
        setYoloMode(session.yolo_mode);
      }

      // Add user message to UI immediately
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        agent: "user",
        content: message,
        timestamp: new Date(),
      };
      setRoundtableMessages((prev) => [...prev, userMessage]);

      // Stream responses via SSE
      const stream = streamRoundtableMessage(
        projectId,
        sessionId,
        message,
        "both" // Always send to both agents
      );

      for await (const event of stream) {
        switch (event.type) {
          case "agent_start":
            // Show which agent is typing
            if (event.data.agent) {
              setStreamingAgent(event.data.agent);
            }
            break;

          case "keepalive":
            // Keepalive ping to prevent connection timeout
            // Just ensures the streaming agent indicator stays visible
            console.debug(`Keepalive from ${event.data.agent}`);
            break;

          case "agent_complete":
            // Add agent response when complete
            if (event.data.id && event.data.agent && event.data.content) {
              const agentMessage: ChatMessage = {
                id: event.data.id,
                agent: event.data.agent,
                content: event.data.content,
                timestamp: event.data.timestamp ? new Date(event.data.timestamp) : new Date(),
                tokensUsed: event.data.tokens_used,
              };
              setRoundtableMessages((prev) => [...prev, agentMessage]);
            }
            setStreamingAgent(null);
            break;

          case "error":
            setRoundtableError(event.data.message || "An error occurred");
            break;

          case "permission_request":
            // Agent needs permission for a write operation
            if (event.data.permission_id && event.data.tool_name && event.data.agent) {
              setPendingPermission({
                permission_id: event.data.permission_id,
                tool_name: event.data.tool_name,
                params: event.data.params || {},
                preview: event.data.preview,
                agent: event.data.agent,
              });
            }
            break;

          case "done":
            // Stream complete
            break;
        }
      }
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setRoundtableLoading(false);
      setStreamingAgent(null);
    }
  };

  // Wrapper to handle common generation pattern (loading state, error handling, session check)
  const withGeneration = async <T,>(
    defaultValue: T,
    errorPrefix: string,
    fn: (sessionId: string) => Promise<T>
  ): Promise<T> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return defaultValue;
    }
    setRoundtableLoading(true);
    setRoundtableError(null);
    try {
      return await fn(roundtableSessionId);
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : `Failed to ${errorPrefix}`);
      return defaultValue;
    } finally {
      setRoundtableLoading(false);
    }
  };

  const handleGenerateFeatures = (): Promise<GeneratedFeature[]> =>
    withGeneration([], "generate features", async (sessionId) => {
      const result = await generateFeaturesFromRoundtable(projectId, sessionId, "gemini");
      return result.features;
    });

  const handleGenerateVision = (): Promise<GeneratedVision> =>
    withGeneration({ mission: null, narratives: [] }, "generate vision", async (sessionId) => {
      const result = await generateVisionFromRoundtable(projectId, sessionId, "claude");
      return { mission: result.mission, narratives: result.narratives };
    });

  const handleGenerateGoals = (): Promise<GeneratedGoal[]> =>
    withGeneration([], "generate goals", async (sessionId) => {
      const result = await generateGoalsFromRoundtable(projectId, sessionId, "claude");
      return result.goals;
    });

  const handleSaveVision = (mission: GeneratedMission | null, narratives: GeneratedNarrative[]): Promise<void> =>
    withGeneration(undefined, "save vision", async (sessionId) => {
      await saveVisionFromRoundtable(projectId, sessionId, mission, narratives);
    });

  const handleSaveGoals = (goals: GeneratedGoal[]): Promise<void> =>
    withGeneration(undefined, "save goals", async (sessionId) => {
      await saveGoalsFromRoundtable(projectId, sessionId, goals);
    });

  const handleGenerateSpec = () =>
    withGeneration({ components: [] }, "generate spec", async (sessionId) => {
      const result = await generateSpecFromRoundtable(projectId, sessionId, "gemini");
      setGeneratedSpec(result.spec);
      return result.spec;
    });

  const handleAcceptSpec = (): Promise<void> =>
    withGeneration(undefined, "accept spec", async (sessionId) => {
      const result = await acceptSpecFromRoundtable(projectId, sessionId, "user");
      setGeneratedSpec(null);
      console.log(`Spec accepted: ${result.components_created} components, ${result.capabilities_created} capabilities, ${result.tests_created} tests`);
    });

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
          <h2 className="display text-lg font-semibold text-white mb-2">Project Not Found</h2>
          <p className="text-slate-400 mb-6">The project you&apos;re looking for doesn&apos;t exist or couldn&apos;t be loaded.</p>
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
        {activeTab === "roundtable" && (
          <div className="flex gap-4 h-full p-4">
            {/* Session List Panel */}
            <div className="w-72 flex-shrink-0">
              <SessionList
                projectId={projectId}
                currentSessionId={roundtableSessionId ?? undefined}
                onSelectSession={handleSessionSelect}
                onNewSession={handleNewSession}
              />
            </div>

            {/* Chat Panel */}
            <div className="flex-1 flex flex-col min-w-0">
              {/* Memory capture status indicator */}
              <div className="flex items-center justify-end mb-2">
                <MemoryCaptureIndicator projectId={projectId} />
              </div>
              <RoundtableChat
                projectId={projectId}
                sessionId={roundtableSessionId ?? undefined}
                className="flex-1"
                mode={roundtableMode}
                onModeChange={setRoundtableMode}
                onSendMessage={handleSendMessage}
                onGenerateFeatures={handleGenerateFeatures}
                onGenerateVision={handleGenerateVision}
                onGenerateGoals={handleGenerateGoals}
                onGenerateSpec={handleGenerateSpec}
                onSaveVision={handleSaveVision}
                onSaveGoals={handleSaveGoals}
                onAcceptSpec={handleAcceptSpec}
                generatedSpec={generatedSpec}
                onNewSession={handleNewSession}
                messages={roundtableMessages}
                isLoading={roundtableLoading}
                streamingAgent={streamingAgent}
                connected={true}
                error={roundtableError}
                toolsEnabled={toolsEnabled}
                writeEnabled={writeEnabled}
                yoloMode={yoloMode}
                toolStats={toolStats}
                onToolsChange={handleToolsChange}
                agentOverride={agentOverride}
                modelOverride={modelOverride}
                onAgentConfigChange={handleAgentConfigChange}
              />
            </div>
          </div>
        )}
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
            <TasksTab projectId={projectId} initialFilters={taskInitialFilters} />
          </div>
        )}
        {activeTab === "evidence" && (
          <div className="h-full overflow-auto p-4">
            <EvidenceTab
              projectId={projectId}
              entryId={evidenceEntryId}
              onClearEntryFilter={evidenceEntryId ? handleClearEvidenceEntryFilter : undefined}
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

      {/* Permission Dialog for write tool approval */}
      <PermissionDialog
        open={!!pendingPermission}
        request={pendingPermission}
        onApprove={handleApprovePermission}
        onDeny={handleDenyPermission}
        isLoading={permissionLoading}
      />
    </div>
  );
}
