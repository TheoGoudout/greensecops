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

const SSE_BASE_URL = `${import.meta.env.VITE_API_URL}/api/v1/events/stream`
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30_000

/**
 * Opens a persistent SSE connection using native EventSource.
 * Token is passed as ?token= query param (EventSource cannot set custom headers).
 * Reconnects with exponential backoff on disconnect or error.
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

    function connect(): void {
      const currentToken = localStorage.getItem("access_token")
      if (!currentToken || closed) return

      const url = `${SSE_BASE_URL}?token=${encodeURIComponent(currentToken)}`
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
        if (closed) return
        retryTimer = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS)
          if (!closed) connect()
        }, reconnectDelay)
      }
    }

    connect()

    function forceReconnect() {
      if (retryTimer !== null) clearTimeout(retryTimer)
      retryTimer = null
      es?.close()
      es = null
      reconnectDelay = RECONNECT_BASE_MS
      connect()
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
