import { useEffect, useRef } from "react"

export type SSEEventData = {
  event: string
  [key: string]: unknown
}

type SSEHandler = (data: SSEEventData) => void

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
          const payload = JSON.parse(e.data) as SSEEventData
          onEventRef.current(payload)
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

    return () => {
      closed = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      es?.close()
    }
  }, [])
}
