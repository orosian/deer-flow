import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useGraphPresets } from "@/core/graph-presets";
import { cn } from "@/lib/utils";
import type { ComponentProps, ReactNode } from "react";

/**
 * PresetSelector — mirror of ``ModelSelector`` for graph-harness ``gh:``
 * presets. Unlike the model selector, presets are *read-only* once a
 * thread is created (the active preset is locked to the thread at
 * creation time, see ``graph-harness-integration.mdx``). The trigger is
 * therefore disabled in the workspace; consumers should still wire up
 * ``open`` / ``onOpenChange`` so the dialog can be opened from outside
 * the input box (e.g. the sidebar "New chat" flow).
 */

export type PresetSelectorProps = ComponentProps<typeof Dialog>;

export const PresetSelector = (props: PresetSelectorProps) => (
  <Dialog {...props} />
);

export type PresetSelectorTriggerProps = ComponentProps<typeof DialogTrigger>;

export const PresetSelectorTrigger = (props: PresetSelectorTriggerProps) => (
  <DialogTrigger {...props} />
);

export type PresetSelectorContentProps = ComponentProps<
  typeof DialogContent
> & {
  title?: ReactNode;
};

export const PresetSelectorContent = ({
  className,
  children,
  title = "Preset Selector",
  ...props
}: PresetSelectorContentProps) => (
  <DialogContent className={cn("p-0", className)} {...props}>
    <DialogTitle className="sr-only">{title}</DialogTitle>
    <Command className="**:data-[slot=command-input-wrapper]:h-auto">
      {children}
    </Command>
  </DialogContent>
);

export type PresetSelectorDialogProps = ComponentProps<typeof CommandDialog>;

export const PresetSelectorDialog = (props: PresetSelectorDialogProps) => (
  <CommandDialog {...props} />
);

export type PresetSelectorInputProps = ComponentProps<typeof CommandInput>;

export const PresetSelectorInput = ({
  className,
  ...props
}: PresetSelectorInputProps) => (
  <CommandInput className={cn("h-auto py-3.5", className)} {...props} />
);

export type PresetSelectorListProps = ComponentProps<typeof CommandList>;

export const PresetSelectorList = (props: PresetSelectorListProps) => (
  <CommandList {...props} />
);

export type PresetSelectorEmptyProps = ComponentProps<typeof CommandEmpty>;

export const PresetSelectorEmpty = (props: PresetSelectorEmptyProps) => (
  <CommandEmpty {...props} />
);

export type PresetSelectorGroupProps = ComponentProps<typeof CommandGroup>;

export const PresetSelectorGroup = (props: PresetSelectorGroupProps) => (
  <CommandGroup {...props} />
);

export type PresetSelectorItemProps = ComponentProps<typeof CommandItem>;

export const PresetSelectorItem = (props: PresetSelectorItemProps) => (
  <CommandItem {...props} />
);

export type PresetSelectorSeparatorProps = ComponentProps<
  typeof CommandSeparator
>;

export const PresetSelectorSeparator = (
  props: PresetSelectorSeparatorProps,
) => <CommandSeparator {...props} />;

export type PresetSelectorNameProps = ComponentProps<"span">;

export const PresetSelectorName = ({
  className,
  ...props
}: PresetSelectorNameProps) => (
  <span
    className={cn("flex-1 truncate text-left text-xs", className)}
    {...props}
  />
);

/**
 * Convenience hook: returns the active preset metadata (looked up by id)
 * plus a loading flag. Use inside the trigger to render the locked
 * preset's display name.
 */
export function useActivePreset(presetId: string | undefined): {
  displayName: string;
  category: string;
  isLoading: boolean;
} {
  const { presets, isLoading } = useGraphPresets();
  const match = presetId ? presets.find((p) => p.id === presetId) : undefined;
  return {
    displayName: match?.display_name ?? "Default Lead Agent",
    category: match?.category ?? "utility",
    isLoading,
  };
}
