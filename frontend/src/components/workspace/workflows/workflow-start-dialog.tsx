"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  type GraphPreset,
  type InputPortSpec,
} from "@/core/graph-presets";
import { useI18n } from "@/core/i18n/hooks";

interface WorkflowStartDialogProps {
  /** Preset whose `input_ports` drive the form.  `null` renders nothing. */
  preset: GraphPreset | null;
  /** Controlled open state — parent owns dialog visibility. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Fired with the resolved values map on Confirm. */
  onConfirm: (preset: GraphPreset, values: Record<string, unknown>) => void;
  /** Fired when the user dismisses the dialog without confirming. */
  onCancel: () => void;
}

type ControlKind =
  | "string"
  | "multiline"
  | "number"
  | "boolean"
  | "enum"
  | "json"
  | "file"
  | "fallback";

/**
 * Set of UI port types the dialog supports natively. Unknown types are
 * rendered as a fallback `<Textarea>` with a warning banner.
 * Exported for unit testing (see tests/unit/components/workspace/workflow-start-dialog.test.tsx).
 */
export const SUPPORTED_PORT_TYPES: ReadonlySet<string> = new Set<string>([
  "string",
  "text",
  "path",
  "multiline",
  "number",
  "boolean",
  "enum",
  "file",
  "json",
]);

export function controlKindFor(spec: InputPortSpec): ControlKind {
  if (spec.type === "boolean") return "boolean";
  if (spec.type === "number") return "number";
  if (spec.type === "enum") return "enum";
  if (spec.type === "json") return "json";
  if (spec.type === "file") return "file";
  if (spec.type === "multiline") return "multiline";
  if (spec.type === "string" || spec.type === "text" || spec.type === "path") {
    return "string";
  }
  return "fallback";
}

export function defaultValueFor(spec: InputPortSpec): unknown {
  if (Object.prototype.hasOwnProperty.call(spec, "default")) {
    return spec.default;
  }
  switch (controlKindFor(spec)) {
    case "boolean":
      return false;
    case "number":
      return "";
    case "enum":
      return spec.enum_values?.[0] ?? "";
    case "multiline":
    case "json":
    case "string":
    case "fallback":
    case "file":
      return "";
  }
}

