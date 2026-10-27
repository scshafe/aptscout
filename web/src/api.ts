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

export const STATUSES = ["interested", "contacted", "toured", "applied", "rejected", "signed"] as const;
export const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] as const;
export type Status = (typeof STATUSES)[number];
export type Compass = (typeof COMPASS)[number];

export interface Apartment {
  id: number;
  label: string;
  address: string;
  unit: string;
  lat: number | null;
  lon: number | null;
  location_source: "none" | "geocoder" | "manual";
  rent: number | null;
  rent_includes: string;
  fees: number | null;
  deposit: number | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  floor: number | null;
  floors_in_building: number | null;
  facing: Compass[];
  lease_months: number | null;
  available_from: string | null;
  pets: string;
  laundry: string;
  parking: string;
  listing_url: string;
  status: Status;
  notes: string;
  place_score?: number | null;
  minutes?: Record<string, number | null>;
}

export interface CategoryScore {
  key: string;
  name: string;
  weight: number;
  score: number;
  minutes: number | null;
  place: { id: number; name: string; lat: number; lon: number } | null;
  note: string;
  share: number;
  contribution: number;
}

export interface ApartmentDetail extends Apartment {
  score: { place_score: number | null; categories: CategoryScore[] };
  status_history: { status: string; at: string }[];
}

export type ApartmentInput = Partial<Omit<Apartment, "id" | "place_score" | "minutes">>;

export const getApartments = () => get<Apartment[]>("/api/apartments");
export const getApartment = (id: number) => get<ApartmentDetail>(`/api/apartments/${id}`);
export const addApartment = (body: ApartmentInput) =>
  send("POST", "/api/apartments", body).then((r) => r.json() as Promise<{ id: number }>);
export const patchApartment = (id: number, body: ApartmentInput) => send("PATCH", `/api/apartments/${id}`, body);
export const deleteApartment = (id: number) => send("DELETE", `/api/apartments/${id}`);
export const geocode = (q: string) =>
  get<{ label: string; lat: number; lon: number }[]>(`/api/geocode?q=${encodeURIComponent(q)}`);
