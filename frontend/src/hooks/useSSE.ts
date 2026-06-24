import { useEffect, useRef } from "react"

export type SSEEventData = {
  event: string
  [key: string]: unknown
}

type SSEHandler = (data: SSEEventData) => void

const SSE_URL = "/api/v1/events/stream"
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30_000

/**
 * Opens a persistent SSE connection using fetch + ReadableStream.
 * Uses Authorization header (unlike native EventSource).
 * Reconnects with exponential backoff on disconnect.
 */
export function useSSE(onEvent: SSEHandler): void {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    const token = localStorage.getItem("access_token")
    if (!token) return

    let aborted = false
    const controller = new AbortController()
    let reconnectDelay = RECONNECT_BASE_MS

    async function connect(): Promise<void> {
      const currentToken = localStorage.getItem("access_token")
      if (!currentToken || aborted) return

      try {
        const response = await fetch(SSE_URL, {
          headers: { Authorization: `Bearer ${currentToken}` },
          signal: controller.signal,
        })

        if (!response.ok || !response.body) {
          throw new Error(`SSE connect failed: ${response.status}`)
        }

        reconnectDelay = RECONNECT_BASE_MS

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // SSE frames are separated by double newline
          const frames = buffer.split("\n\n")
          buffer = frames.pop() ?? ""

          for (const frame of frames) {
            if (!frame.trim() || frame.startsWith(":")) continue
            const dataLine = frame
              .split("\n")
              .find((l) => l.startsWith("data:"))
            if (!dataLine) continue
            try {
              const payload = JSON.parse(
                dataLine.slice(5).trim(),
              ) as SSEEventData
              onEventRef.current(payload)
            } catch {
              // malformed JSON — skip
            }
          }
        }
      } catch (err) {
        if (aborted) return
        if (err instanceof DOMException && err.name === "AbortError") return
        await new Promise((resolve) => setTimeout(resolve, reconnectDelay))
        reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS)
        if (!aborted) void connect()
      }
    }

    void connect()

    return () => {
      aborted = true
      controller.abort()
    }
  }, [])
}
