import { describe, expect, it } from "vitest";
import type { Apartment } from "./api";
import { combinedScores, hoursMinutes, robustness, weeklyTotal } from "./weeklyMath";

function apt(id: number, rent: number, score: number, parts: [number, number, number][]): Apartment {
  const weekly_parts = parts.map(([did, round_trip, trips]) => ({ id: did, round_trip, trips, weekly: round_trip * trips }));
  return {
    id, rent, place_score: score, weekly_parts, weekly_complete: true,
    weekly_minutes: weekly_parts.reduce((t, p) => t + p.weekly, 0),
  } as unknown as Apartment;
}

// destination 1 = job (5 trips), destination 2 = gym (3 trips); round trips in minutes
const near = apt(1, 2000, 60, [[1, 60, 5], [2, 10, 3]]);   // 330 min a week
const far = apt(2, 1500, 80, [[1, 90, 5], [2, 4, 3]]);     // 462 min a week

describe("weeklyTotal", () => {
  it("sums trips times round trip, with what-if overrides", () => {
    expect(weeklyTotal(near)).toBe(330);
    expect(weeklyTotal(near, { 1: 3 })).toBe(210);
    expect(weeklyTotal({ id: 9 } as Apartment)).toBeNull();
  });
  it("formats hours and minutes", () => {
    expect(hoursMinutes(330)).toBe("5h 30m");
    expect(hoursMinutes(null)).toBe("–");
  });
});

describe("robustness", () => {
  it("counts the variations under which the leader stays the leader", () => {
    const r = robustness([near, far])!;
    expect(r.leader).toBe(1);
    expect(r.of).toBe(4);
    expect(r.holds).toBe(4);   // the job dominates: the near apartment leads at +-20% on either
  });
  it("sees a leader that is not safe", () => {
    const a = apt(3, 1000, 50, [[1, 60, 5], [2, 20, 3]]);   // 360 a week
    const b = apt(4, 1000, 50, [[1, 70, 5], [2, 2, 3]]);    // 356: leads, but only just
    const r = robustness([a, b])!;
    expect(r.leader).toBe(4);
    expect(r.holds).toBeLessThan(r.of);   // 20% more job trips hands the lead to the other
  });
  it("needs two ranked apartments", () => {
    expect(robustness([near])).toBeNull();
  });
});

describe("combinedScores", () => {
  it("scales time and rent over the apartments shown", () => {
    const got = combinedScores([near, far], { w_place: 1, w_time: 1, w_rent: 1 });
    // near: place 60, time 100 (lowest), rent 0 (highest) -> 53.3; far: 80, 0, 100 -> 60
    expect(got.get(1)).toBe(53.3);
    expect(got.get(2)).toBe(60);
  });
  it("ignores zero weights and missing parts", () => {
    const noScore = { ...near, place_score: null } as Apartment;
    expect(combinedScores([noScore, far], { w_place: 1, w_time: 1, w_rent: 0 }).get(1)).toBe(100);
    expect(combinedScores([near], { w_place: 0, w_time: 0, w_rent: 0 }).get(1)).toBeNull();
  });
});
