import { useState, useEffect, useRef, useCallback } from "react";
import { getQueueStatus, type QueueStatus } from "@/api/admin";

interface QueueEvent {
  type: string;
  article_id?: string;
  title?: string;
  stage?: string;
  duration_ms?: string;
  error?: string;
  value?: string;
  paused?: string;
  priority?: string;
  state?: string;                    // circuit breaker state
  consecutive_failures?: string;     // circuit breaker failure count
}

export function useQueueStream() {
  const [data, setData] = useState<QueueStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const reconnectRef = useRef<number>(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const maxReconnectDelay = 30000;

  // Initial load
  const refresh = useCallback(async () => {
    try {
      const snapshot = await getQueueStatus();
      setData(snapshot);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    // 1. Load initial snapshot
    refresh();

    // 2. Connect SSE with auto-reconnection
    const connect = () => {
      const controller = new AbortController();
      abortRef.current = controller;

      const token = localStorage.getItem("access_token");
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      fetch("/api/v1/admin/pipeline/queue/stream", {
        headers,
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          reconnectRef.current = 0; // Reset backoff on success
          setConnected(true);
          const reader = response.body?.getReader();
          if (!reader) return;

          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              const jsonStr = line.slice(6).trim();
              if (!jsonStr) continue;

              try {
                const event: QueueEvent = JSON.parse(jsonStr);
                setData((prev) => {
                  if (!prev) return prev;
                  return applyEvent(prev, event);
                });
              } catch {
                // skip
              }
            }
          }

          // Reader completed (server closed connection) — reconnect
          setConnected(false);
          const delay = Math.min(1000 * 2 ** reconnectRef.current, maxReconnectDelay);
          reconnectRef.current += 1;
          reconnectTimerRef.current = setTimeout(connect, delay);
        })
        .catch((err) => {
          if (err instanceof DOMException && err.name === "AbortError") return;
          setConnected(false);
          // Reconnect with exponential backoff
          const delay = Math.min(1000 * 2 ** reconnectRef.current, maxReconnectDelay);
          reconnectRef.current += 1;
          reconnectTimerRef.current = setTimeout(connect, delay);
        });
    };

    connect();

    return () => {
      abortRef.current?.abort();
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
    };
  }, [refresh]);

  return { data, connected, refresh };
}

function applyEvent(
  state: QueueStatus,
  event: QueueEvent,
): QueueStatus {
  const next = { ...state };
  const id = event.article_id ?? "";
  if (!id && !event.type.startsWith("circuit_breaker") && event.type !== "concurrency" && event.type !== "paused") {
    return state;
  }

  switch (event.type) {
    case "enqueued": {
      const priority = event.priority ?? "high";
      const newItem = {
        article_id: id,
        title: event.title ?? "",
        enqueued_at: String(Date.now() / 1000),
        position: state.queued.length + 1,
        priority,
      };
      next.queued = [...state.queued, newItem];
      if (priority === "high") {
        next.queued_high = [...(state.queued_high ?? []), newItem];
      } else {
        next.queued_low = [...(state.queued_low ?? []), newItem];
      }
      next.counts = {
        ...state.counts,
        queued: state.counts.queued + 1,
        queued_high: (state.counts.queued_high ?? 0) + (priority === "high" ? 1 : 0),
        queued_low: (state.counts.queued_low ?? 0) + (priority === "low" ? 1 : 0),
      };
      break;
    }

    case "processing": {
      const dequeuedItem = state.queued.find((a) => a.article_id === id);
      const dequeuedPriority = dequeuedItem?.priority;
      next.queued = state.queued.filter((a) => a.article_id !== id);
      if (state.queued_high) next.queued_high = state.queued_high.filter((a) => a.article_id !== id);
      if (state.queued_low) next.queued_low = state.queued_low.filter((a) => a.article_id !== id);
      next.processing = [
        ...state.processing,
        {
          article_id: id,
          title:
            event.title ??
            dequeuedItem?.title ??
            "",
          current_stage: "",
          started_at: String(Date.now() / 1000),
        },
      ];
      next.counts = {
        ...state.counts,
        queued: Math.max(0, state.counts.queued - 1),
        queued_high: dequeuedPriority === "high" ? Math.max(0, (state.counts.queued_high ?? 0) - 1) : (state.counts.queued_high ?? 0),
        queued_low: dequeuedPriority === "low" ? Math.max(0, (state.counts.queued_low ?? 0) - 1) : (state.counts.queued_low ?? 0),
        processing: state.counts.processing + 1,
      };
      break;
    }

    case "stage":
      next.processing = state.processing.map((a) =>
        a.article_id === id ? { ...a, current_stage: event.stage ?? "" } : a,
      );
      break;

    case "completed":
      next.processing = state.processing.filter((a) => a.article_id !== id);
      next.recent = [
        {
          article_id: id,
          title:
            state.processing.find((a) => a.article_id === id)?.title ?? "",
          status: "completed",
          duration_ms: event.duration_ms ?? "0",
          completed_at: String(Date.now() / 1000),
        },
        ...state.recent,
      ].slice(0, 50);
      next.counts = {
        ...state.counts,
        processing: Math.max(0, state.counts.processing - 1),
        completed: state.counts.completed + 1,
      };
      break;

    case "failed":
      next.processing = state.processing.filter((a) => a.article_id !== id);
      next.recent = [
        {
          article_id: id,
          title:
            state.processing.find((a) => a.article_id === id)?.title ?? "",
          status: "failed",
          error: event.error ?? "",
          completed_at: String(Date.now() / 1000),
        },
        ...state.recent,
      ].slice(0, 50);
      next.counts = {
        ...state.counts,
        processing: Math.max(0, state.counts.processing - 1),
        failed: state.counts.failed + 1,
      };
      break;

    case "concurrency":
      next.concurrency = {
        ...state.concurrency,
        target: parseInt(event.value ?? "0", 10),
      };
      break;

    case "paused":
      next.paused = event.paused === "1";
      break;

    case "circuit_breaker_open":
    case "circuit_breaker_half_open":
    case "circuit_breaker_closed":
    case "circuit_breaker_reset":
      next.circuitBreaker = {
        state: event.state ?? "closed",
        consecutiveFailures: parseInt(event.consecutive_failures ?? "0", 10),
      };
      break;
  }

  return next;
}
