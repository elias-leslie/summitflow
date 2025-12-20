"use client";

import { useState } from "react";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Input } from "../ui/input";
import { Badge } from "../ui/badge";
import {
  Eye,
  Save,
  X,
  Pencil,
  Sparkles,
  Target,
  BookOpen,
  Trash2,
  Plus,
} from "lucide-react";

export interface GeneratedMission {
  statement: string;
  values: string[];
}

export interface GeneratedNarrative {
  id: string;
  title: string;
  content: string;
  category: string;
}

export interface VisionPreviewProps {
  mission: GeneratedMission | null;
  narratives: GeneratedNarrative[];
  onSave: (
    mission: GeneratedMission | null,
    narratives: GeneratedNarrative[]
  ) => Promise<void>;
  onClose: () => void;
  isLoading?: boolean;
}

const categoryConfig: Record<
  string,
  { label: string; color: string; icon: typeof BookOpen }
> = {
  what: { label: "What", color: "bg-blue-900/50 text-blue-200", icon: Target },
  why: { label: "Why", color: "bg-purple-900/50 text-purple-200", icon: Sparkles },
  how: { label: "How", color: "bg-green-900/50 text-green-200", icon: BookOpen },
  who: { label: "Who", color: "bg-amber-900/50 text-amber-200", icon: Eye },
  principles: { label: "Principles", color: "bg-rose-900/50 text-rose-200", icon: BookOpen },
  general: { label: "General", color: "bg-slate-700 text-slate-300", icon: BookOpen },
};

export function VisionPreview({
  mission: initialMission,
  narratives: initialNarratives,
  onSave,
  onClose,
  isLoading = false,
}: VisionPreviewProps) {
  const [mission, setMission] = useState<GeneratedMission | null>(initialMission);
  const [narratives, setNarratives] = useState<GeneratedNarrative[]>(initialNarratives);
  const [editingMission, setEditingMission] = useState(false);
  const [editingNarrativeId, setEditingNarrativeId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await onSave(mission, narratives);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  const handleMissionChange = (field: keyof GeneratedMission, value: string | string[]) => {
    if (!mission) return;
    setMission({ ...mission, [field]: value });
  };

  const handleNarrativeChange = (
    id: string,
    field: keyof GeneratedNarrative,
    value: string
  ) => {
    setNarratives(
      narratives.map((n) => (n.id === id ? { ...n, [field]: value } : n))
    );
  };

  const handleDeleteNarrative = (id: string) => {
    setNarratives(narratives.filter((n) => n.id !== id));
  };

  const handleAddNarrative = () => {
    const newId = `narrative-${Date.now()}`;
    setNarratives([
      ...narratives,
      { id: newId, title: "New Narrative", content: "", category: "general" },
    ]);
    setEditingNarrativeId(newId);
  };

  return (
    <div className="p-4 bg-purple-950/30 border border-purple-900/50 rounded-lg space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Eye className="w-5 h-5 text-purple-400" />
          <h4 className="text-sm font-medium text-purple-200">Vision Preview</h4>
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

      {/* Mission Section */}
      {mission && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h5 className="text-xs font-medium text-purple-300 uppercase tracking-wide">
              Mission Statement
            </h5>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditingMission(!editingMission)}
              className="h-6 px-2"
            >
              <Pencil className="w-3 h-3" />
            </Button>
          </div>
          {editingMission ? (
            <Textarea
              value={mission.statement}
              onChange={(e) => handleMissionChange("statement", e.target.value)}
              className="bg-slate-800/50 border-purple-800 text-sm"
              rows={3}
            />
          ) : (
            <p className="text-sm text-slate-300 bg-slate-800/30 p-3 rounded-md">
              {mission.statement}
            </p>
          )}
          {mission.values.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {mission.values.map((value, i) => (
                <Badge
                  key={i}
                  className="bg-purple-900/30 text-purple-200 text-xs"
                >
                  {value}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Narratives Section */}
      {narratives.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h5 className="text-xs font-medium text-purple-300 uppercase tracking-wide">
              Narratives ({narratives.length})
            </h5>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleAddNarrative}
              className="h-6 px-2"
            >
              <Plus className="w-3 h-3 mr-1" />
              Add
            </Button>
          </div>
          <div className="space-y-2 max-h-64 overflow-y-auto">
            {narratives.map((narrative) => {
              const config = categoryConfig[narrative.category] || categoryConfig.general;
              const Icon = config.icon;
              const isEditing = editingNarrativeId === narrative.id;

              return (
                <div
                  key={narrative.id}
                  className="bg-slate-800/30 border border-slate-700/50 rounded-md p-3 space-y-2"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                      <Icon className="w-4 h-4 text-slate-400 flex-shrink-0" />
                      {isEditing ? (
                        <Input
                          value={narrative.title}
                          onChange={(e) =>
                            handleNarrativeChange(narrative.id, "title", e.target.value)
                          }
                          className="h-7 bg-slate-800 border-slate-600 text-sm"
                        />
                      ) : (
                        <span className="text-sm font-medium text-slate-200 truncate">
                          {narrative.title}
                        </span>
                      )}
                      <Badge className={`${config.color} text-xs flex-shrink-0`}>
                        {config.label}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setEditingNarrativeId(isEditing ? null : narrative.id)
                        }
                        className="h-6 w-6 p-0"
                      >
                        <Pencil className="w-3 h-3" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDeleteNarrative(narrative.id)}
                        className="h-6 w-6 p-0 text-rose-400 hover:text-rose-300"
                      >
                        <Trash2 className="w-3 h-3" />
                      </Button>
                    </div>
                  </div>
                  {isEditing ? (
                    <Textarea
                      value={narrative.content}
                      onChange={(e) =>
                        handleNarrativeChange(narrative.id, "content", e.target.value)
                      }
                      className="bg-slate-800/50 border-slate-600 text-sm"
                      rows={3}
                    />
                  ) : (
                    <p className="text-xs text-slate-400 line-clamp-2">
                      {narrative.content}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Empty state */}
      {!mission && narratives.length === 0 && (
        <div className="text-center py-6 text-slate-400">
          <Eye className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No vision content extracted from conversation.</p>
          <p className="text-xs mt-1">
            Try discussing the project&apos;s purpose, mission, or key narratives.
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-end gap-2 pt-2 border-t border-purple-900/30">
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
          disabled={isSaving || (!mission && narratives.length === 0)}
          className="bg-purple-600 hover:bg-purple-500"
        >
          {isSaving ? (
            <>
              <span className="animate-spin mr-2">⏳</span>
              Saving...
            </>
          ) : (
            <>
              <Save className="w-4 h-4 mr-2" />
              Save Vision
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
