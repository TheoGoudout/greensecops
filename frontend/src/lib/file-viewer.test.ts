import { describe, expect, it } from "vitest"
import { buildDiffEntries, computeSegments } from "./file-viewer"

describe("buildDiffEntries", () => {
  it("returns original lines unchanged when there is no fixed content", () => {
    const result = buildDiffEntries("line1\nline2\nline3")
    expect(result.map((e) => e.text)).toEqual(["line1", "line2", "line3"])
    expect(result.every((e) => e.type === "normal")).toBe(true)
  })

  it("returns original lines unchanged when fixed content is identical", () => {
    const result = buildDiffEntries("line1\nline2", "line1\nline2")
    expect(result.map((e) => e.text)).toEqual(["line1", "line2"])
    expect(result.every((e) => e.type === "normal")).toBe(true)
  })

  it("marks a replaced line as remove + add", () => {
    const result = buildDiffEntries(
      "line1\nline2\nline3",
      "line1\nreplaced\nline3",
    )
    expect(result.find((e) => e.type === "remove")?.text).toBe("line2")
    expect(result.find((e) => e.type === "add")?.text).toBe("replaced")
    expect(
      result.filter((e) => e.type === "normal").map((e) => e.text),
    ).toEqual(["line1", "line3"])
  })

  it("marks an inserted line as add without an original line number", () => {
    const result = buildDiffEntries(
      "line1\nline2\nline3",
      "line1\ninserted\nline2\nline3",
    )
    expect(result.map((e) => e.text)).toEqual([
      "line1",
      "inserted",
      "line2",
      "line3",
    ])
    expect(result[1].type).toBe("add")
    expect(result[1].lineNum).toBeNull()
  })

  it("numbers original lines continuously across removals", () => {
    const result = buildDiffEntries(
      "line1\nline2\nline3\nline4",
      "line1\nline4",
    )
    const removed = result.filter((e) => e.type === "remove")
    expect(removed.map((e) => e.text)).toEqual(["line2", "line3"])
    expect(removed.map((e) => e.lineNum)).toEqual([2, 3])
    expect(result.find((e) => e.text === "line4")?.lineNum).toBe(4)
  })

  it("handles multiple separate change regions", () => {
    const result = buildDiffEntries(
      "line1\nline2\nline3\nline4\nline5",
      "line1\nfixed2\nline3\nline4\nfixed5",
    )
    expect(
      result.filter((e) => e.type === "remove").map((e) => e.text),
    ).toEqual(["line2", "line5"])
    expect(result.filter((e) => e.type === "add").map((e) => e.text)).toEqual([
      "fixed2",
      "fixed5",
    ])
  })

  it("shows no diff when both sides end with trailing newline", () => {
    const result = buildDiffEntries("line1\nline2\n", "line1\nline2\n")
    expect(result.every((e) => e.type === "normal")).toBe(true)
    expect(result.map((e) => e.text)).toEqual(["line1", "line2"])
  })

  it("shows no spurious removed line when fullContent preserves trailing newline", () => {
    const result = buildDiffEntries("line1\nline2\n", "line1\nline2\n")
    const removals = result.filter((e) => e.type === "remove")
    expect(removals).toHaveLength(0)
  })
})

describe("computeSegments", () => {
  const lines = (n: number) =>
    Array.from({ length: n }, (_, i) => ({
      key: i,
      lineNum: i + 1,
      text: `line${i + 1}`,
      type: "normal" as const,
    }))

  it("shows a file whole when nothing is annotated or changed", () => {
    // Collapsing everything would leave the reader with an empty viewer.
    expect(computeSegments(lines(40), new Set())).toEqual([
      { kind: "lines", start: 0, end: 39 },
    ])
  })

  it("returns nothing for an empty file", () => {
    expect(computeSegments([], new Set())).toEqual([])
  })

  it("keeps context either side of an annotated line and folds the rest", () => {
    // Annotation on line 21 (index 20) => indices 15..25 stay visible.
    const segments = computeSegments(lines(40), new Set([21]))
    expect(segments).toEqual([
      { kind: "collapsed", start: 0, end: 14 },
      { kind: "lines", start: 15, end: 25 },
      { kind: "collapsed", start: 26, end: 39 },
    ])
  })

  it("merges two annotations whose context windows overlap", () => {
    const segments = computeSegments(lines(40), new Set([21, 24]))
    expect(segments.filter((s) => s.kind === "lines")).toEqual([
      { kind: "lines", start: 15, end: 28 },
    ])
  })

  it("always shows changed lines, annotated or not", () => {
    const entries = lines(20).map((line, i) =>
      i === 10 ? { ...line, type: "add" as const, lineNum: null } : line,
    )
    const visible = computeSegments(entries, new Set()).filter(
      (s) => s.kind === "lines",
    )
    expect(visible).toEqual([{ kind: "lines", start: 10, end: 10 }])
  })
})
