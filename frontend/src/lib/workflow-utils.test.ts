import { describe, expect, it } from "vitest"
import { combinePatchesForFile } from "./workflow-utils"

const HEADER = `diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index abc1234..def5678 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
`

describe("combinePatchesForFile", () => {
  it("returns empty string for empty input", () => {
    expect(combinePatchesForFile([])).toBe("")
  })

  it("returns empty string when no valid patches", () => {
    expect(combinePatchesForFile(["no hunk here", "also invalid"])).toBe("")
  })

  it("returns single patch unchanged", () => {
    const patch = `${HEADER}@@ -5,3 +5,3 @@
 context
-old line
+new line
 context`
    expect(combinePatchesForFile([patch])).toBe(patch)
  })

  it("deduplicates identical patches", () => {
    const patch = `${HEADER}@@ -5,3 +5,3 @@
 context
-old
+new
 context`
    expect(combinePatchesForFile([patch, patch])).toBe(patch)
  })

  it("combines two patches: later hunk gets newStart adjusted by earlier delta", () => {
    // Fix A at line 5: replaces 1 line with 3 lines (+2 net delta)
    const patchA = `${HEADER}@@ -5,3 +5,5 @@
 context
-old line
+new line 1
+new line 2
+new line 3
 context`

    // Fix B at line 20 in original (generated independently, newStart=20)
    const patchB = `${HEADER}@@ -20,3 +20,3 @@
 context
-another old line
+another new line
 context`

    const result = combinePatchesForFile([patchA, patchB])

    // Hunk A: cumulativeDelta=0 → adjustedNewStart=5; delta becomes newCount(5)-oldCount(3)=+2
    expect(result).toContain("@@ -5,3 +5,5 @@")
    // Hunk B: cumulativeDelta=+2 → adjustedNewStart=20+2=22
    expect(result).toContain("@@ -20,3 +22,3 @@")
  })

  it("sorts hunks by oldStart regardless of patch input order", () => {
    const patchA = `${HEADER}@@ -30 +30 @@
-late fix
+late fix corrected`

    const patchB = `${HEADER}@@ -10 +10 @@
-early fix
+early fix corrected`

    const result = combinePatchesForFile([patchA, patchB])
    const hunkLines = result.split("\n").filter((l) => l.startsWith("@@"))

    expect(hunkLines[0]).toContain("-10")
    expect(hunkLines[1]).toContain("-30")
  })

  it("accumulates delta correctly across three hunks", () => {
    // Hunk 1: line 5, oldCount=1 newCount=3 → delta +2
    const patch1 = `${HEADER}@@ -5 +5,3 @@
-one
+one
+extra1
+extra2`

    // Hunk 2: line 15, oldCount=2 newCount=1 → delta -1
    const patch2 = `${HEADER}@@ -15,2 +15 @@
-remove1
-remove2
+kept`

    // Hunk 3: line 40 in original, oldCount=1 newCount=1 → delta 0
    const patch3 = `${HEADER}@@ -40 +40 @@
-last
+last fixed`

    const result = combinePatchesForFile([patch1, patch2, patch3])

    // Hunk 1: cumulativeDelta=0 → newStart=5; cumulativeDelta becomes +2
    expect(result).toContain("@@ -5 +5,3 @@")
    // Hunk 2: cumulativeDelta=+2 → newStart=15+2=17; cumulativeDelta becomes +1
    expect(result).toContain("@@ -15,2 +17 @@")
    // Hunk 3: cumulativeDelta=+1 → newStart=40+1=41
    expect(result).toContain("@@ -40 +41 @@")
  })
})