export function isJsonValid(text: string): boolean {
  if (text.trim() === "") return true;
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

export function isRequiredFilled(spec: InputPortSpec, value: unknown): boolean {
  if (!spec.required) return true;
  if (controlKindFor(spec) === "boolean") return true;
  if (typeof value === "string") return value.trim().length > 0;
  return value !== undefined && value !== null;
}

export function fieldIdFor(presetId: string, key: string): string {
  return `wf-port-${presetId}-${key}`;
}

export function WorkflowStartDialog({
  preset,
  open,
  onOpenChange,
  onConfirm,
  onCancel,
}: WorkflowStartDialogProps) {
  const { t } = useI18n();
  const ports = useMemo(
    () => preset?.input_ports ?? [],
    [preset?.input_ports],
  );

  const [values, setValues] = useState<Record<string, unknown>>({});

  // Reset values whenever the active preset changes (or the dialog reopens).
  useEffect(() => {
    if (!preset) {
      setValues({});
      return;
    }
    const next: Record<string, unknown> = {};
    for (const port of ports) {
      next[port.key] = defaultValueFor(port);
    }
    setValues(next);
  }, [preset, ports]);

  if (!preset) return null;

  const isUnknownType = (type: string) => !SUPPORTED_PORT_TYPES.has(type);

  const handleConfirm = () => {
    onConfirm(preset, values);
  };

  const handleCancel = () => {
    onCancel();
    onOpenChange(false);
  };

  const requiredOk = ports.every((p) => isRequiredFilled(p, values[p.key]));
  const jsonOk = ports.every((p) => {
    if (controlKindFor(p) !== "json") return true;
    return isJsonValid(typeof values[p.key] === "string" ? (values[p.key] as string) : "");
  });
  const confirmDisabled = !requiredOk || !jsonOk;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.workflowStart.title}</DialogTitle>
          <DialogDescription>
            {t.workflowStart.description.replace("{{presetName}}", preset.display_name)}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
          {ports.length === 0 ? (
            <p className="text-muted-foreground text-sm">No inputs required.</p>
          ) : (
            ports.map((port) => {
              const id = fieldIdFor(preset.id, port.key);
              const kind = controlKindFor(port);
              const value = values[port.key];
              const fallback = isUnknownType(port.type);

              const updateValue = (next: unknown) => {
                setValues((current) => ({ ...current, [port.key]: next }));
              };

              return (
                <div key={port.key} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <label htmlFor={id} className="text-sm leading-none font-medium">
                      {port.key}
                      {port.required ? (
                        <span className="text-destructive ml-1">*</span>
                      ) : null}
                    </label>
                    <span className="text-muted-foreground text-xs">
                      {port.required
                        ? t.workflowStart.required
                        : t.workflowStart.optional}
                    </span>
                  </div>
                  {port.description ? (
                    <p className="text-muted-foreground text-xs">
                      {port.description}
                    </p>
                  ) : null}

                  {kind === "boolean" ? (
                    <div className="flex items-center gap-2 pt-1">
                      <Switch
                        id={id}
                        checked={Boolean(value)}
                        onCheckedChange={(checked) => updateValue(checked)}
                      />
                      <span className="text-muted-foreground text-xs">
                        {Boolean(value) ? "true" : "false"}
                      </span>
                    </div>
                  ) : kind === "multiline" ? (
                    <Textarea
                      id={id}
                      value={typeof value === "string" ? value : ""}
                      onChange={(event) => updateValue(event.target.value)}
                      required={port.required}
                    />
                  ) : kind === "number" ? (
                    <Input
                      id={id}
                      type="number"
                      value={typeof value === "string" ? value : ""}
                      onChange={(event) => updateValue(event.target.value)}
                      required={port.required}
                    />
                  ) : kind === "enum" ? (
                    port.enum_values && port.enum_values.length > 0 ? (
                      <Select
                        value={typeof value === "string" ? value : undefined}
                        onValueChange={(next) => updateValue(next)}
                      >
                        <SelectTrigger id={id} className="w-full">
                          <SelectValue placeholder="..." />
                        </SelectTrigger>
                        <SelectContent>
                          {port.enum_values.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      // No enum_values supplied — fall back to free-text input so
                      // the form is still submittable.
                      <Input
                        id={id}
                        type="text"
                        value={typeof value === "string" ? value : ""}
                        onChange={(event) => updateValue(event.target.value)}
                        required={port.required}
                      />
                    )
                  ) : kind === "json" ? (
                    <div className="space-y-1">
                      <Textarea
                        id={id}
                        className="min-h-24 font-mono text-xs"
                        value={typeof value === "string" ? value : ""}
                        onChange={(event) => updateValue(event.target.value)}
                        required={port.required}
                      />
                      {typeof value === "string" && value.length > 0 && !isJsonValid(value) ? (
                        <p className="text-destructive text-xs">
                          {t.workflowStart.invalidJson}
                        </p>
                      ) : null}
                    </div>
                  ) : kind === "file" ? (
                    <Input
                      id={id}
                      type="file"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        updateValue(file?.name ?? "");
                      }}
                      required={port.required}
                    />
                  ) : (
                    // string / text / path / unknown fallback
                    <Input
                      id={id}
                      type="text"
                      value={typeof value === "string" ? value : ""}
                      onChange={(event) => updateValue(event.target.value)}
                      required={port.required}
                    />
                  )}

                  {fallback ? (
                    <p className="text-muted-foreground text-xs italic">
                      {t.workflowStart.unknownType}
                    </p>
                  ) : null}
                </div>
              );
            })
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={handleCancel}>
            {t.workflowStart.cancel}
          </Button>
          <Button
            type="button"
            onClick={handleConfirm}
            disabled={confirmDisabled || ports.length === 0}
          >
            {t.workflowStart.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}