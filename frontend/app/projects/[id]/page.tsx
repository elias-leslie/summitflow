"use client";

import { useState, useEffect } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import Link from "next/link";
import {
  fetchProject,
  fetchProjectHealth,
  createRoundtableSession,
  getRoundtableSession,
  streamRoundtableMessage,
  generateFeaturesFromRoundtable,
  generateVisionFromRoundtable,
  generateGoalsFromRoundtable,
  saveVisionFromRoundtable,
  saveGoalsFromRoundtable,
  updateRoundtableTools,
  updateRoundtableAgentConfig,
  resolvePermission,
  type RoundtableMessage,
  type GeneratedFeature,
  type GeneratedMission,
  type GeneratedNarrative,
  type GeneratedGoal,
  type RoundtableSSEEvent,
  type ToolStats,
  type PermissionRequest,
} from "@/lib/api";
import { type AgentConfig } from "@/components/settings/AgentConfigPanel";
import { FeaturesTab } from "@/components/features/FeaturesTab";
import { VisionOverview } from "@/components/vision/VisionOverview";
import { TasksTab } from "@/components/tasks/TasksTab";
import { EvidenceTab } from "@/components/evidence/EvidenceTab";
import { GoalsList } from "@/components/goals/GoalsList";
import { ExplorerTab } from "@/components/explorer/ExplorerTab";
import type { ExplorerType } from "@/components/explorer/types";
import { TaskKanbanBoard } from "@/components/kanban/TaskKanbanBoard";
import { TaskDetailDrawer } from "@/components/kanban/TaskDetailDrawer";
import {
  RoundtableChat,
  type ChatMessage,
  type RoundtableMode,
  type FileAttachment,
  type GeneratedVision,
} from "@/components/roundtable/RoundtableChat";
import { PermissionDialog } from "@/components/roundtable/PermissionDialog";
import { SessionList } from "@/components/roundtable/SessionList";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { fetchTasks, updateTaskStatus, type Task, type TaskStatus } from "@/lib/api";

type TabId = "roundtable" | "vision" | "goals" | "features" | "kanban" | "tasks" | "evidence" | "explorer";

const VALID_EXPLORER_TYPES: ExplorerType[] = ["files", "database", "celery", "api", "pages"];
const VALID_TABS: TabId[] = ["roundtable", "vision", "goals", "features", "kanban", "tasks", "evidence", "explorer"];

// localStorage key for remembering last tab per project
const getLastTabKey = (projectId: string) => `summitflow_last_tab_${projectId}`;

