"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { GraphPreset } from "@/core/graph-presets";
import { useI18n } from "@/core/i18n/hooks";

interface WorkflowCardProps {
  preset: GraphPreset;
  /**
   * Fired when the user clicks "Start".  The parent (`WorkflowGallery`) owns
   * the dialog state — it inspects `preset.input_ports` and either opens
   * `WorkflowStartDialog` (when ports exist) or routes directly to the
   * chat (v1 behaviour).
   */
  onStart: (preset: GraphPreset) => void;
}

export function WorkflowCard({ preset, onStart }: WorkflowCardProps) {
  const { t } = useI18n();
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="line-clamp-2 text-base">
            {preset.display_name}
          </CardTitle>
          <Badge variant="secondary" className="shrink-0">
            v{preset.version}
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className="text-xs">
            {preset.category}
          </Badge>
          <code className="text-muted-foreground text-xs">{preset.id}</code>
        </div>
      </CardHeader>
      <CardContent className="flex-1">
        <CardDescription className="line-clamp-3">
          {preset.description}
        </CardDescription>
      </CardContent>
      <CardFooter>
        <Button className="w-full" onClick={() => onStart(preset)}>
          {t.workflows.start}
        </Button>
      </CardFooter>
    </Card>
  );
}