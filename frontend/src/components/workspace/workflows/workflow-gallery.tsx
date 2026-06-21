"use client";

import { WorkflowIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { useGraphPresets, type GraphPreset } from "@/core/graph-presets";
import { useI18n } from "@/core/i18n/hooks";

import { WorkflowCard } from "./workflow-card";
import { WorkflowStartDialog } from "./workflow-start-dialog";

/**
 * Build the search-param string for the chat page.
 *
 * Format: `?preset=<id>&input.<key>=<value>` — the LangGraph SDK rewrites the
 * URL with the real backend threadId on first send and preserves
 * `window.location.search` (Pitfall 16).  Booleans serialize as `"true"` /
 * `"false"`; everything else is coerced to string via `String()` so numbers
 * don't appear as `NaN` in the URL.
 */
function buildSearchParams(preset: GraphPreset, values: Record<string, unknown>): string {
  const params = new URLSearchParams();
  params.set("preset", preset.id);
  for (const [key, raw] of Object.entries(values)) {
    if (raw === undefined || raw === null) continue;
    // Booleans → "true"/"false"; numbers → string; plain strings → as-is.
    // Objects/arrays → JSON so they don't render as "[object Object]".
    let stringified: string;
    if (typeof raw === "boolean") {
      stringified = raw ? "true" : "false";
    } else if (typeof raw === "string") {
      stringified = raw;
    } else if (typeof raw === "number" && Number.isFinite(raw)) {
      stringified = String(raw);
    } else if (typeof raw === "object") {
      stringified = JSON.stringify(raw);
    } else {
      stringified = String(raw);
    }
    if (stringified === "") continue;
    params.set(`input.${key}`, stringified);
  }
  return params.toString();
}

export function WorkflowGallery() {
  const { t } = useI18n();
  const { presets, isLoading } = useGraphPresets();
  const router = useRouter();

  const [dialogPreset, setDialogPreset] = useState<GraphPreset | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const navigateToChat = useCallback(
    (preset: GraphPreset, extraSearch?: string) => {
      // Pre-allocate a threadId so the URL is shareable before the backend
      // has minted one.  The preset id and any input port values are carried
      // in the query string — NOT localStorage — because the LangGraph SDK
      // rewrites the URL with the real backend threadId on first send, and a
      // localStorage write keyed by the pre-alloc id would be orphaned by
      // that rewrite (Pitfall 16).
      const newThreadId = crypto.randomUUID();
      const search = extraSearch ? `?${extraSearch}` : `?preset=${encodeURIComponent(preset.id)}`;
      router.push(`/workspace/chats/${newThreadId}${search}`);
    },
    [router],
  );

  const handleStart = useCallback((preset: GraphPreset) => {
    const hasPorts = (preset.input_ports ?? []).length > 0;
    if (!hasPorts) {
      // v1 behaviour — no inputs to configure, route directly to the chat.
      setDialogPreset(null);
      setDialogOpen(false);
      // Defer navigation to the next tick so the gallery's click handler can
      // complete without side-effects from a synchronous push.
      queueMicrotask(() => navigateToChat(preset));
      return;
    }
    setDialogPreset(preset);
    setDialogOpen(true);
  }, [navigateToChat]);

  const handleConfirm = useCallback(
    (preset: GraphPreset, values: Record<string, unknown>) => {
      const search = buildSearchParams(preset, values);
      setDialogOpen(false);
      setDialogPreset(null);
      queueMicrotask(() => navigateToChat(preset, search));
    },
    [navigateToChat],
  );

  const handleDialogOpenChange = useCallback((next: boolean) => {
    setDialogOpen(next);
    if (!next) setDialogPreset(null);
  }, []);

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

      <WorkflowStartDialog
        preset={dialogPreset}
        open={dialogOpen}
        onOpenChange={handleDialogOpenChange}
        onConfirm={handleConfirm}
        onCancel={() => {
          /* nothing to clean up — dialog state is reset in onOpenChange */
        }}
      />
    </div>
  );
}