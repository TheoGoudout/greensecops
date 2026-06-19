import { afterEach, beforeEach, describe, expect, it, mock } from "bun:test"
import { ingestTelemetry, refreshOidcToken, sendSample } from "../api"

const FAKE_INGEST_PAYLOAD = {
  workflow_run_id: 123,
  repository: "owner/repo",
  branch: "main",
  commit_sha: "abc123",
  workflow_name: "CI",
  runner_specs: {
    os: "Linux",
    arch: "x64",
    runner_name: "runner-1",
    platform: "linux",
    node_version: "v20",
    vcpus: 2,
    ram_total_gb: 8,
  },
  metrics: { collected_at: 1000 },
  phase: "started",
}

const FAKE_SAMPLE_PAYLOAD = {
  workflow_run_id: 123,
  cpu_percent: 50,
  ram_used_mb: 1024,
}

let originalFetch: typeof globalThis.fetch

beforeEach(() => {
  originalFetch = globalThis.fetch
})

afterEach(() => {
  globalThis.fetch = originalFetch
  delete process.env.ACTIONS_ID_TOKEN_REQUEST_URL
  delete process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN
})

describe("ingestTelemetry", () => {
  it("returns true on 2xx response", async () => {
    globalThis.fetch = mock(() =>
      Promise.resolve(new Response(null, { status: 200 })),
    )

    const result = await ingestTelemetry(
      "https://app.example.com",
      "token",
      FAKE_INGEST_PAYLOAD,
    )

    expect(result).toBe(true)
  })

  it("returns false on non-2xx response", async () => {
    globalThis.fetch = mock(() =>
      Promise.resolve(new Response(null, { status: 500 })),
    )

    const result = await ingestTelemetry(
      "https://app.example.com",
      "token",
      FAKE_INGEST_PAYLOAD,
    )

    expect(result).toBe(false)
  })

  it("returns false on network error", async () => {
    globalThis.fetch = mock(() => Promise.reject(new Error("network error")))

    const result = await ingestTelemetry(
      "https://app.example.com",
      "token",
      FAKE_INGEST_PAYLOAD,
    )

    expect(result).toBe(false)
  })
})

describe("sendSample", () => {
  it("returns true on 2xx response", async () => {
    globalThis.fetch = mock(() =>
      Promise.resolve(new Response(null, { status: 201 })),
    )

    const result = await sendSample(
      "https://app.example.com",
      "token",
      FAKE_SAMPLE_PAYLOAD,
    )

    expect(result).toBe(true)
  })

  it("returns false on non-2xx response", async () => {
    globalThis.fetch = mock(() =>
      Promise.resolve(new Response(null, { status: 401 })),
    )

    const result = await sendSample(
      "https://app.example.com",
      "token",
      FAKE_SAMPLE_PAYLOAD,
    )

    expect(result).toBe(false)
  })

  it("returns false on network error", async () => {
    globalThis.fetch = mock(() =>
      Promise.reject(new TypeError("failed to fetch")),
    )

    const result = await sendSample(
      "https://app.example.com",
      "token",
      FAKE_SAMPLE_PAYLOAD,
    )

    expect(result).toBe(false)
  })
})

describe("refreshOidcToken", () => {
  it("returns null when env vars are missing", async () => {
    const token = await refreshOidcToken()
    expect(token).toBeNull()
  })

  it("returns token value on success", async () => {
    process.env.ACTIONS_ID_TOKEN_REQUEST_URL = "https://token.example.com?id=1"
    process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN = "request-token"
    globalThis.fetch = mock(() =>
      Promise.resolve(
        new Response(JSON.stringify({ value: "oidc-token-123" }), {
          status: 200,
        }),
      ),
    )

    const token = await refreshOidcToken()

    expect(token).toBe("oidc-token-123")
  })

  it("returns null when response is not ok", async () => {
    process.env.ACTIONS_ID_TOKEN_REQUEST_URL = "https://token.example.com?id=1"
    process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN = "request-token"
    globalThis.fetch = mock(() =>
      Promise.resolve(new Response(null, { status: 403 })),
    )

    const token = await refreshOidcToken()

    expect(token).toBeNull()
  })

  it("returns null on fetch error", async () => {
    process.env.ACTIONS_ID_TOKEN_REQUEST_URL = "https://token.example.com?id=1"
    process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN = "request-token"
    globalThis.fetch = mock(() => Promise.reject(new Error("network error")))

    const token = await refreshOidcToken()

    expect(token).toBeNull()
  })
})
