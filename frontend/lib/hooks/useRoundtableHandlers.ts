"use client";

import { useState, useCallback } from "react";
import {
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
  type GeneratedSpec,
  type PermissionRequest,
  type ToolStats,
} from "@/lib/api";

// Re-export types for consumers
export type { GeneratedFeature, GeneratedMission, GeneratedNarrative, GeneratedGoal, PermissionRequest };
import { type AgentConfig } from "@/components/settings/AgentConfigPanel";
import { type ChatMessage, type GeneratedVision, type RoundtableMode } from "@/components/roundtable/RoundtableChat";

interface UseRoundtableHandlersProps {
  projectId: string;
  // Session state
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  mode: RoundtableMode;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  // Tools state
  toolsEnabled: boolean;
  setToolsEnabled: (enabled: boolean) => void;
  writeEnabled: boolean;
  setWriteEnabled: (enabled: boolean) => void;
  yoloMode: boolean;
  setYoloMode: (enabled: boolean) => void;
  setToolStats: React.Dispatch<React.SetStateAction<ToolStats>>;
  // Agent config
  agentOverride: string | null;
  setAgentOverride: (agent: string | null) => void;
  modelOverride: string | null;
  setModelOverride: (model: string | null) => void;
  // Spec
  setGeneratedSpec: (spec: GeneratedSpec | null) => void;
}

interface UseRoundtableHandlersResult {
  // Loading/error state
  loading: boolean;
  error: string | null;
  streamingAgent: "claude" | "gemini" | null;
  clearError: () => void;
  // Permission state
  pendingPermission: PermissionRequest | null;
  permissionLoading: boolean;
  // Handlers
  handleSendMessage: (message: string) => Promise<void>;
  handleToolsChange: (settings: { toolsEnabled?: boolean; writeEnabled?: boolean; yoloMode?: boolean }) => Promise<void>;
  handleAgentConfigChange: (config: AgentConfig) => Promise<void>;
  handleApprovePermission: () => Promise<void>;
  handleDenyPermission: () => Promise<void>;
  // Generation handlers
  handleGenerateFeatures: () => Promise<GeneratedFeature[]>;
  handleGenerateVision: () => Promise<GeneratedVision>;
  handleGenerateGoals: () => Promise<GeneratedGoal[]>;
  handleSaveVision: (mission: GeneratedMission | null, narratives: GeneratedNarrative[]) => Promise<void>;
  handleSaveGoals: (goals: GeneratedGoal[]) => Promise<void>;
  handleGenerateSpec: () => Promise<GeneratedSpec>;
  handleAcceptSpec: () => Promise<void>;
}

