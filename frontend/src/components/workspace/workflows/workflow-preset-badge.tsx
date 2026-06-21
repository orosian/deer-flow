"use client";

import { WorkflowIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { useActivePreset } from "@/components/ai-elements/preset-selector";
import { Badge } from "@/components/ui/badge";
import { getThreadPresetId } from "@/core/settings/local";

/**
 * Renders a small badge in the chat header when the current thread was
 * created from a graph-harness preset. The preset id is persisted to
 * localStorage by `/workspace/workflows` and looked up here.
 */
export function WorkflowPresetBadge({ threadId }: { threadId: string }) {
  const [presetId, setPresetId] = useState<string | undefined>(undefined);
  useEffect(() => {
    setPresetId(getThreadPresetId(threadId) ?? undefined);
  }, [threadId]);
  // useActivePreset looks up the preset metadata by id; we read the display
  // name (or fall back to the id if the catalog hasn't loaded).
  const { displayName, isLoading } = useActivePreset(presetId);
  if (!presetId) return null;
  return (
    <Badge variant="secondary" className="gap-1">
      <WorkflowIcon className="h-3 w-3" />
      {isLoading ? presetId : `${displayName}`}
    </Badge>
  );
}
