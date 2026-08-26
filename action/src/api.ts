import type { DockerBuildPayload, IngestPayload, SamplePayload } from "./types"

const TIMEOUT_MS = 5000
const OIDC_AUDIENCE = "greensecops"

/** fetch with a hard timeout; null on any network error or timeout. */
async function fetchWithTimeout(
  url: string,
  init: RequestInit,
): Promise<Response | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

async function post(
  url: string,
  token: string,
  body: unknown,
): Promise<boolean> {
  const res = await fetchWithTimeout(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })
  return res?.ok ?? false
}

export async function ingestTelemetry(
  baseUrl: string,
  token: string,
  payload: IngestPayload,
): Promise<boolean> {
  return post(`${baseUrl}/api/v1/telemetry/runs`, token, payload)
}

export async function sendSample(
  baseUrl: string,
  token: string,
  payload: SamplePayload,
): Promise<boolean> {
  return post(`${baseUrl}/api/v1/telemetry/samples`, token, payload)
}

export async function refreshOidcToken(): Promise<string | null> {
  const requestUrl = process.env.ACTIONS_ID_TOKEN_REQUEST_URL
  const requestToken = process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN
  if (!requestUrl || !requestToken) return null
  const res = await fetchWithTimeout(
    `${requestUrl}&audience=${encodeURIComponent(OIDC_AUDIENCE)}`,
    { headers: { Authorization: `Bearer ${requestToken}` } },
  )
  if (!res?.ok) return null
  try {
    const data = (await res.json()) as { value?: string }
    return data.value ?? null
  } catch {
    return null
  }
}

/** Post one image build's measured facts. Best-effort, like every other probe. */
export async function ingestDockerBuild(
  baseUrl: string,
  token: string,
  payload: DockerBuildPayload,
): Promise<boolean> {
  return post(
    `${baseUrl.replace(/\/$/, "")}/api/v1/telemetry/docker-builds`,
    token,
    payload,
  )
}
