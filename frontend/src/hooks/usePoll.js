import { useEffect, useRef } from "react";

// Module-level in-flight registry, keyed by a stable poll `key`. Because it lives OUTSIDE any
// component instance, it de-dupes across React StrictMode's dev double-mount AND across multiple
// mounts of the same poller — so a given poll can only ever have ONE request in flight at a time.
// That is the fix for stacked pollers (/calls/active every 8s, etc.) piling up dozens of pending
// XHRs and exhausting the browser's ~6 connections-per-host when the backend is slow.
const _inflight = new Set();

// Poll `fn` (async) every `intervalMs`, but:
//  - NEVER overlap: skip a tick while a call with the same `key` is still in flight.
//  - PAUSE while the browser tab is hidden (don't poll a screen nobody is looking at); refresh
//    immediately when the tab is refocused.
// NOTE: `fn` must call API.get(..., { noCancel: true }) so a route change can't abort it into a
// never-settling promise (which would leave its key stuck in `_inflight` and stop the poller).
export function usePoll(fn, intervalMs, key) {
  const fnRef = useRef(fn);
  fnRef.current = fn; // always call the latest closure without re-subscribing the interval

  useEffect(() => {
    let alive = true;
    const hidden = () => typeof document !== "undefined" && document.hidden;

    const tick = async () => {
      if (!alive || hidden() || (key && _inflight.has(key))) return;
      if (key) _inflight.add(key);
      try {
        await fnRef.current();
      } catch {
        /* each caller handles/ignores its own errors */
      } finally {
        if (key) _inflight.delete(key);
      }
    };

    tick();
    const t = setInterval(tick, intervalMs);
    const onVis = () => { if (!hidden()) tick(); };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", onVis);

    return () => {
      alive = false;
      clearInterval(t);
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", onVis);
    };
  }, [intervalMs, key]);
}
