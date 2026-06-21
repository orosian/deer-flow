"use client";

import { WorkflowIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

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
import { useGraphPresets, type GraphPreset } from "@/core/graph-presets";
import { useI18n } from "@/core/i18n/hooks";
import { saveThreadPresetId } from "@/core/settings/local";

export function WorkflowGallery() {
  const { t } = useI18n();
  const { presets, isLoading } = useGraphPresets();
  const router = useRouter();

  const handleStart = useCallback(
    (preset: GraphPreset) => {
      // Generate a new thread id; chat page reads preset_id from localStorage
      // and routes useStream(assistantId = `gh:${preset_id}`).
      const newThreadId = crypto.randomUUID();
      saveThreadPresetId(newThreadId, preset.id);
      router.push(`/workspace/chats/${newThreadId}`);
    },
    [router],
  );

  return (
    <div className="flex size-full flex-col">
      {/* Page header */}
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold">{t.workflows.title}</h1>
          <p className="text-muted-foreground mt-0.5 text-sm">
            {t.workflows.description}
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="text-muted-foreground flex h-40 items-center justify-center text-sm">
            {t.common.loading}
          </div>
        ) : presets.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
            <div className="bg-muted flex h-14 w-14 items-center justify-center rounded-full">
              <WorkflowIcon className="text-muted-foreground h-7 w-7" />
            </div>
            <div>
              <p className="font-medium">{t.workflows.emptyTitle}</p>
              <p className="text-muted-foreground mt-1 text-sm">
                {t.workflows.emptyDescription}
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {presets.map((preset) => (
              <WorkflowCard
                key={preset.id}
                preset={preset}
                onStart={handleStart}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function WorkflowCard({
  preset,
  onStart,
}: {
  preset: GraphPreset;
  onStart: (preset: GraphPreset) => void;
}) {
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
