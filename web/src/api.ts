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

export interface Category {
  key: string;
  name: string;
  colour: string;
  icon: string;
  builtin: boolean;
  visible: boolean;
  transit: boolean;
  weight: number;
}

export interface PlaceProps {
  id: number;
  name: string;
  category: string;
  category_name: string;
  colour: string;
  source: string;
  address: string;
  lap_score: "likely" | "maybe" | "unlikely" | null;
  also: string;
  state: "unreviewed" | "confirmed" | "rejected";
  favourite: boolean;
  hidden: boolean;
  notes: string;
  own: boolean;
}

export interface PlaceCollection {
  type: "FeatureCollection";
  features: { type: "Feature"; geometry: { type: "Point"; coordinates: [number, number] }; properties: PlaceProps }[];
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const resp = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${method} ${path}: ${resp.status} ${await resp.text()}`);
  return resp;
}

export const getCategories = () => get<Category[]>("/api/categories");
export const getPlaces = () => get<PlaceCollection>("/api/places");
export const addCategory = (body: { name: string; colour: string }) =>
  send("POST", "/api/categories", body).then((r) => r.json() as Promise<Category>);
export const patchCategory = (key: string, body: Partial<Category>) =>
  send("PATCH", `/api/categories/${key}`, body).then((r) => r.json() as Promise<Category>);
export const deleteCategory = (key: string) => send("DELETE", `/api/categories/${key}`);
export const addPlace = (body: { category: string; name: string; lat: number; lon: number; address?: string; notes?: string }) =>
  send("POST", "/api/places", body);
export const patchPlace = (id: number, body: Partial<Pick<PlaceProps, "name" | "state" | "favourite" | "hidden" | "notes" | "address">> & { lat?: number; lon?: number }) =>
  send("PATCH", `/api/places/${id}`, body);
export const deletePlace = (id: number) => send("DELETE", `/api/places/${id}`);
