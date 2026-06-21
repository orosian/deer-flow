"use client";

import { WorkflowIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";

import { useGraphPanel } from "./graph-panel-context";

interface GraphPanelTriggerProps {
  /** Only render the trigger when a preset id is present. */
  presetId?: string;
}

export function GraphPanelTrigger({ presetId }: GraphPanelTriggerProps) {
  const { t } = useI18n();
  const { open, toggle } = useGraphPanel();

  if (!presetId) return null;

  return (
    <Tooltip content={t.graphPanel.triggerTooltip}>
      <Button
        className="text-muted-foreground hover:text-foreground"
        variant={open ? "secondary" : "ghost"}
        onClick={toggle}
        aria-pressed={open}
      >
        <WorkflowIcon />
        {t.graphPanel.trigger}
      </Button>
    </Tooltip>
  );
}
