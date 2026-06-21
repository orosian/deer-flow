"use client";

import { WorkflowIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { useGraphPresets, type GraphPreset } from "@/core/graph-presets";
import { useI18n } from "@/core/i18n/hooks";

import { WorkflowCard } from "./workflow-card";

export function WorkflowGallery() {
  const { t } = useI18n();
  const { presets, isLoading } = useGraphPresets();
  const router = useRouter();

  const handleStart = useCallback(
    (preset: GraphPreset) => {
      // Pre-allocate a threadId so the URL is shareable before the backend
      // has minted one. The preset id is carried in the query string — NOT
      // localStorage — because the LangGraph SDK rewrites the URL with the
      // real backend threadId on first send, and a localStorage write keyed
      // by the pre-alloc id would be orphaned by that rewrite (Pitfall 16).
      // The URL is the single source of truth: see useUrlPreset and
      // ChatPage.onStart which preserves window.location.search.
      const newThreadId = crypto.randomUUID();
      router.push(
        `/workspace/chats/${newThreadId}?preset=${encodeURIComponent(preset.id)}`,
      );
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