export function useRoundtableHandlers({
  projectId,
  sessionId,
  setSessionId,
  mode,
  messages,
  setMessages,
  toolsEnabled,
  setToolsEnabled,
  writeEnabled,
  setWriteEnabled,
  yoloMode,
  setYoloMode,
  setToolStats,
  agentOverride,
  setAgentOverride,
  modelOverride,
  setModelOverride,
  setGeneratedSpec,
}: UseRoundtableHandlersProps): UseRoundtableHandlersResult {
  // Loading and error state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingAgent, setStreamingAgent] = useState<"claude" | "gemini" | null>(null);

  // Permission state
  const [pendingPermission, setPendingPermission] = useState<PermissionRequest | null>(null);
  const [permissionLoading, setPermissionLoading] = useState(false);

  const clearError = useCallback(() => setError(null), []);

  // Generic wrapper for generation calls
  const withGeneration = useCallback(
    async <T,>(
      defaultValue: T,
      errorPrefix: string,
      fn: (sid: string) => Promise<T>
    ): Promise<T> => {
      if (!sessionId) {
        setError("No active session");
        return defaultValue;
      }
      setLoading(true);
      setError(null);
      try {
        return await fn(sessionId);
      } catch (err) {
        setError(err instanceof Error ? err.message : `Failed to ${errorPrefix}`);
        return defaultValue;
      } finally {
        setLoading(false);
      }
    },
    [sessionId]
  );

  // Send message handler
  const handleSendMessage = useCallback(
    async (message: string) => {
      setLoading(true);
      setError(null);

      try {
        // Create session if needed
        let sid = sessionId;
        if (!sid) {
          const session = await createRoundtableSession(projectId, {
            mode,
            toolsEnabled,
            writeEnabled,
            yoloMode,
          });
          sid = session.session_id;
          setSessionId(sid);
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
        setMessages((prev) => [...prev, userMessage]);

        // Stream responses via SSE
        const stream = streamRoundtableMessage(projectId, sid, message, "both");

        for await (const event of stream) {
          switch (event.type) {
            case "agent_start":
              if (event.data.agent) {
                setStreamingAgent(event.data.agent);
              }
              break;

            case "keepalive":
              console.debug(`Keepalive from ${event.data.agent}`);
              break;

            case "agent_complete":
              if (event.data.id && event.data.agent && event.data.content) {
                const agentMessage: ChatMessage = {
                  id: event.data.id,
                  agent: event.data.agent,
                  content: event.data.content,
                  timestamp: event.data.timestamp ? new Date(event.data.timestamp) : new Date(),
                  tokensUsed: event.data.tokens_used,
                };
                setMessages((prev) => [...prev, agentMessage]);
              }
              setStreamingAgent(null);
              break;

            case "error":
              setError(event.data.message || "An error occurred");
              break;

            case "permission_request":
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
              break;
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to send message");
      } finally {
        setLoading(false);
        setStreamingAgent(null);
      }
    },
    [projectId, sessionId, mode, toolsEnabled, writeEnabled, yoloMode, setSessionId, setToolsEnabled, setWriteEnabled, setYoloMode, setMessages]
  );

  // Tools change handler
  const handleToolsChange = useCallback(
    async (settings: { toolsEnabled?: boolean; writeEnabled?: boolean; yoloMode?: boolean }) => {
      // Optimistically update UI
      const prevToolsEnabled = toolsEnabled;
      const prevWriteEnabled = writeEnabled;
      const prevYoloMode = yoloMode;

      if (settings.toolsEnabled !== undefined) setToolsEnabled(settings.toolsEnabled);
      if (settings.writeEnabled !== undefined) setWriteEnabled(settings.writeEnabled);
      if (settings.yoloMode !== undefined) setYoloMode(settings.yoloMode);

      // If we have a session, persist the change
      if (sessionId) {
        try {
          const result = await updateRoundtableTools(projectId, sessionId, settings);
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
    },
    [projectId, sessionId, toolsEnabled, writeEnabled, yoloMode, setToolsEnabled, setWriteEnabled, setYoloMode, setToolStats]
  );

  // Agent config handler
  const handleAgentConfigChange = useCallback(
    async (config: AgentConfig) => {
      // Optimistically update UI
      const prevAgentOverride = agentOverride;
      const prevModelOverride = modelOverride;

      setAgentOverride(config.agentOverride);
      setModelOverride(config.modelOverride);

      // If we have a session, persist the change
      if (sessionId) {
        try {
          const result = await updateRoundtableAgentConfig(projectId, sessionId, {
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
    },
    [projectId, sessionId, agentOverride, modelOverride, setAgentOverride, setModelOverride]
  );

  // Permission handlers
  const handleResolvePermission = useCallback(
    async (approve: boolean) => {
      if (!pendingPermission || !sessionId) return;
      setPermissionLoading(true);
      try {
        await resolvePermission(projectId, sessionId, pendingPermission.permission_id, approve);
        setPendingPermission(null);
      } catch (err) {
        console.error(`Failed to ${approve ? "approve" : "deny"} permission:`, err);
      } finally {
        setPermissionLoading(false);
      }
    },
    [projectId, sessionId, pendingPermission]
  );

  const handleApprovePermission = useCallback(() => handleResolvePermission(true), [handleResolvePermission]);
  const handleDenyPermission = useCallback(() => handleResolvePermission(false), [handleResolvePermission]);

  // Generation handlers
  const handleGenerateFeatures = useCallback(
    (): Promise<GeneratedFeature[]> =>
      withGeneration([], "generate features", async (sid) => {
        const result = await generateFeaturesFromRoundtable(projectId, sid, "gemini");
        return result.features;
      }),
    [projectId, withGeneration]
  );

  const handleGenerateVision = useCallback(
    (): Promise<GeneratedVision> =>
      withGeneration({ mission: null, narratives: [] }, "generate vision", async (sid) => {
        const result = await generateVisionFromRoundtable(projectId, sid, "claude");
        return { mission: result.mission, narratives: result.narratives };
      }),
    [projectId, withGeneration]
  );

  const handleGenerateGoals = useCallback(
    (): Promise<GeneratedGoal[]> =>
      withGeneration([], "generate goals", async (sid) => {
        const result = await generateGoalsFromRoundtable(projectId, sid, "claude");
        return result.goals;
      }),
    [projectId, withGeneration]
  );

  const handleSaveVision = useCallback(
    (mission: GeneratedMission | null, narratives: GeneratedNarrative[]): Promise<void> =>
      withGeneration(undefined, "save vision", async (sid) => {
        await saveVisionFromRoundtable(projectId, sid, mission, narratives);
      }),
    [projectId, withGeneration]
  );

  const handleSaveGoals = useCallback(
    (goals: GeneratedGoal[]): Promise<void> =>
      withGeneration(undefined, "save goals", async (sid) => {
        await saveGoalsFromRoundtable(projectId, sid, goals);
      }),
    [projectId, withGeneration]
  );

  const handleGenerateSpec = useCallback(
    (): Promise<GeneratedSpec> =>
      withGeneration({ components: [] } as GeneratedSpec, "generate spec", async (sid) => {
        const result = await generateSpecFromRoundtable(projectId, sid, "gemini");
        setGeneratedSpec(result.spec);
        return result.spec;
      }),
    [projectId, withGeneration, setGeneratedSpec]
  );

  const handleAcceptSpec = useCallback(
    (): Promise<void> =>
      withGeneration(undefined, "accept spec", async (sid) => {
        const result = await acceptSpecFromRoundtable(projectId, sid, "user");
        setGeneratedSpec(null);
        console.log(`Spec accepted: ${result.components_created} components, ${result.capabilities_created} capabilities, ${result.tests_created} tests`);
      }),
    [projectId, withGeneration, setGeneratedSpec]
  );

  return {
    loading,
    error,
    streamingAgent,
    clearError,
    pendingPermission,
    permissionLoading,
    handleSendMessage,
    handleToolsChange,
    handleAgentConfigChange,
    handleApprovePermission,
    handleDenyPermission,
    handleGenerateFeatures,
    handleGenerateVision,
    handleGenerateGoals,
    handleSaveVision,
    handleSaveGoals,
    handleGenerateSpec,
    handleAcceptSpec,
  };
}
