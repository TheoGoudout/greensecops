import { describe, expect, it } from "vitest"
import type { FixPublic } from "@/client"
import { applyPatches } from "./WorkflowFileViewer"

function makeFix(patch: string): FixPublic {
  return {
    id: Math.random().toString(),
    issue_id: "",
    status: "ready",
    diff_patch: patch,
    workflow_file_path: "",
    created_at: "",
    updated_at: "",
  } as unknown as FixPublic
}

describe("applyPatches", () => {
  it("returns original lines unchanged when no fixes", () => {
    const result = applyPatches(["line1", "line2", "line3"], [])
    expect(result.map((e) => e.text)).toEqual(["line1", "line2", "line3"])
    expect(result.every((e) => e.type === "normal")).toBe(true)
  })

  it("applies single fix: removes old line, adds new line", () => {
    const patch = `@@ -2,1 +2,1 @@
-line2
+replaced`
    const result = applyPatches(["line1", "line2", "line3"], [makeFix(patch)])
    expect(result.find((e) => e.type === "remove")?.text).toBe("line2")
    expect(result.find((e) => e.type === "add")?.text).toBe("replaced")
    expect(
      result.filter((e) => e.type === "normal").map((e) => e.text),
    ).toEqual(["line1", "line3"])
  })

  it("applies single fix: inserts line between existing lines", () => {
    const patch = `@@ -1,2 +1,3 @@
 line1
+inserted
 line2`
    const result = applyPatches(["line1", "line2", "line3"], [makeFix(patch)])
    expect(result.map((e) => e.text)).toEqual([
      "line1",
      "inserted",
      "line2",
      "line3",
    ])
    expect(result[1].type).toBe("add")
    expect(result[1].lineNum).toBeNull()
  })

  it("second fix correctly targets original line when first fix inserts lines before it", () => {
    // Fix A: insert 2 lines after line1
    const patchA = `@@ -1,2 +1,4 @@
 line1
+inserted1
+inserted2
 line2`

    // Fix B: replace line3 — generated from original, so oldStart=2 with line2 context
    const patchB = `@@ -2,2 +2,2 @@
 line2
-line3
+replaced3`

    const original = ["line1", "line2", "line3", "line4"]
    const result = applyPatches(original, [makeFix(patchA), makeFix(patchB)])
    const texts = result.map((e) => e.text)

    expect(texts[0]).toBe("line1")
    expect(texts[1]).toBe("inserted1")
    expect(texts[2]).toBe("inserted2")
    expect(texts[3]).toBe("line2")

    expect(result.find((e) => e.type === "remove")?.text).toBe("line3")
    expect(
      result.find((e) => e.type === "add" && e.text === "replaced3"),
    ).toBeTruthy()
    expect(result.find((e) => e.text === "inserted1")?.type).toBe("add")
    expect(result.find((e) => e.text === "inserted2")?.type).toBe("add")
    expect(texts[texts.length - 1]).toBe("line4")
  })

  it("three fixes: each targets original line number regardless of prior insertions", () => {
    const patchA = `@@ -1,1 +1,2 @@
 line1
+insertedA`

    const patchB = `@@ -3,1 +3,2 @@
 line3
+insertedB`

    const patchC = `@@ -5,1 +5,1 @@
-line5
+replaced5`

    const original = ["line1", "line2", "line3", "line4", "line5"]
    const result = applyPatches(original, [
      makeFix(patchA),
      makeFix(patchB),
      makeFix(patchC),
    ])

    expect(result.find((e) => e.text === "insertedA")?.type).toBe("add")
    expect(result.find((e) => e.text === "insertedB")?.type).toBe("add")
    expect(result.find((e) => e.type === "remove")?.text).toBe("line5")
    expect(result.find((e) => e.text === "replaced5")?.type).toBe("add")
  })

  it("second fix applies correctly via fuzz when patch offset is in modified-file space", () => {
    // Fix A inserts 2 lines after line1 (shifts subsequent lines by 2).
    // Fix B was generated against the modified file: oldStart=4 refers to
    // modified position 4, which is original line 2. Library fuzz handles this.
    const patchA = `@@ -1,2 +1,4 @@
 line1
+ins1
+ins2
 line2`

    const patchB = `@@ -4,1 +4,1 @@
-line2
+fixed2`

    const original = ["line1", "line2", "line3", "line4"]
    const result = applyPatches(original, [makeFix(patchA), makeFix(patchB)])
    expect(result.find((e) => e.type === "remove")?.text).toBe("line2")
    expect(
      result.find((e) => e.type === "add" && e.text === "fixed2"),
    ).toBeTruthy()
    expect(result.find((e) => e.text === "line4")?.type).toBe("normal")
  })
})
