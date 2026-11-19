import { useCallback, useEffect, useRef, useState } from "react";
import { config } from "../config";

/** Polls every 2 s while the tab is visible (S13 step 6); `refresh` forces a load now. */
export function usePoll<T>(load: (() => Promise<T>) | null, key: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const tick = useCallback(async () => {
    const fn = loadRef.current;
    if (!fn) return;
    try {
      setData(await fn());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    }
  }, []);

  useEffect(() => {
    setData(null);
    if (!loadRef.current) return;
    let timer: number | undefined;
    const start = () => {
      if (timer === undefined) timer = window.setInterval(() => void tick(), config.pollMs);
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    const onVis = () => {
      if (document.hidden) stop();
      else {
        void tick();
        start();
      }
    };
    void tick();
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [key, tick]);

  return { data, error, refresh: tick };
}
