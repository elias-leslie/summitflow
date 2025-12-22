"use client";

import { useState } from "react";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import {
  Layers,
  Save,
  X,
  ChevronDown,
  ChevronRight,
  Boxes,
  TestTube2,
  MessageSquare,
  Loader2,
} from "lucide-react";
import { clsx } from "clsx";

export interface SpecTest {
  type: string;
  name: string;
  command?: string;
}

export interface SpecCapability {
  id: string;
  name: string;
  description?: string;
  tests: SpecTest[];
}

export interface SpecComponent {
  id: string;
  name: string;
  description?: string;
  priority?: number;
  capabilities: SpecCapability[];
}

export interface GeneratedSpec {
  components: SpecComponent[];
}

export interface SpecPreviewProps {
  spec: GeneratedSpec;
  onAccept: () => Promise<void>;
  onContinue: () => void;
  isLoading?: boolean;
}

// Test type badge colors
const testTypeColors: Record<string, string> = {
  pytest: "bg-yellow-900/50 text-yellow-200",
  vitest: "bg-green-900/50 text-green-200",
  playwright: "bg-purple-900/50 text-purple-200",
  api: "bg-blue-900/50 text-blue-200",
  ui: "bg-pink-900/50 text-pink-200",
  mypy: "bg-orange-900/50 text-orange-200",
  ruff: "bg-cyan-900/50 text-cyan-200",
};

function TestItem({ test }: { test: SpecTest }) {
  const typeColor = testTypeColors[test.type] || "bg-slate-700 text-slate-300";

  return (
    <div className="flex items-center gap-2 py-1.5 px-2 bg-slate-800/30 rounded text-xs">
      <TestTube2 className="w-3 h-3 text-slate-400 flex-shrink-0" />
      <span className="text-slate-300 flex-1 truncate">{test.name}</span>
      <Badge className={clsx("text-2xs px-1.5 py-0", typeColor)}>
        {test.type}
      </Badge>
    </div>
  );
}

function CapabilityRow({
  capability,
  isExpanded,
  onToggle,
}: {
  capability: SpecCapability;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const testCount = capability.tests.length;

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 w-full py-1.5 px-2 rounded hover:bg-slate-700/30 text-left"
      >
        {isExpanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
        )}
        <Boxes className="w-3.5 h-3.5 text-phosphor-400 flex-shrink-0" />
        <span className="text-sm text-slate-200 flex-1 truncate">
          {capability.name}
        </span>
        <Badge variant="outline" className="text-2xs">
          {testCount} test{testCount !== 1 ? "s" : ""}
        </Badge>
      </button>

      {isExpanded && testCount > 0 && (
        <div className="ml-7 space-y-1">
          {capability.tests.map((test, i) => (
            <TestItem key={`${capability.id}-test-${i}`} test={test} />
          ))}
        </div>
      )}
    </div>
  );
}

function ComponentCard({
  component,
  defaultExpanded = false,
}: {
  component: SpecComponent;
  defaultExpanded?: boolean;
}) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [expandedCaps, setExpandedCaps] = useState<Set<string>>(new Set());

  const capCount = component.capabilities.length;
  const testCount = component.capabilities.reduce(
    (sum, cap) => sum + cap.tests.length,
    0
  );

  const toggleCapability = (capId: string) => {
    setExpandedCaps((prev) => {
      const next = new Set(prev);
      if (next.has(capId)) {
        next.delete(capId);
      } else {
        next.add(capId);
      }
      return next;
    });
  };

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-3 w-full p-3 hover:bg-slate-700/20 text-left"
      >
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-slate-400" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-400" />
        )}
        <Layers className="w-4 h-4 text-phosphor-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-200 truncate">
              {component.name}
            </span>
            {component.priority !== undefined && (
              <Badge variant="phosphor" className="text-2xs">
                P{component.priority}
              </Badge>
            )}
          </div>
          {component.description && (
            <p className="text-xs text-slate-400 truncate mt-0.5">
              {component.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <Badge variant="outline" className="text-2xs">
            {capCount} cap{capCount !== 1 ? "s" : ""}
          </Badge>
          <Badge variant="outline" className="text-2xs">
            {testCount} test{testCount !== 1 ? "s" : ""}
          </Badge>
        </div>
      </button>

      {isExpanded && capCount > 0 && (
        <div className="px-3 pb-3 space-y-1 border-t border-slate-700/50 pt-2 ml-3">
          {component.capabilities.map((cap) => (
            <CapabilityRow
              key={cap.id}
              capability={cap}
              isExpanded={expandedCaps.has(cap.id)}
              onToggle={() => toggleCapability(cap.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function SpecPreview({
  spec,
  onAccept,
  onContinue,
  isLoading = false,
}: SpecPreviewProps) {
  const [isAccepting, setIsAccepting] = useState(false);

  const handleAccept = async () => {
    setIsAccepting(true);
    try {
      await onAccept();
    } finally {
      setIsAccepting(false);
    }
  };

  const components = spec.components || [];
  const totalComponents = components.length;
  const totalCapabilities = components.reduce(
    (sum, c) => sum + c.capabilities.length,
    0
  );
  const totalTests = components.reduce(
    (sum, c) =>
      sum + c.capabilities.reduce((s, cap) => s + cap.tests.length, 0),
    0
  );

  return (
    <div className="p-4 bg-phosphor-950/30 border border-phosphor-900/50 rounded-lg space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-phosphor-400" />
          <h4 className="text-sm font-medium text-phosphor-200">
            Spec Preview
          </h4>
          <div className="flex items-center gap-1.5 ml-2">
            <Badge variant="slate" className="text-2xs">
              {totalComponents} component{totalComponents !== 1 ? "s" : ""}
            </Badge>
            <Badge variant="slate" className="text-2xs">
              {totalCapabilities} capabilit{totalCapabilities !== 1 ? "ies" : "y"}
            </Badge>
            <Badge variant="slate" className="text-2xs">
              {totalTests} test{totalTests !== 1 ? "s" : ""}
            </Badge>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onContinue}
          disabled={isLoading || isAccepting}
          className="h-7 px-2"
        >
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Components Tree */}
      {totalComponents > 0 ? (
        <div className="space-y-2 max-h-80 overflow-y-auto">
          {components.map((component, index) => (
            <ComponentCard
              key={component.id}
              component={component}
              defaultExpanded={index === 0}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-6 text-slate-400">
          <Layers className="w-8 h-8 mx-auto mb-2 opacity-50" />
          <p className="text-sm">No components extracted from conversation.</p>
          <p className="text-xs mt-1">
            Try discussing specific features, capabilities, or system components.
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-between pt-2 border-t border-phosphor-900/30">
        <p className="text-xs text-slate-500">
          Review the spec above. Continue discussion to refine, or accept to create entities.
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onContinue}
            disabled={isAccepting}
          >
            <MessageSquare className="w-4 h-4 mr-2" />
            Continue Discussion
          </Button>
          <Button
            size="sm"
            onClick={handleAccept}
            disabled={isAccepting || totalComponents === 0}
            className="bg-phosphor-600 hover:bg-phosphor-500"
          >
            {isAccepting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <Save className="w-4 h-4 mr-2" />
                Accept & Create
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
