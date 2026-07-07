import { useEffect, useRef } from "react"
import type { SSESignal } from "../client/types.gen"

export type { SSESignal }

export type SSEEventData = {
  event: SSESignal
  [key: string]: unknown
}

type SSEHandler = (data: SSEEventData) => void

const _SSE_SIGNALS = new Set<string>([
  "analysis.queued",
  "analysis.started",
  "analysis.completed",
  "analysis.failed",
  "analysis.skipped",
  "fix.skipped",
  "fix.generating",
  "fix.ready",
  "fix.delivering",
  "fix.delivered",
  "fix.failed",
  "fix.rejected",
  "pr.opened",
  "pr.updated",
  "pr.closed",
  "pr.merged",
  "installation.syncing",
  "installation.synced",
  "installation.created",
  "installation.deleted",
  "installation.suspended",
  "installation.unsuspended",
  "installation.updated",
  "repository.added",
  "repository.disabled",
  "repository.toggled",
  "repository.action_pr_opened",
])

function isSSESignal(s: unknown): s is SSESignal {
  return typeof s === "string" && _SSE_SIGNALS.has(s)
}

const SSE_API_BASE = `${import.meta.env.VITE_API_URL}/api/v1/events`
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30_000

/**
 * Opens a persistent SSE connection using native EventSource.
 *
 * EventSource cannot set an Authorization header, so instead of putting the
 * long-lived JWT in the URL, we exchange it (via a normal header-authenticated
 * request) for a short-lived, single-use ticket and open the stream with
 * ?ticket=. Reconnects with exponential backoff on disconnect or error.
 */
export function useSSE(onEvent: SSEHandler): void {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    const token = localStorage.getItem("access_token")
    if (!token) return

    let closed = false
    let reconnectDelay = RECONNECT_BASE_MS
    let es: EventSource | null = null
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    async function fetchTicket(authToken: string): Promise<string | null> {
      try {
        const res = await fetch(`${SSE_API_BASE}/ticket`, {
          method: "POST",
          headers: { Authorization: `Bearer ${authToken}` },
        })
        if (!res.ok) return null
        const data = (await res.json()) as { ticket?: string }
        return data.ticket ?? null
      } catch {
        return null
      }
    }

    function scheduleReconnect(): void {
      if (closed) return
      retryTimer = setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS)
        if (!closed) void connect()
      }, reconnectDelay)
    }

    async function connect(): Promise<void> {
      const currentToken = localStorage.getItem("access_token")
      if (!currentToken || closed) return

      const ticket = await fetchTicket(currentToken)
      if (closed) return
      if (!ticket) {
        scheduleReconnect()
        return
      }

      const url = `${SSE_API_BASE}/stream?ticket=${encodeURIComponent(ticket)}`
      es = new EventSource(url)

      es.onopen = () => {
        reconnectDelay = RECONNECT_BASE_MS
      }

      es.onmessage = (e: MessageEvent<string>) => {
        try {
          const raw = JSON.parse(e.data) as Record<string, unknown>
          if (isSSESignal(raw.event)) {
            onEventRef.current(raw as SSEEventData)
          }
        } catch {
          // malformed JSON — skip
        }
      }

      es.onerror = () => {
        es?.close()
        es = null
        scheduleReconnect()
      }
    }

    void connect()

    function forceReconnect() {
      if (retryTimer !== null) clearTimeout(retryTimer)
      retryTimer = null
      es?.close()
      es = null
      reconnectDelay = RECONNECT_BASE_MS
      void connect()
    }

    window.addEventListener("sse:reconnect", forceReconnect)

    return () => {
      closed = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      es?.close()
      window.removeEventListener("sse:reconnect", forceReconnect)
    }
  }, [])
}
