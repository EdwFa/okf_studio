"use client";

import { useCallback, useEffect, useState } from "react";

/** A boolean remembered in this browser (a collapsed panel, for example). Works without storage too. */
export function useStoredFlag(key: string, initial = false): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(initial);
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(key);
      if (stored !== null) setValue(stored === "1");
    } catch {
      // Storage is unavailable (private window): keep the default.
    }
  }, [key]);
  const set = useCallback(
    (next: boolean) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, next ? "1" : "0");
      } catch {
        // Not remembered, still applied.
      }
    },
    [key],
  );
  return [value, set];
}
