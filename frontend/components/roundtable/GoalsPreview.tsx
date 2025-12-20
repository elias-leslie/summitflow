"use client";

import { useState } from "react";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Input } from "../ui/input";
import { Badge } from "../ui/badge";
import {
  Target,
  Save,
  X,
  Pencil,
  Trash2,
  Plus,
} from "lucide-react";

export interface GeneratedGoal {
  code: string;
  name: string;
  description: string;
  category: string;
}

export interface GoalsPreviewProps {
  goals: GeneratedGoal[];
  onSave: (goals: GeneratedGoal[]) => Promise<void>;
  onClose: () => void;
  isLoading?: boolean;
}

const categoryColors: Record<string, string> = {
  performance: "bg-orange-900/50 text-orange-200",
  usability: "bg-blue-900/50 text-blue-200",
  security: "bg-red-900/50 text-red-200",
  automation: "bg-purple-900/50 text-purple-200",
  scalability: "bg-green-900/50 text-green-200",
  integration: "bg-cyan-900/50 text-cyan-200",
  general: "bg-slate-700 text-slate-300",
};

export function GoalsPreview({
  goals: initialGoals,
  onSave,
  onClose,
  isLoading = false,
}: GoalsPreviewProps) {
  const [goals, setGoals] = useState<GeneratedGoal[]>(initialGoals);
  const [editingGoalCode, setEditingGoalCode] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(goals);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  const handleGoalChange = (
    code: string,
    field: keyof GeneratedGoal,
    value: string
  ) => {
    setGoals(
      goals.map((g) => (g.code === code ? { ...g, [field]: value } : g))
    );
  };

  const handleDeleteGoal = (code: string) => {
    setGoals(goals.filter((g) => g.code !== code));
  };

  const handleAddGoal = () => {
    const newCode = `VG-NEW${Date.now().toString().slice(-4)}`;
    setGoals([
      ...goals,
      { code: newCode, name: "New Goal", description: "", category: "general" },
    ]);
    setEditingGoalCode(newCode);
  };

  return (
    <div className="p-4 bg-green-950/30 border border-green-900/50 rounded-lg space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target className="w-5 h-5 text-green-400" />
          <h4 className="text-sm font-medium text-green-200">
            Goals Preview ({goals.length})
          </h4>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
          disabled={isLoading || isSaving}
        >
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Goals List */}
      {goals.length > 0 && (
        <div className="space-y-2 max-h-72 overflow-y-auto">
          {goals.map((goal) => {
            const isEditing = editingGoalCode === goal.code;
            const categoryColor = categoryColors[goal.category] || categoryColors.general;

            return (
              <div
                key={goal.code}
                className="bg-slate-800/30 border border-slate-700/50 rounded-md p-3 space-y-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <Badge variant="outline" className="text-xs font-mono flex-shrink-0">
                      {goal.code}
                    </Badge>
                    {isEditing ? (
                      <Input
                        value={goal.name}
                        onChange={(e) =>
                          handleGoalChange(goal.code, "name", e.target.value)
                        }
                        className="h-7 bg-slate-800 border-slate-600 text-sm flex-1"
                      />
                    ) : (
                      <span className="text-sm font-medium text-slate-200 truncate">
                        {goal.name}
                      </span>
                    )}
                    <Badge className={`${categoryColor} text-xs flex-shrink-0`}>
                      {goal.category}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() =>
                        setEditingGoalCode(isEditing ? null : goal.code)
                      }
                      className="h-6 w-6 p-0"
                    >
                      <Pencil className="w-3 h-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteGoal(goal.code)}
                      className="h-6 w-6 p-0 text-rose-400 hover:text-rose-300"
                    >
                      <Trash2 className="w-3 h-3" />
                    </Button>
                  </div>
                </div>
                {isEditing ? (
                  <div className="space-y-2">
                    <Textarea
                      value={goal.description}
                      onChange={(e) =>
                        handleGoalChange(goal.code, "description", e.target.value)
                      }
                      placeholder="Goal description..."
                      className="bg-slate-800/50 border-slate-600 text-sm"
                      rows={2}
                    />
                    <div className="flex gap-2">
                      <Input
                        value={goal.code}
                        onChange={(e) =>
                          handleGoalChange(goal.code, "code", e.target.value)
                        }
                        placeholder="VG-CODE"
                        className="h-7 bg-slate-800 border-slate-600 text-xs font-mono w-24"
                      />
                      <select
                        value={goal.category}
                        onChange={(e) =>
                          handleGoalChange(goal.code, "category", e.target.value)
                        }
                        className="h-7 bg-slate-800 border border-slate-600 rounded-md text-xs px-2 text-slate-200"
                      >
                        <option value="performance">Performance</option>
                        <option value="usability">Usability</option>
                        <option value="security">Security</option>
                        <option value="automation">Automation</option>
                        <option value="scalability">Scalability</option>
                        <option value="integration">Integration</option>
                        <option value="general">General</option>
                      </select>
                    </div>
                  </div>
                ) : (
                  goal.description && (
                    <p className="text-xs text-slate-400 line-clamp-2">
                      {goal.description}
                    </p>
                  )
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Add Goal Button */}
      <Button
        variant="outline"
        size="sm"
        onClick={handleAddGoal}
        className="w-full border-dashed border-slate-600 text-slate-400 hover:text-slate-200"
      >
        <Plus className="w-4 h-4 mr-2" />
        Add Goal
      </Button>

      {/* Empty state */}
      {goals.length === 0 && (
        <div className="text-center py-6 text-slate-400">
          <Target className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No goals extracted from conversation.</p>
          <p className="text-xs mt-1">
            Try discussing strategic objectives, outcomes, or high-level goals.
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-end gap-2 pt-2 border-t border-green-900/30">
        <Button
          variant="ghost"
          size="sm"
          onClick={onClose}
          disabled={isSaving}
        >
          Cancel
        </Button>
        <Button
          size="sm"
          onClick={handleSave}
          disabled={isSaving || goals.length === 0}
          className="bg-green-600 hover:bg-green-500"
        >
          {isSaving ? (
            <>
              <span className="animate-spin mr-2">⏳</span>
              Saving...
            </>
          ) : (
            <>
              <Save className="w-4 h-4 mr-2" />
              Save Goals
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
