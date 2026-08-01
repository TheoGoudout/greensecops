import { describe, expect, it } from "vitest"
import { worstGrade } from "./grades"

describe("worstGrade", () => {
  it("returns null when nothing is graded", () => {
    expect(worstGrade([])).toBeNull()
    expect(worstGrade([null, undefined])).toBeNull()
  })

  it("ignores missing grades", () => {
    expect(worstGrade([null, "B", undefined])).toBe("B")
  })

  it("picks the worst letter", () => {
    expect(worstGrade(["A", "C", "B"])).toBe("C")
    expect(worstGrade(["F", "A"])).toBe("F")
  })

  it("ranks plus grades above their base letter", () => {
    expect(worstGrade(["A+", "A"])).toBe("A")
    expect(worstGrade(["A+++", "A++"])).toBe("A++")
    expect(worstGrade(["A+++", "B"])).toBe("B")
  })

  it("sorts an unknown grade last", () => {
    expect(worstGrade(["A", "???"])).toBe("???")
  })
})
