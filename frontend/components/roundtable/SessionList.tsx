"use client";

import { useState, useCallback, useEffect } from "react";
import { clsx } from "clsx";
import { ScrollArea } from "../ui/scroll-area";
import { Button } from "../ui/button";
import {
  Plus,
  Bot,
  Sparkles,
  MessageSquare,
  Trash2,
  ChevronDown,
  ChevronRight,
  Clock,
  Users,
} from "lucide-react";
import {
  listRoundtableSessions,
  deleteRoundtableSession,
  RoundtableSessionInfo,
} from "@/lib/api";

interface SessionListProps {
  projectId: string;
  currentSessionId?: string;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  className?: string;
}

const MAX_SESSIONS = 25;

function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function getAgentModeIcon(agentMode: string) {
  switch (agentMode) {
    case "claude":
      return <Bot className="h-3.5 w-3.5 text-orange-500" />;
    case "gemini":
      return <Sparkles className="h-3.5 w-3.5 text-blue-500" />;
    default:
      return <Users className="h-3.5 w-3.5 text-purple-500" />;
  }
}

function getAgentModeLabel(agentMode: string) {
  switch (agentMode) {
    case "claude":
      return "Claude only";
    case "gemini":
      return "Gemini only";
    default:
      return "Both agents";
  }
}

export function SessionList({
  projectId,
  currentSessionId,
  onSelectSession,
  onNewSession,
  className,
}: SessionListProps) {
  const [sessions, setSessions] = useState<RoundtableSessionInfo[]>([]);
  const [isExpanded, setIsExpanded] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    try {
      const data = await listRoundtableSessions(projectId);
      setSessions(data);
    } catch (error) {
      console.error("Failed to load sessions:", error);
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const handleDelete = useCallback(
    async (e: React.MouseEvent, sessionId: string) => {
      e.stopPropagation();
      if (!confirm("Delete this session? This cannot be undone.")) return;

      setDeletingId(sessionId);
      try {
        await deleteRoundtableSession(projectId, sessionId);
        setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      } catch (error) {
        console.error("Failed to delete session:", error);
      } finally {
        setDeletingId(null);
      }
    },
    [projectId]
  );

  const isAtLimit = sessions.length >= MAX_SESSIONS;

  return (
    <div className={clsx("border rounded-lg bg-card", className)}>
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-3 hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <MessageSquare className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium text-sm">Sessions</span>
          <span className="text-xs text-muted-foreground">
            ({sessions.length}/{MAX_SESSIONS})
          </span>
        </div>
      </button>

      {isExpanded && (
        <div className="border-t">
          {/* New Session Button */}
          <div className="p-2 border-b">
            <Button
              onClick={onNewSession}
              variant="outline"
              size="sm"
              className="w-full"
              disabled={isAtLimit}
            >
              <Plus className="h-4 w-4 mr-1" />
              {isAtLimit ? "Session Limit Reached" : "New Session"}
            </Button>
            {isAtLimit && (
              <p className="text-xs text-muted-foreground mt-1 text-center">
                Delete old sessions to create new ones
              </p>
            )}
          </div>

          {/* Session List */}
          <ScrollArea className="h-64">
            {isLoading ? (
              <div className="p-4 text-center text-muted-foreground text-sm">
                Loading sessions...
              </div>
            ) : sessions.length === 0 ? (
              <div className="p-4 text-center text-muted-foreground text-sm">
                No sessions yet
              </div>
            ) : (
              <div className="p-1">
                {sessions.map((session) => (
                  <button
                    key={session.id}
                    onClick={() => onSelectSession(session.id)}
                    className={clsx(
                      "w-full text-left p-2 rounded-md mb-1 transition-colors group",
                      session.id === currentSessionId
                        ? "bg-primary/10 border border-primary/20"
                        : "hover:bg-muted/50"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        {/* Title or Preview */}
                        <div className="font-medium text-sm truncate">
                          {session.title || `Session ${session.id.slice(0, 8)}`}
                        </div>

                        {/* Meta info */}
                        <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                          {/* Agent Mode */}
                          <div
                            className="flex items-center gap-1"
                            title={getAgentModeLabel(session.agent_mode)}
                          >
                            {getAgentModeIcon(session.agent_mode)}
                          </div>

                          {/* Message count */}
                          <div className="flex items-center gap-0.5">
                            <MessageSquare className="h-3 w-3" />
                            {session.message_count}
                          </div>

                          {/* Time */}
                          <div className="flex items-center gap-0.5">
                            <Clock className="h-3 w-3" />
                            {formatRelativeTime(session.updated_at)}
                          </div>
                        </div>
                      </div>

                      {/* Delete button */}
                      <Button
                        variant="ghost"
                        size="sm"
                        className={clsx(
                          "h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity",
                          deletingId === session.id && "opacity-100"
                        )}
                        onClick={(e) => handleDelete(e, session.id)}
                        disabled={deletingId === session.id}
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </ScrollArea>
        </div>
      )}
    </div>
  );
}
