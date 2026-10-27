import type { Apartment, Settings } from "./api";

/** Trips per week the owner is trying out, by destination id (not saved). */
export type WhatIf = Record<number, number>;

/** An apartment's weekly minutes when some destinations' trips are overridden. */
export function weeklyTotal(a: Apartment, trips: WhatIf = {}): number | null {
  if (!a.weekly_parts || a.weekly_minutes == null) return null;
  let total = 0;
  for (const p of a.weekly_parts) {
    if (p.round_trip == null) continue;
    total += p.round_trip * (trips[p.id] ?? p.trips);
  }
  return Math.round(total * 10) / 10;
}

export function hoursMinutes(minutes: number | null | undefined): string {
  if (minutes == null) return "–";
  const m = Math.round(minutes);
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

/**
 * How robust the front-runner is: the share of single-destination changes of
 * plus or minus 20% trips under which the apartment with the lowest weekly
 * time is still the same one. Returns null with fewer than two ranked apartments.
 */
export function robustness(apts: Apartment[], trips: WhatIf = {}): { holds: number; of: number; leader: number } | null {
  const ranked = apts.filter((a) => weeklyTotal(a, trips) != null);
  if (ranked.length < 2) return null;
  const leader = (t: WhatIf) =>
    ranked.reduce((best, a) => (weeklyTotal(a, t)! < weeklyTotal(best, t)! ? a : best)).id;
  const base = leader(trips);
  const ids = new Set(ranked.flatMap((a) => a.weekly_parts!.map((p) => p.id)));
  let holds = 0, of = 0;
  for (const id of ids) {
    const current = trips[id] ?? ranked[0].weekly_parts!.find((p) => p.id === id)?.trips ?? 0;
    for (const factor of [0.8, 1.2]) {
      of++;
      if (leader({ ...trips, [id]: current * factor }) === base) holds++;
    }
  }
  return { holds, of, leader: base };
}

/** Lower is better: 100 for the lowest value, 0 for the highest, over the values given. */
function lowerIsBetter(values: (number | null)[]): (number | null)[] {
  const nums = values.filter((v): v is number => v != null);
  if (!nums.length) return values.map(() => null);
  const lo = Math.min(...nums), hi = Math.max(...nums);
  return values.map((v) => (v == null ? null : hi === lo ? 100 : (100 * (hi - v)) / (hi - lo)));
}

/**
 * The optional combined score (design 6.2): place score, weekly time and rent
 * scaled 0 to 100 over the apartments shown, mixed by the owner's weights.
 * An apartment missing a part is scored on the parts it has.
 */
export function combinedScores(apts: Apartment[], s: Pick<Settings, "w_place" | "w_time" | "w_rent">, trips: WhatIf = {}): Map<number, number | null> {
  const time = lowerIsBetter(apts.map((a) => weeklyTotal(a, trips)));
  const rent = lowerIsBetter(apts.map((a) => a.rent));
  const out = new Map<number, number | null>();
  apts.forEach((a, i) => {
    const parts: [number, number | null | undefined][] = [[s.w_place, a.place_score], [s.w_time, time[i]], [s.w_rent, rent[i]]];
    const used = parts.filter(([w, v]) => w > 0 && v != null) as [number, number][];
    const weight = used.reduce((t, [w]) => t + w, 0);
    out.set(a.id, weight ? Math.round((used.reduce((t, [w, v]) => t + w * v, 0) / weight) * 10) / 10 : null);
  });
  return out;
}
