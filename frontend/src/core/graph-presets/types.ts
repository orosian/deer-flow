/**
 * Spec for a single input port declared by a graph-harness preset.
 *
 * Mirrors the `input_ports` array returned by the backend `/api/graph-presets`
 * endpoint.  Field names are kept snake_case to match the wire format; the
 * frontend only translates `type` into a UI control.
 */
export interface InputPortSpec {
  /** Stable key — used as the search-param suffix (`input.<key>`). */
  key: string;
  /**
   * UI control hint.  The frontend picks a widget based on this value; an
   * unknown / missing type falls back to a multi-line textarea (see
   * `WorkflowStartDialog` for the mapping table).
   */
  type:
    | "string"
    | "text"
    | "multiline"
    | "number"
    | "boolean"
    | "enum"
    | "path"
    | "file"
    | "json";
  /** Whether the user must supply a non-empty value before confirming. */
  required?: boolean;
  /** Human-readable description shown beneath the label. */
  description?: string;
  /** Allowed values for `type === "enum"`.  Absent values fall back to free text. */
  enum_values?: string[];
  /** Optional default — applied when the dialog first opens. */
  default?: unknown;
  /** Optional semantic hint from the backend (e.g. `"url"`, `"email"`). */
  value_type?: string | null;
}

export interface GraphPreset {
  id: string;
  display_name: string;
  description: string;
  category: string;
  version: string;
  /** When absent or empty the gallery routes directly to the chat (v1 behaviour). */
  input_ports?: InputPortSpec[];
}

export interface GraphPresetsResponse {
  presets: GraphPreset[];
}