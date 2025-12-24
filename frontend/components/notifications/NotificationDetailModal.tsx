"use client";

import { useState, useRef, useEffect } from "react";
import { X, AlertCircle, Send, Bot, User, RefreshCw, Loader2 } from "lucide-react";
import { clsx } from "clsx";
import { type Notification, type Task, fetchTask, startTask } from "@/lib/api";

interface NotificationDetailModalProps {
  notification: Notification | null;
  projectId: string;
  onClose: () => void;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export function NotificationDetailModal({
  notification,
  projectId,
  onClose,
}: NotificationDetailModalProps) {
  const [taskDetails, setTaskDetails] = useState<Task | null>(null);
  const [loading, setLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [userInput, setUserInput] = useState("");
  const [sending, setSending] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Fetch task details when notification changes
  useEffect(() => {
    if (notification?.task_id) {
      setLoading(true);
      fetchTask(projectId, notification.task_id)
        .then(setTaskDetails)
        .catch(() => setTaskDetails(null))
        .finally(() => setLoading(false));
    } else {
      setTaskDetails(null);
    }
    // Reset chat when notification changes
    setChatMessages([]);
  }, [notification, projectId]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  // Add initial assistant message when task details load
  useEffect(() => {
    if (taskDetails && notification) {
      const errorMsg = taskDetails.error_message || notification.message;
      setChatMessages([
        {
          role: "assistant",
          content: `I encountered an error while executing this task:\n\n"${errorMsg}"\n\nHow would you like me to proceed? I can:\n- **Retry** the failed criterion\n- **Skip** this criterion and continue\n- **Modify** the approach\n\nOr tell me what you'd like me to try differently.`,
          timestamp: new Date(),
        },
      ]);
    }
  }, [taskDetails, notification]);

  if (!notification) return null;

  const handleSendMessage = async () => {
    if (!userInput.trim() || sending) return;

    const userMessage: ChatMessage = {
      role: "user",
      content: userInput,
      timestamp: new Date(),
    };

    setChatMessages((prev) => [...prev, userMessage]);
    setUserInput("");
    setSending(true);

    // Simulate AI response (in a real implementation, this would call an API)
    setTimeout(() => {
      const assistantMessage: ChatMessage = {
        role: "assistant",
        content: `I understand. Let me analyze your request:\n\n"${userMessage.content}"\n\nTo implement this change, I would need to modify the execution approach. Would you like me to:\n\n1. **Retry with modifications** - Apply your suggestion and retry\n2. **Create a new plan** - Generate a new implementation plan\n3. **Escalate** - Mark this for manual review\n\nPlease let me know which option you prefer.`,
        timestamp: new Date(),
      };
      setChatMessages((prev) => [...prev, assistantMessage]);
      setSending(false);
    }, 1500);
  };

  const handleRetry = async () => {
    if (!notification.task_id || retrying) return;
    setRetrying(true);

    try {
      await startTask(projectId, notification.task_id, {
        agent_type: "gemini",
      });
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Task has been restarted. You can close this dialog and monitor progress in the task view.",
          timestamp: new Date(),
        },
      ]);
    } catch {
      setChatMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Failed to restart the task. Please try again or check the task status.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setRetrying(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-2xl max-h-[90vh] bg-slate-900 border border-slate-700 rounded-lg shadow-xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700 bg-slate-900/50">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-rose-400" />
            <div>
              <h2 className="text-sm font-medium text-slate-200">{notification.title}</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {notification.task_id || "No linked task"}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {notification.task_id && (
              <button
                onClick={handleRetry}
                disabled={retrying}
                className="btn-ghost p-2 rounded-lg text-amber-400 hover:text-amber-300 hover:bg-amber-950/30"
                title="Retry Task"
              >
                {retrying ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
              </button>
            )}
            <button onClick={onClose} className="btn-ghost p-2 rounded-lg" title="Close">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Split View Container */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {/* Top: Task Details */}
          <div className="h-2/5 min-h-[150px] border-b border-slate-700 overflow-auto p-4">
            {loading ? (
              <div className="flex items-center justify-center h-full">
                <Loader2 className="w-6 h-6 animate-spin text-slate-500" />
              </div>
            ) : taskDetails ? (
              <div className="space-y-3 text-sm">
                <div>
                  <span className="text-slate-500">Task:</span>
                  <span className="ml-2 text-slate-300">
                    {taskDetails.title || "Unknown"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">Status:</span>
                  <span className="ml-2 text-rose-400">
                    {taskDetails.status || "unknown"}
                  </span>
                </div>
                {taskDetails.current_criterion_id && (
                  <div>
                    <span className="text-slate-500">Failed at:</span>
                    <span className="ml-2 text-slate-300 mono">
                      {taskDetails.current_criterion_id}
                    </span>
                  </div>
                )}
                {taskDetails.error_message && (
                  <div>
                    <span className="text-slate-500 block mb-1">Error:</span>
                    <pre className="p-2 bg-rose-950/30 border border-rose-900/50 rounded text-xs text-rose-300 overflow-auto">
                      {taskDetails.error_message}
                    </pre>
                  </div>
                )}
                {taskDetails.progress_log && (
                  <div>
                    <span className="text-slate-500 block mb-1">Recent Log:</span>
                    <pre className="p-2 bg-slate-800/50 border border-slate-700 rounded text-xs text-slate-400 overflow-auto max-h-24">
                      {(taskDetails.progress_log || "")
                        .split("\n")
                        .slice(-5)
                        .join("\n")}
                    </pre>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center text-slate-500 py-8">
                <AlertCircle className="w-8 h-8 mx-auto mb-2 text-slate-600" />
                <p className="text-sm">{notification.message}</p>
              </div>
            )}
          </div>

          {/* Bottom: Chat */}
          <div className="h-3/5 flex flex-col min-h-0">
            {/* Chat Messages */}
            <div className="flex-1 overflow-auto p-4 space-y-4">
              {chatMessages.map((msg, index) => (
                <div
                  key={index}
                  className={clsx(
                    "flex gap-3",
                    msg.role === "user" ? "flex-row-reverse" : ""
                  )}
                >
                  <div
                    className={clsx(
                      "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
                      msg.role === "user" ? "bg-phosphor-500/20" : "bg-slate-700"
                    )}
                  >
                    {msg.role === "user" ? (
                      <User className="w-4 h-4 text-phosphor-400" />
                    ) : (
                      <Bot className="w-4 h-4 text-slate-400" />
                    )}
                  </div>
                  <div
                    className={clsx(
                      "max-w-[80%] p-3 rounded-lg text-sm",
                      msg.role === "user"
                        ? "bg-phosphor-500/20 text-slate-200"
                        : "bg-slate-800 text-slate-300"
                    )}
                  >
                    <div className="whitespace-pre-wrap">{msg.content}</div>
                    <span className="text-xs text-slate-500 mt-1 block">
                      {msg.timestamp.toLocaleTimeString()}
                    </span>
                  </div>
                </div>
              ))}
              {sending && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-slate-700 flex items-center justify-center">
                    <Bot className="w-4 h-4 text-slate-400" />
                  </div>
                  <div className="bg-slate-800 p-3 rounded-lg">
                    <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Chat Input */}
            <div className="p-4 border-t border-slate-700 bg-slate-900/50">
              <div className="flex gap-2">
                <textarea
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Describe what you'd like me to try..."
                  className="flex-1 p-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-phosphor-500"
                  rows={2}
                />
                <button
                  onClick={handleSendMessage}
                  disabled={!userInput.trim() || sending}
                  className={clsx(
                    "p-3 rounded-lg transition-colors",
                    userInput.trim() && !sending
                      ? "bg-phosphor-500 text-white hover:bg-phosphor-600"
                      : "bg-slate-700 text-slate-500 cursor-not-allowed"
                  )}
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
              <p className="text-xs text-slate-600 mt-2">
                Press Enter to send, Shift+Enter for new line
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
