import { useEffect, useRef } from "react";

// Poll `fn` (async) every `intervalMs` WITHOUT overlapping and WITHOUT running while the browser
// tab is hidden.
//
// Skipping a tick whenever the previous call is still in-flight is the key guard: when the backend
// is slow, a naive setInterval keeps firing new requests on top of the stalled ones, piling up
// dozens of pending XHRs that exhaust the browser's ~6 connections-per-host — so the important
// requests (auth/me, the Leads list) can't even start and sit "pending" for minutes. This hook
// makes every global poller (incoming-call, WhatsApp unread, follow-up reminders, agent status)
// fire at most one request at a time and pause entirely when nobody is looking at the tab.
export function usePoll(fn, intervalMs) {
  const fnRef = useRef(fn);
  fnRef.current = fn; // always call the latest closure (avoids stale state without re-subscribing)

  useEffect(() => {
    let alive = true;
    let inFlight = false;
    const hidden = () => typeof document !== "undefined" && document.hidden;

    const tick = async () => {
      if (!alive || inFlight || hidden()) return;
      inFlight = true;
      try {
        await fnRef.current();
      } catch {
        /* each caller handles/ignores its own errors */
      } finally {
        inFlight = false;
      }
    };

    tick();
    const t = setInterval(tick, intervalMs);
    const onVis = () => { if (!hidden()) tick(); }; // refresh immediately when the tab is refocused
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVis);

    return () => {
      alive = false;
      clearInterval(t);
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVis);
    };
  }, [intervalMs]);
}
