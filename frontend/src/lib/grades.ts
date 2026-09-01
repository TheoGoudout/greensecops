import type { Engine, RepoEngineGrade } from "@/client"

// Grades run best → worst. Plain string comparison gets this wrong for the
// plus grades ("A+" > "A" lexically, but it is the better grade), so ordering
// goes through this table.
export const GRADE_ORDER = [
  "A+++",
  "A++",
  "A+",
  "A",
  "B",
  "C",
  "D",
  "E",
  "F",
] as const

const gradeRank = (grade: string): number => {
  const rank = GRADE_ORDER.indexOf(grade as (typeof GRADE_ORDER)[number])
  // An unknown grade sorts last so it never masks a real one.
  return rank === -1 ? GRADE_ORDER.length : rank
}

/**
 * The worst grade in a list, ignoring missing ones. Returns null when nothing
 * has been graded yet — a repo can hold several scan targets, and the headline
 * grade is the worst of them.
 */
export function worstGrade(
  grades: readonly (string | null | undefined)[],
): string | null {
  const known = grades.filter((g): g is string => !!g)
  if (!known.length) return null
  return known.reduce((worst, g) =>
    gradeRank(g) > gradeRank(worst) ? g : worst,
  )
}

/**
 * One engine's average grade for a repository, or `null` if it has none.
 *
 * The repository endpoint reports a grade per engine. Reading the engine's own
 * entry is what stops a page showing the CI grade under a Docker heading, or
 * falling back to `worstGrade` over its targets — which is not an average, and
 * let one bad target set the header for all of them.
 */
export function engineGrade(
  repo: { engine_grades?: RepoEngineGrade[] } | undefined,
  engine: Engine,
): string | null {
  return repo?.engine_grades?.find((g) => g.engine === engine)?.grade ?? null
}
