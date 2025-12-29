"use client";

import { memo } from "react";
import { Button } from "../ui/button";
import { Loader2, Wand2, ChevronDown, ListChecks, Eye, Target, Layers } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface GenerateMenuItem {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
  iconColor: string;
  isLoading: boolean;
  loadingText: string;
  onGenerate: () => void;
  disabled?: boolean;
}

interface GenerateMenuProps {
  items: GenerateMenuItem[];
  isOpen: boolean;
  onToggle: () => void;
  disabled: boolean;
  isAnyLoading: boolean;
}

export const GenerateMenu = memo(function GenerateMenu({
  items,
  isOpen,
  onToggle,
  disabled,
  isAnyLoading,
}: GenerateMenuProps) {
  const loadingItem = items.find((item) => item.isLoading);

  return (
    <div className="relative">
      <Button
        type="button"
        onClick={onToggle}
        disabled={disabled || isAnyLoading}
        className="w-full bg-phosphor-500 hover:bg-phosphor-600 text-white"
      >
        {isAnyLoading && loadingItem ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            {loadingItem.loadingText}
          </>
        ) : (
          <>
            <Wand2 className="w-4 h-4 mr-2" />
            Generate from Discussion
            <ChevronDown className="w-4 h-4 ml-2" />
          </>
        )}
      </Button>
      {isOpen && !isAnyLoading && (
        <div className="absolute bottom-full left-0 right-0 mb-1 bg-slate-800 border border-slate-700 rounded-lg shadow-lg overflow-hidden z-10">
          {items.map((item, index) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={item.onGenerate}
                disabled={item.disabled}
                className={`w-full px-4 py-2.5 text-left text-sm text-slate-200 hover:bg-slate-700 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed ${index > 0 ? "border-t border-slate-700" : ""}`}
              >
                <Icon className={`w-4 h-4 ${item.iconColor}`} />
                <div>
                  <div className="font-medium">{item.label}</div>
                  <div className="text-xs text-slate-400">{item.description}</div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
});

// Pre-defined menu configurations for common use cases
export function useGenerateMenuItems({
  onGenerateFeatures,
  onGenerateVision,
  onGenerateGoals,
  onGenerateSpec,
  isGenerating,
  isGeneratingVision,
  isGeneratingGoals,
  isGeneratingSpec,
}: {
  onGenerateFeatures?: () => void;
  onGenerateVision?: () => void;
  onGenerateGoals?: () => void;
  onGenerateSpec?: () => void;
  isGenerating: boolean;
  isGeneratingVision: boolean;
  isGeneratingGoals: boolean;
  isGeneratingSpec: boolean;
}): GenerateMenuItem[] {
  return [
    {
      id: "features",
      label: "Generate Features",
      description: "Extract features with acceptance criteria",
      icon: ListChecks,
      iconColor: "text-phosphor-400",
      isLoading: isGenerating,
      loadingText: "Extracting Features...",
      onGenerate: onGenerateFeatures ?? (() => {}),
      disabled: !onGenerateFeatures,
    },
    {
      id: "vision",
      label: "Generate Vision",
      description: "Extract mission and narratives",
      icon: Eye,
      iconColor: "text-purple-400",
      isLoading: isGeneratingVision,
      loadingText: "Extracting Vision...",
      onGenerate: onGenerateVision ?? (() => {}),
      disabled: !onGenerateVision,
    },
    {
      id: "goals",
      label: "Generate Goals",
      description: "Extract strategic goals",
      icon: Target,
      iconColor: "text-green-400",
      isLoading: isGeneratingGoals,
      loadingText: "Extracting Goals...",
      onGenerate: onGenerateGoals ?? (() => {}),
      disabled: !onGenerateGoals,
    },
    {
      id: "spec",
      label: "Generate Spec (TDD)",
      description: "Extract components, capabilities, and tests",
      icon: Layers,
      iconColor: "text-phosphor-400",
      isLoading: isGeneratingSpec,
      loadingText: "Extracting Spec...",
      onGenerate: onGenerateSpec ?? (() => {}),
      disabled: !onGenerateSpec,
    },
  ];
}