export default function ProjectDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const projectId = params.id as string;

  // Get initial tab from URL query param
  const urlTab = searchParams.get("tab") as TabId | null;
  const [activeTab, setActiveTab] = useState<TabId>(urlTab || "roundtable");
  const [hasRestoredTab, setHasRestoredTab] = useState(false);

  // Get explorer type from URL (for context preservation)
  const urlExplorerType = searchParams.get("type") as ExplorerType | null;
  const [explorerType, setExplorerType] = useState<ExplorerType>(
    urlExplorerType && VALID_EXPLORER_TYPES.includes(urlExplorerType) ? urlExplorerType : "files"
  );

  // Restore last tab from localStorage on mount (if no URL tab specified)
  useEffect(() => {
    if (!urlTab && !hasRestoredTab) {
      const lastTab = localStorage.getItem(getLastTabKey(projectId)) as TabId | null;
      if (lastTab && VALID_TABS.includes(lastTab)) {
        setActiveTab(lastTab);
        // Also restore explorer type if it was the explorer tab
        if (lastTab === "explorer") {
          const lastType = localStorage.getItem(`${getLastTabKey(projectId)}_explorer_type`) as ExplorerType | null;
          if (lastType && VALID_EXPLORER_TYPES.includes(lastType)) {
            setExplorerType(lastType);
          }
        }
      }
      setHasRestoredTab(true);
    }
  }, [projectId, urlTab, hasRestoredTab]);

  // Sync with URL changes
  useEffect(() => {
    if (urlTab && VALID_TABS.includes(urlTab)) {
      setActiveTab(urlTab);
    }
    // Sync explorer type from URL
    if (urlExplorerType && VALID_EXPLORER_TYPES.includes(urlExplorerType)) {
      setExplorerType(urlExplorerType);
    }
  }, [urlTab, urlExplorerType]);

  // Save active tab to localStorage whenever it changes
  useEffect(() => {
    if (hasRestoredTab) {
      localStorage.setItem(getLastTabKey(projectId), activeTab);
      // Also save explorer type if on explorer tab
      if (activeTab === "explorer") {
        localStorage.setItem(`${getLastTabKey(projectId)}_explorer_type`, explorerType);
      }
    }
  }, [activeTab, explorerType, projectId, hasRestoredTab]);

  // Update URL when explorer type changes (without full navigation)
  const handleExplorerTypeChange = (type: ExplorerType) => {
    setExplorerType(type);
    // Update URL to preserve context
    const newUrl = `/projects/${projectId}?tab=explorer&type=${type}`;
    router.replace(newUrl, { scroll: false });
  };

  // Kanban state
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [createTaskDialogOpen, setCreateTaskDialogOpen] = useState(false);

  // Roundtable state
  const [roundtableSessionId, setRoundtableSessionId] = useState<string | null>(null);
  const [roundtableMode, setRoundtableMode] = useState<RoundtableMode>("spec_driven");
  const [roundtableMessages, setRoundtableMessages] = useState<ChatMessage[]>([]);
  const [roundtableLoading, setRoundtableLoading] = useState(false);
  const [streamingAgent, setStreamingAgent] = useState<"claude" | "gemini" | null>(null);
  const [roundtableError, setRoundtableError] = useState<string | null>(null);
  const [generatedFeatures, setGeneratedFeatures] = useState<GeneratedFeature[]>([]);
  const [roundtableSessionLoaded, setRoundtableSessionLoaded] = useState(false);
  const [toolsEnabled, setToolsEnabled] = useState(true);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [yoloMode, setYoloMode] = useState(false);
  const [toolStats, setToolStats] = useState<ToolStats>({ total_calls: 0, files_read: 0, searches: 0, writes: 0 });
  const [agentOverride, setAgentOverride] = useState<string | null>(null);
  const [modelOverride, setModelOverride] = useState<string | null>(null);

  // Permission prompting state
  const [pendingPermission, setPendingPermission] = useState<PermissionRequest | null>(null);
  const [permissionLoading, setPermissionLoading] = useState(false);

  // Load roundtable session from localStorage on mount
  useEffect(() => {
    const storageKey = `roundtable-session-${projectId}`;
    const savedSessionId = localStorage.getItem(storageKey);

    if (savedSessionId) {
      // Load session data from backend
      getRoundtableSession(projectId, savedSessionId)
        .then((session) => {
          setRoundtableSessionId(session.id);
          setRoundtableMode(session.mode as RoundtableMode);

          // Load tools settings
          setToolsEnabled(session.tools_enabled ?? true);
          setWriteEnabled(session.write_enabled ?? false);
          setYoloMode(session.yolo_mode ?? false);
          if (session.tool_stats) {
            setToolStats(session.tool_stats);
          }

          // Load agent config
          setAgentOverride(session.agent_override ?? null);
          setModelOverride(session.model_override ?? null);

          // Convert messages to ChatMessage format
          const messages: ChatMessage[] = session.messages.map((msg: RoundtableMessage) => ({
            id: msg.id,
            agent: msg.agent,
            content: msg.content,
            timestamp: new Date(msg.timestamp),
            tokensUsed: msg.tokens_used,
          }));
          setRoundtableMessages(messages);

          // Load generated features if any
          if (session.generated_features && session.generated_features.length > 0) {
            setGeneratedFeatures(session.generated_features);
          }
        })
        .catch((err) => {
          console.warn("Failed to load saved session:", err);
          // Clear invalid session
          localStorage.removeItem(storageKey);
        })
        .finally(() => {
          setRoundtableSessionLoaded(true);
        });
    } else {
      setRoundtableSessionLoaded(true);
    }
  }, [projectId]);

  // Save session ID to localStorage when it changes
  useEffect(() => {
    if (roundtableSessionId && roundtableSessionLoaded) {
      const storageKey = `roundtable-session-${projectId}`;
      localStorage.setItem(storageKey, roundtableSessionId);
    }
  }, [roundtableSessionId, projectId, roundtableSessionLoaded]);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });

  const { data: health } = useQuery({
    queryKey: ["project-health", projectId],
    queryFn: () => fetchProjectHealth(projectId),
    refetchInterval: 30000,
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

  // Roundtable handlers
  const handleRoundtableModeChange = (mode: RoundtableMode) => {
    setRoundtableMode(mode);
  };

  const handleNewRoundtableSession = () => {
    // Clear current session
    setRoundtableSessionId(null);
    setRoundtableMessages([]);
    setGeneratedFeatures([]);
    setRoundtableError(null);
    // Reset tools state
    setToolsEnabled(true);
    setWriteEnabled(false);
    setYoloMode(false);
    setToolStats({ total_calls: 0, files_read: 0, searches: 0, writes: 0 });
    // Clear from localStorage
    const storageKey = `roundtable-session-${projectId}`;
    localStorage.removeItem(storageKey);
  };

  const handleSelectSession = async (sessionId: string) => {
    // Don't reload if already selected
    if (sessionId === roundtableSessionId) return;

    try {
      const session = await getRoundtableSession(projectId, sessionId);
      setRoundtableSessionId(session.id);
      setRoundtableMode(session.mode as RoundtableMode);

      // Load tools settings
      setToolsEnabled(session.tools_enabled ?? true);
      setWriteEnabled(session.write_enabled ?? false);
      setYoloMode(session.yolo_mode ?? false);
      if (session.tool_stats) {
        setToolStats(session.tool_stats);
      }

      // Load agent config
      setAgentOverride(session.agent_override ?? null);
      setModelOverride(session.model_override ?? null);

      // Convert messages to ChatMessage format
      const messages: ChatMessage[] = session.messages.map((msg: RoundtableMessage) => ({
        id: msg.id,
        agent: msg.agent,
        content: msg.content,
        timestamp: new Date(msg.timestamp),
        tokensUsed: msg.tokens_used,
      }));
      setRoundtableMessages(messages);

      // Load generated features if any
      if (session.generated_features && session.generated_features.length > 0) {
        setGeneratedFeatures(session.generated_features);
      } else {
        setGeneratedFeatures([]);
      }

      // Clear any errors
      setRoundtableError(null);

      // Save to localStorage for persistence
      const storageKey = `roundtable-session-${projectId}`;
      localStorage.setItem(storageKey, sessionId);
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
  const handleApprovePermission = async () => {
    if (!pendingPermission || !roundtableSessionId) return;
    setPermissionLoading(true);
    try {
      await resolvePermission(projectId, roundtableSessionId, pendingPermission.permission_id, true);
      setPendingPermission(null);
    } catch (error) {
      console.error("Failed to approve permission:", error);
    } finally {
      setPermissionLoading(false);
    }
  };

  const handleDenyPermission = async () => {
    if (!pendingPermission || !roundtableSessionId) return;
    setPermissionLoading(true);
    try {
      await resolvePermission(projectId, roundtableSessionId, pendingPermission.permission_id, false);
      setPendingPermission(null);
    } catch (error) {
      console.error("Failed to deny permission:", error);
    } finally {
      setPermissionLoading(false);
    }
  };

  const handleSendMessage = async (
    message: string,
    _attachments?: FileAttachment[],
    _targetAgent?: "claude" | "gemini" | "user"
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

  const handleGenerateFeatures = async (): Promise<GeneratedFeature[]> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return [];
    }

    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      const result = await generateFeaturesFromRoundtable(
        projectId,
        roundtableSessionId,
        "gemini" // Use Gemini for faster extraction
      );

      // Convert to the format expected by the component
      const features: GeneratedFeature[] = result.features.map((f) => ({
        feature_id: f.feature_id,
        name: f.name,
        category: f.category,
        priority: f.priority,
        description: f.description,
        acceptance_criteria: f.acceptance_criteria,
      }));

      setGeneratedFeatures(features);
      return features;
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to generate features");
      return [];
    } finally {
      setRoundtableLoading(false);
    }
  };

  const handleGenerateVision = async (): Promise<GeneratedVision> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return { mission: null, narratives: [] };
    }

    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      const result = await generateVisionFromRoundtable(
        projectId,
        roundtableSessionId,
        "claude"
      );

      return {
        mission: result.mission,
        narratives: result.narratives,
      };
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to generate vision");
      return { mission: null, narratives: [] };
    } finally {
      setRoundtableLoading(false);
    }
  };

  const handleGenerateGoals = async (): Promise<GeneratedGoal[]> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return [];
    }

    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      const result = await generateGoalsFromRoundtable(
        projectId,
        roundtableSessionId,
        "claude"
      );

      return result.goals;
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to generate goals");
      return [];
    } finally {
      setRoundtableLoading(false);
    }
  };

  const handleSaveVision = async (
    mission: GeneratedMission | null,
    narratives: GeneratedNarrative[]
  ): Promise<void> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return;
    }

    try {
      await saveVisionFromRoundtable(projectId, roundtableSessionId, mission, narratives);
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to save vision");
    }
  };

  const handleSaveGoals = async (goals: GeneratedGoal[]): Promise<void> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return;
    }

    try {
      await saveGoalsFromRoundtable(projectId, roundtableSessionId, goals);
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to save goals");
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
          <h2 className="display text-lg font-semibold text-white mb-2">Project Not Found</h2>
          <p className="text-slate-400 mb-6">The project you're looking for doesn't exist or couldn't be loaded.</p>
          <Link href="/projects" className="btn-primary inline-flex items-center gap-2">
            View All Projects
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
                onSelectSession={handleSelectSession}
                onNewSession={handleNewRoundtableSession}
              />
            </div>

            {/* Chat Panel */}
            <RoundtableChat
              projectId={projectId}
              sessionId={roundtableSessionId ?? undefined}
              className="flex-1"
              mode={roundtableMode}
              onModeChange={handleRoundtableModeChange}
              onSendMessage={handleSendMessage}
              onGenerateFeatures={handleGenerateFeatures}
              onGenerateVision={handleGenerateVision}
              onGenerateGoals={handleGenerateGoals}
              onSaveVision={handleSaveVision}
              onSaveGoals={handleSaveGoals}
              onNewSession={handleNewRoundtableSession}
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
        )}
        {activeTab === "vision" && (
          <div className="h-full overflow-auto p-4">
            <VisionOverview projectId={projectId} />
          </div>
        )}
        {activeTab === "goals" && (
          <div className="h-full overflow-auto p-4">
            <GoalsList projectId={projectId} />
          </div>
        )}
        {activeTab === "features" && (
          <div className="h-full overflow-auto p-4">
            <FeaturesTab projectId={projectId} />
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
            <TasksTab projectId={projectId} />
          </div>
        )}
        {activeTab === "evidence" && (
          <div className="h-full overflow-auto p-4">
            <EvidenceTab projectId={projectId} />
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
