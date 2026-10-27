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
  weekly_minutes?: number | null;
  weekly_complete?: boolean;
  weekly_parts?: { id: number; round_trip: number | null; trips: number; weekly: number | null }[];
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
  weekly: { total: number | null; complete: boolean; destinations: WeeklyPart[] };
  status_history: { status: string; at: string }[];
}

export type ApartmentInput = Partial<Omit<Apartment, "id" | "place_score" | "minutes" | "weekly_minutes" | "weekly_complete" | "weekly_parts">>;

export const getApartments = () => get<Apartment[]>("/api/apartments");
export const getApartment = (id: number) => get<ApartmentDetail>(`/api/apartments/${id}`);
export const addApartment = (body: ApartmentInput) =>
  send("POST", "/api/apartments", body).then((r) => r.json() as Promise<{ id: number }>);
export const patchApartment = (id: number, body: ApartmentInput) => send("PATCH", `/api/apartments/${id}`, body);
export const deleteApartment = (id: number) => send("DELETE", `/api/apartments/${id}`);
export const geocode = (q: string) =>
  get<{ label: string; lat: number; lon: number }[]>(`/api/geocode?q=${encodeURIComponent(q)}`);

export const MODES = ["walk", "bike", "drive", "transit"] as const;
export const BANDS = ["weekday_rush", "weekday_midday", "evening", "saturday", "sunday"] as const;
export const BAND_LABEL: Record<(typeof BANDS)[number], string> = {
  weekday_rush: "Weekday rush hour", weekday_midday: "Weekday midday", evening: "Evening",
  saturday: "Saturday", sunday: "Sunday",
};
export const RULES = ["best", "nearest", "favourite", "mean_n"] as const;
export const RULE_LABEL: Record<(typeof RULES)[number], string> = {
  best: "Best by travel time", nearest: "Nearest", favourite: "My favourite", mean_n: "Average of the nearest N",
};

export interface Destination {
  id: number;
  name: string;
  kind: "place" | "category";
  address: string;
  lat: number | null;
  lon: number | null;
  category_key: string | null;
  selection_rule: (typeof RULES)[number];
  n: number;
  trips_per_week: number;
  mode: (typeof MODES)[number];
  time_band: (typeof BANDS)[number];
  return_band: (typeof BANDS)[number] | null;
  max_minutes: number | null;
}
export type DestinationInput = Partial<Omit<Destination, "id">>;

export interface WeeklyPart {
  id: number;
  name: string;
  trips: number;
  mode: string;
  place: { id: number; name: string; lat: number; lon: number } | null;
  out: number | null;
  back: number | null;
  round_trip: number | null;
  weekly: number | null;
  method: string | null;
  note: string;
  over_budget: boolean;
  max_minutes: number | null;
}

export interface Settings {
  combined_on: boolean;
  w_place: number;
  w_time: number;
  w_rent: number;
}

export const getDestinations = () => get<Destination[]>("/api/destinations");
export const addDestination = (body: DestinationInput) =>
  send("POST", "/api/destinations", body).then((r) => r.json() as Promise<{ id: number }>);
export const patchDestination = (id: number, body: DestinationInput) => send("PATCH", `/api/destinations/${id}`, body);
export const deleteDestination = (id: number) => send("DELETE", `/api/destinations/${id}`);
export const getSettings = () => get<Settings>("/api/settings");
export const putSettings = (body: Partial<Settings>) =>
  send("PUT", "/api/settings", body).then((r) => r.json() as Promise<Settings>);
