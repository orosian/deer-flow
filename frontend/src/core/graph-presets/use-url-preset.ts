"use client";

import { useSearchParams } from "next/navigation";

/**
 * Reads the `?preset=<id>` query param from the current URL.
 *
 * The URL is the source of truth for the active graph-harness preset
 * (see v1.1 doc §3 — Pitfall 16). Earlier versions persisted this to
 * `localStorage[THREAD_PRESET_KEY_PREFIX + threadId]`, but that broke
 * when the LangGraph SDK rewrote the URL with the real backend
 * threadId — the new id had no preset entry, so the `gh:` routing
 * silently regressed to `lead_agent`.
 *
 * Returns `undefined` when the param is absent (regular chat thread).
 */
export function useUrlPreset(): string | undefined {
  const searchParams = useSearchParams();
  return searchParams.get("preset") ?? undefined;
}