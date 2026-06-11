import type { IngestPayload, SamplePayload } from "./types"

const TIMEOUT_MS = 5000
const OIDC_AUDIENCE = "greensecops"

async function post(
  url: string,
  token: string,
  body: unknown,
): Promise<boolean> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

export async function ingestTelemetry(
  baseUrl: string,
  token: string,
  payload: IngestPayload,
): Promise<boolean> {
  return post(`${baseUrl}/api/v1/telemetry/ingest`, token, payload)
}

export async function sendSample(
  baseUrl: string,
  token: string,
  payload: SamplePayload,
): Promise<boolean> {
  return post(`${baseUrl}/api/v1/telemetry/sample`, token, payload)
}

export async function refreshOidcToken(): Promise<string | null> {
  const requestUrl = process.env.ACTIONS_ID_TOKEN_REQUEST_URL
  const requestToken = process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN
  if (!requestUrl || !requestToken) return null
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(
      `${requestUrl}&audience=${encodeURIComponent(OIDC_AUDIENCE)}`,
      {
        headers: { Authorization: `Bearer ${requestToken}` },
        signal: controller.signal,
      },
    )
    if (!res.ok) return null
    const data = (await res.json()) as { value?: string }
    return data.value ?? null
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}
