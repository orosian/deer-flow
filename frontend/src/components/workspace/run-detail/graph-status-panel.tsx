"use client";

import {
  CheckCircle2Icon,
  CircleDashedIcon,
  LoaderIcon,
  WorkflowIcon,
  XCircleIcon,
  type LucideIcon,
} from "lucide-react";

import { useActivePreset } from "@/components/ai-elements/preset-selector";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useThread } from "@/components/workspace/messages/context";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type NodeStatus = "pending" | "running" | "done" | "error";

interface NodeView {
  id: string;
  name: string;
  status: NodeStatus;
}

interface GraphStatusPanelProps {
  threadId: string;
  presetId: string | undefined;
}

const STATUS_META: Record<
  NodeStatus,
  {
    variant: "default" | "secondary" | "outline" | "destructive";
    icon: LucideIcon;
    key: "pending" | "running" | "done" | "error";
  }
> = {
  pending: { variant: "outline", icon: CircleDashedIcon, key: "pending" },
  running: { variant: "default", icon: LoaderIcon, key: "running" },
  done: { variant: "secondary", icon: CheckCircle2Icon, key: "done" },
  error: { variant: "destructive", icon: XCircleIcon, key: "error" },
};

/**
 * v1 simplified graph status panel.
 *
 * Renders a vertical list of nodes with status badges. Per the v2.1 roadmap we
 * intentionally do NOT ship a full React Flow / Mermaid visualisation yet — a
 * linear list keeps the panel readable in a 25%-width side panel and matches
 * what a `gh:*` preset typically surfaces to the user (3–6 planning / execution
 * steps).
 *
 * Data source: the active thread's todos (sourced via `useThread()` from
 * `ThreadContext`, which mirrors what `client.threads.getState()` returns).
 * The future SSE path can swap this hook for a `useStream`/`useThreadState`
 * subscription without changing the component shape.
 *
 * Graceful empty states:
 *   - `presetId` undefined  → "Start a workflow to see graph status"
 *   - preset active, no todos yet → "Waiting for the graph to start..."
 */
export function GraphStatusPanel({
  threadId: _threadId,
  presetId,
}: GraphStatusPanelProps) {
  const { t } = useI18n();
  const { thread } = useThread();
  const { displayName } = useActivePreset(presetId);

  if (!presetId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="bg-muted flex h-12 w-12 items-center justify-center rounded-full">
          <WorkflowIcon className="text-muted-foreground h-6 w-6" />
        </div>
        <div>
          <p className="text-sm font-medium">{t.graphStatus.title}</p>
          <p className="text-muted-foreground mt-1 text-xs">
            {t.graphStatus.emptyHint}
          </p>
        </div>
      </div>
    );
  }

  const nodes: NodeView[] = (thread.values.todos ?? []).map((todo, index) => {
    const status: NodeStatus =
      todo.status === "completed"
        ? "done"
        : todo.status === "in_progress"
          ? "running"
          : "pending";
    return {
      id: `node-${index}`,
      name: todo.content ?? `Step ${index + 1}`,
      status,
    };
  });

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-4 py-3">
        <h2 className="text-sm font-medium">{displayName}</h2>
        <p className="text-muted-foreground mt-0.5 text-xs">
          {t.graphStatus.subtitle}
        </p>
      </header>
      <ScrollArea className="min-h-0 flex-1">
        {nodes.length === 0 ? (
          <div className="text-muted-foreground px-4 py-6 text-center text-xs">
            {t.graphStatus.waitingForNodes}
          </div>
        ) : (
          <ul className="divide-y">
            {nodes.map((node) => {
              const meta = STATUS_META[node.status];
              const Icon = meta.icon;
              return (
                <li
                  key={node.id}
                  className="flex items-center gap-2 px-4 py-2 text-sm"
                >
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      node.status === "running" && "animate-spin",
                    )}
                  />
                  <span className="min-w-0 flex-1 truncate">{node.name}</span>
                  <Badge
                    variant={meta.variant}
                    className="shrink-0 text-xs"
                    data-testid={`graph-status-${node.status}`}
                  >
                    {t.graphStatus[meta.key]}
                  </Badge>
                </li>
              );
            })}
          </ul>
        )}
      </ScrollArea>
    </div>
  );
}
