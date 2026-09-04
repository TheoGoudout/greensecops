import { describe, expect, it } from "vitest"
import {
  IDLE_POLL_MS,
  pollForActivity,
  pollWhileScanning,
  SCAN_POLL_MS,
} from "@/lib/scan-polling"

describe("pollForActivity", () => {
  it("slows down but never stops", () => {
    // The point of it: `pollWhileScanning` returns false on an idle page, so
    // work started anywhere else stays invisible until something refetches.
    expect(pollWhileScanning([])).toBe(false)
    expect(pollForActivity([])).toBe(IDLE_POLL_MS)
  })

  it("speeds up for fix work a scan status cannot see", () => {
    expect(
      pollForActivity([
        { activity: "generating", latest_scan_status: "completed" },
      ]),
    ).toBe(SCAN_POLL_MS)
  })

  it("speeds up for a running scan on a row that reports no activity", () => {
    // Belt and braces: a row from an older API, or a test double, carries no
    // `activity` — and treating that as idle would make a running scan take
    // half a minute to resolve on screen.
    expect(pollForActivity([{ latest_scan_status: "running" }])).toBe(
      SCAN_POLL_MS,
    )
  })

  it("is idle only when both signals are", () => {
    expect(
      pollForActivity([
        { activity: "idle", latest_scan_status: "completed" },
        { activity: "idle", latest_scan_status: "failed" },
      ]),
    ).toBe(IDLE_POLL_MS)
  })

  it("takes the fastest row on the page", () => {
    expect(
      pollForActivity([
        { activity: "idle", latest_scan_status: "completed" },
        { activity: "scanning" },
      ]),
    ).toBe(SCAN_POLL_MS)
  })
})
