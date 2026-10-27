export interface MapConfig {
  city: string;
  center: [number, number];
  zoom: number;
  bbox: [number, number, number, number];
  tiles: boolean;
}

export interface Dataset {
  status?: "ok" | "expiring" | "expired" | "unknown";
  valid_to?: string;
  credit?: string;
  fetched_at?: string;
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

export const getConfig = () => get<MapConfig>("/api/config");
export const getDatasets = () => get<Record<string, Dataset>>("/api/datasets");
