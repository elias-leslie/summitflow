"use client";

import { useState, useEffect, useCallback } from "react";
import {
  getRoundtableSession,
  getSpecFromRoundtable,
  type RoundtableMessage,
  type GeneratedSpec,
  type ToolStats,
} from "@/lib/api";
import { type ChatMessage, type RoundtableMode } from "@/components/roundtable/RoundtableChat";

interface UseRoundtableSessionResult {
  // Session state
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  mode: RoundtableMode;
  setMode: (mode: RoundtableMode) => void;
  messages: ChatMessage[];
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  sessionLoaded: boolean;

  // Tools state
  toolsEnabled: boolean;
  setToolsEnabled: (enabled: boolean) => void;
  writeEnabled: boolean;
  setWriteEnabled: (enabled: boolean) => void;
  yoloMode: boolean;
  setYoloMode: (enabled: boolean) => void;
  toolStats: ToolStats;
  setToolStats: React.Dispatch<React.SetStateAction<ToolStats>>;

  // Agent config
  agentOverride: string | null;
  setAgentOverride: (agent: string | null) => void;
  modelOverride: string | null;
  setModelOverride: (model: string | null) => void;

  // Spec
  generatedSpec: GeneratedSpec | null;
  setGeneratedSpec: (spec: GeneratedSpec | null) => void;

  // Actions
  selectSession: (sessionId: string) => Promise<void>;
  clearSession: () => void;
}

const DEFAULT_TOOL_STATS: ToolStats = {
  total_calls: 0,
  files_read: 0,
  searches: 0,
  writes: 0,
};

/**
 * Hook to manage Roundtable session state with localStorage persistence.
 */
export function useRoundtableSession(projectId: string): UseRoundtableSessionResult {
  // Core session state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<RoundtableMode>("spec_driven");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionLoaded, setSessionLoaded] = useState(false);

  // Tools state
  const [toolsEnabled, setToolsEnabled] = useState(true);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [yoloMode, setYoloMode] = useState(false);
  const [toolStats, setToolStats] = useState<ToolStats>(DEFAULT_TOOL_STATS);

  // Agent config
  const [agentOverride, setAgentOverride] = useState<string | null>(null);
  const [modelOverride, setModelOverride] = useState<string | null>(null);

  // Spec
  const [generatedSpec, setGeneratedSpec] = useState<GeneratedSpec | null>(null);

  const storageKey = `roundtable-session-${projectId}`;

  // Load session from localStorage on mount
  useEffect(() => {
    const savedSessionId = localStorage.getItem(storageKey);

    if (savedSessionId) {
      getRoundtableSession(projectId, savedSessionId)
        .then((session) => {
          setSessionId(session.id);
          setMode(session.mode as RoundtableMode);

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
          const chatMessages: ChatMessage[] = session.messages.map((msg: RoundtableMessage) => ({
            id: msg.id,
            agent: msg.agent,
            content: msg.content,
            timestamp: new Date(msg.timestamp),
            tokensUsed: msg.tokens_used,
          }));
          setMessages(chatMessages);

          // Load spec if any
          getSpecFromRoundtable(projectId, session.id)
            .then((specData) => {
              if (specData.spec) {
                setGeneratedSpec(specData.spec);
              }
            })
            .catch((err) => {
              console.warn("Failed to load spec:", err);
            });
        })
        .catch((err) => {
          console.warn("Failed to load saved session:", err);
          localStorage.removeItem(storageKey);
        })
        .finally(() => {
          setSessionLoaded(true);
        });
    } else {
      setSessionLoaded(true);
    }
  }, [projectId, storageKey]);

  // Save session ID to localStorage when it changes
  useEffect(() => {
    if (sessionId && sessionLoaded) {
      localStorage.setItem(storageKey, sessionId);
    }
  }, [sessionId, sessionLoaded, storageKey]);

  // Select a session by ID
  const selectSession = useCallback(
    async (newSessionId: string) => {
      if (newSessionId === sessionId) return;

      const session = await getRoundtableSession(projectId, newSessionId);
      setSessionId(session.id);
      setMode(session.mode as RoundtableMode);

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

      // Convert messages
      const chatMessages: ChatMessage[] = session.messages.map((msg: RoundtableMessage) => ({
        id: msg.id,
        agent: msg.agent,
        content: msg.content,
        timestamp: new Date(msg.timestamp),
        tokensUsed: msg.tokens_used,
      }));
      setMessages(chatMessages);

      // Load spec
      const specData = await getSpecFromRoundtable(projectId, newSessionId);
      if (specData.spec) {
        setGeneratedSpec(specData.spec);
      } else {
        setGeneratedSpec(null);
      }

      localStorage.setItem(storageKey, newSessionId);
    },
    [projectId, sessionId, storageKey]
  );

  // Clear current session
  const clearSession = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setGeneratedSpec(null);
    setToolsEnabled(true);
    setWriteEnabled(false);
    setYoloMode(false);
    setToolStats(DEFAULT_TOOL_STATS);
    setAgentOverride(null);
    setModelOverride(null);
    localStorage.removeItem(storageKey);
  }, [storageKey]);

  return {
    // Session state
    sessionId,
    setSessionId,
    mode,
    setMode,
    messages,
    setMessages,
    sessionLoaded,

    // Tools state
    toolsEnabled,
    setToolsEnabled,
    writeEnabled,
    setWriteEnabled,
    yoloMode,
    setYoloMode,
    toolStats,
    setToolStats,

    // Agent config
    agentOverride,
    setAgentOverride,
    modelOverride,
    setModelOverride,

    // Spec
    generatedSpec,
    setGeneratedSpec,

    // Actions
    selectSession,
    clearSession,
  };
}
