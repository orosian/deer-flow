import { useCallback, useMemo, useSyncExternalStore } from "react";

import {
  DEFAULT_LOCAL_SETTINGS,
  applyThreadModelOverride,
  applyThreadPresetOverride,
  type LocalSettings,
} from "./local";
import {
  getBaseSettingsSnapshot,
  getThreadModelSnapshot,
  getThreadPresetSnapshot,
  subscribe,
  updateLocalSettings,
  updateThreadSettings,
  type LocalSettingsSetter,
} from "./store";

export function useLocalSettings(): [LocalSettings, LocalSettingsSetter] {
  const settings = useSyncExternalStore(
    subscribe,
    getBaseSettingsSnapshot,
    () => DEFAULT_LOCAL_SETTINGS,
  );

  const setSettings = useCallback<LocalSettingsSetter>((key, value) => {
    updateLocalSettings(key, value);
  }, []);

  return [settings, setSettings];
}

export function useThreadSettings(
  threadId: string,
): [LocalSettings, LocalSettingsSetter] {
  const baseSettings = useSyncExternalStore(
    subscribe,
    getBaseSettingsSnapshot,
    () => DEFAULT_LOCAL_SETTINGS,
  );

  const threadModelName = useSyncExternalStore(
    subscribe,
    () => getThreadModelSnapshot(threadId),
    () => undefined,
  );

  const threadPresetId = useSyncExternalStore(
    subscribe,
    () => getThreadPresetSnapshot(threadId),
    () => undefined,
  );

  const settings = useMemo(
    () =>
      applyThreadPresetOverride(
        applyThreadModelOverride(baseSettings, threadModelName),
        threadPresetId,
      ),
    [baseSettings, threadModelName, threadPresetId],
  );

  const setSettings = useCallback<LocalSettingsSetter>(
    (key, value) => {
      updateThreadSettings(threadId, key, value);
    },
    [threadId],
  );

  return [settings, setSettings];
}
