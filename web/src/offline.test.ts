import { describe, expect, it } from "vitest";
import { discard, enqueue, flush, headingToCompass, load, type Store } from "./offline";

function fakeStore(): Store {
  const data = new Map<string, string>();
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

describe("queue", () => {
  it("keeps apartments in order and can discard one", () => {
    const s = fakeStore();
    enqueue({ address: "1 Fictional Ave" }, s);
    const two = enqueue({ address: "2 Fictional Ave" }, s)[1];
    expect(load(s).map((q) => q.body.address)).toEqual(["1 Fictional Ave", "2 Fictional Ave"]);
    expect(discard(two.id, s).map((q) => q.body.address)).toEqual(["1 Fictional Ave"]);
  });

  it("survives broken storage", () => {
    const broken: Store = { getItem: () => "{not json", setItem: () => {} };
    expect(load(broken)).toEqual([]);
    expect(load(undefined)).toEqual([]);
  });

  it("sends everything when the network is back", async () => {
    const s = fakeStore();
    enqueue({ address: "a" }, s);
    enqueue({ address: "b" }, s);
    const seen: string[] = [];
    const result = await flush(async (b) => void seen.push(b.address!), s);
    expect(seen).toEqual(["a", "b"]);
    expect(result).toEqual({ sent: 2, remaining: [] });
    expect(load(s)).toEqual([]);
  });

  it("stops at a network failure and keeps the rest in order", async () => {
    const s = fakeStore();
    for (const a of ["a", "b", "c"]) enqueue({ address: a }, s);
    let calls = 0;
    const result = await flush(async () => {
      if (++calls === 2) throw new TypeError("Failed to fetch");
    }, s);
    expect(result.sent).toBe(1);
    expect(result.remaining.map((q) => q.body.address)).toEqual(["b", "c"]);
  });

  it("keeps a rejected item with its error and carries on", async () => {
    const s = fakeStore();
    for (const a of ["a", "b"]) enqueue({ address: a }, s);
    let calls = 0;
    const result = await flush(async () => {
      if (++calls === 1) throw new Error("POST /api/apartments: 422 bad rent");
    }, s);
    expect(result.sent).toBe(1);
    expect(result.remaining).toHaveLength(1);
    expect(result.remaining[0].error).toContain("422");
    expect(result.remaining[0].body.address).toBe("a");
  });
});

describe("headingToCompass", () => {
  it("rounds to the nearest of eight points", () => {
    expect(headingToCompass(0)).toBe("N");
    expect(headingToCompass(22)).toBe("N");
    expect(headingToCompass(23)).toBe("NE");
    expect(headingToCompass(90)).toBe("E");
    expect(headingToCompass(200)).toBe("S");
    expect(headingToCompass(359)).toBe("N");
    expect(headingToCompass(-45)).toBe("NW");
    expect(headingToCompass(725)).toBe("N");
  });
});
