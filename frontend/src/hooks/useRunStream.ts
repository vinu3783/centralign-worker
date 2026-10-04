import { useEffect, useRef, useState } from "react";
import { api, runSocketUrl } from "../services/api";
import type { RunEvent } from "../types";

type Connection = "connecting" | "live" | "closed" | "polling";

/**
 * Live execution events for a run over WebSocket. Replays history on connect,
 * reconnects with ?after=<lastSeq> if the socket drops, and falls back to
 * polling if WebSockets are unavailable.
 */
export function useRunStream(runId: string | null) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const lastSeq = useRef(0);
  const finished = useRef(false);

  useEffect(() => {
    setEvents([]);
    lastSeq.current = 0;
    finished.current = false;
    if (!runId) return;

    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let failures = 0;
    let disposed = false;

    const push = (incoming: RunEvent[]) => {
      const fresh = incoming.filter((e) => e.seq > lastSeq.current);
      if (!fresh.length) return;
      lastSeq.current = fresh[fresh.length - 1].seq;
      if (fresh.some((e) => e.type === "run_completed")) finished.current = true;
      setEvents((prev) => [...prev, ...fresh]);
    };

    const poll = async () => {
      if (disposed) return;
      setConnection("polling");
      try {
        push(await api.runEvents(runId, lastSeq.current));
      } catch { /* retry on next tick */ }
      if (!finished.current) timer = window.setTimeout(poll, 1000);
    };

    const connect = () => {
      if (disposed) return;
      setConnection("connecting");
      ws = new WebSocket(runSocketUrl(runId, lastSeq.current));
      ws.onopen = () => { failures = 0; setConnection("live"); };
      ws.onmessage = (msg) => push([JSON.parse(msg.data) as RunEvent]);
      ws.onclose = () => {
        if (disposed) return;
        setConnection("closed");
        if (finished.current) return;
        failures += 1;
        if (failures > 3) void poll();
        else timer = window.setTimeout(connect, 500 * failures);
      };
    };
    connect();

    return () => {
      disposed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, [runId]);

  return { events, connection };
}
