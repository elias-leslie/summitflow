"use client";

import { clsx } from "clsx";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import {
  getContextTypeIcon,
  getContextTypeColor,
} from "@/lib/formatters/observation-colors";

export interface ContextItem {
  id: string;
  type: string;
  title: string;
  summary?: string;
  token_estimate: number;
  created_at?: string;
}

export interface ExpandedContent {
  entity_id: string;
  type: string;
  content: Record<string, unknown>;
  token_count: number;
}

export interface ContextItemCardProps {
  item: ContextItem;
  isExpanded: boolean;
  isExpanding: boolean;
  expandedContent?: ExpandedContent;
  onExpand: (itemId: string) => void;
}

export function ContextItemCard({
  item,
  isExpanded,
  isExpanding,
  expandedContent,
  onExpand,
}: ContextItemCardProps) {
  const TypeIcon = getContextTypeIcon(item.type);

  return (
    <Card
      className="overflow-hidden cursor-pointer"
      onClick={() => onExpand(item.id)}
    >
      <CardHeader className="p-3 pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className={clsx("text-xs gap-1", getContextTypeColor(item.type))}
            >
              <TypeIcon className="h-3.5 w-3.5" />
              {item.type}
            </Badge>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span>~{item.token_estimate} tokens</span>
            {isExpanding ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : isExpanded ? (
              <ChevronUp className="h-3.5 w-3.5" />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" />
            )}
          </div>
        </div>
        <CardTitle className="text-sm leading-tight mt-1.5">
          {item.title}
        </CardTitle>
        {item.summary && (
          <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">
            {item.summary}
          </p>
        )}
      </CardHeader>

      {isExpanded && expandedContent && (
        <CardContent className="p-3 pt-0 border-t border-slate-200 dark:border-slate-800">
          <div className="text-xs text-slate-400 mb-2">
            Loaded {expandedContent.token_count} tokens
          </div>
          <pre className="text-xs text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
            {JSON.stringify(expandedContent.content, null, 2)}
          </pre>
        </CardContent>
      )}
    </Card>
  );
}
