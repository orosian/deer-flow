export interface GraphPreset {
  id: string;
  display_name: string;
  description: string;
  category: string;
  version: string;
}

export interface GraphPresetsResponse {
  presets: GraphPreset[];
}
