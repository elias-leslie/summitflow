"use client";

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui/sheet";
import { TerminalTabs } from "./TerminalTabs";

interface TerminalDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId?: string;
  projectPath?: string;
}

export function TerminalDrawer({ open, onOpenChange, projectId, projectPath }: TerminalDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-[60%] min-w-[800px] max-w-none p-0"
      >
        <SheetHeader className="flex flex-row items-center justify-between pr-12">
          <SheetTitle>
            Terminal{projectId ? ` - ${projectId}` : ""}
          </SheetTitle>
          <SheetClose onClose={() => onOpenChange(false)} />
        </SheetHeader>
        <div className="h-[calc(100%-60px)]">
          <TerminalTabs
            projectId={projectId}
            projectPath={projectPath}
            className="h-full"
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}
