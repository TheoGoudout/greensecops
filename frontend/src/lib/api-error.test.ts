import { describe, expect, it } from "vitest"
import { ApiError } from "@/client"
import { apiErrorDetail, extractErrorMessage } from "./api-error"

/** An ApiError carrying `detail`, the way the generated client builds one. */
function apiError(detail: unknown): ApiError {
  return new ApiError(
    { method: "POST", url: "/api/v1/workflow/repositories/x/scans" },
    {
      url: "/api/v1/workflow/repositories/x/scans",
      ok: false,
      status: 402,
      statusText: "Payment Required",
      body: { detail },
    },
    "Payment Required",
  )
}

// What `services/billing/errors.py` actually sends. `message` is a complete
// sentence naming what was used, the cap, when it resets and what to do next.
const QUOTA_DETAIL = {
  code: "quota_exceeded",
  message:
    "You have used all 100 analyses on the Free plan this period. " +
    "The allowance resets on 1 October. Upgrade to Starter for 1,000.",
  meter: "analyses",
  tier: "free",
  limit: 100,
  used: 100,
}

describe("apiErrorDetail", () => {
  it("reads the message out of a quota refusal", () => {
    // The bug: a quota 402 arrives as an *object*, and this returned
    // `undefined` for anything that was not a plain string. Every "Scan now"
    // and "Generate fixes" button puts this under its own failure title, so
    // the user saw "Could not queue scan" and nothing else — the one message
    // written to be actionable was the one these buttons could not show.
    expect(apiErrorDetail(apiError(QUOTA_DETAIL))).toBe(QUOTA_DETAIL.message)
  })

  it("reads a plain string detail", () => {
    expect(apiErrorDetail(apiError("Repository is not accessible"))).toBe(
      "Repository is not accessible",
    )
  })

  it("reads the first message out of a validation error", () => {
    expect(
      apiErrorDetail(apiError([{ msg: "branch is required", loc: ["body"] }])),
    ).toBe("branch is required")
  })

  it("returns undefined when there is nothing to add", () => {
    // The caller's toast title already says what failed; a generic sentence
    // underneath it is noise, so this stays undefined rather than inventing
    // one the way `extractErrorMessage` does.
    expect(apiErrorDetail(apiError(undefined))).toBeUndefined()
    expect(apiErrorDetail(apiError(""))).toBeUndefined()
    expect(apiErrorDetail(apiError([]))).toBeUndefined()
    expect(apiErrorDetail(new Error("network down"))).toBeUndefined()
  })

  it("ignores an object that is not a billing refusal", () => {
    expect(apiErrorDetail(apiError({ nope: true }))).toBeUndefined()
  })
})

describe("extractErrorMessage", () => {
  it("reads the same three shapes", () => {
    expect(extractErrorMessage(apiError(QUOTA_DETAIL))).toBe(
      QUOTA_DETAIL.message,
    )
    expect(extractErrorMessage(apiError("Nope"))).toBe("Nope")
    expect(extractErrorMessage(apiError([{ msg: "bad branch" }]))).toBe(
      "bad branch",
    )
  })

  it("falls back to a sentence, because its callers show no title", () => {
    expect(extractErrorMessage(apiError(undefined))).toBe(
      "Something went wrong.",
    )
  })
})
