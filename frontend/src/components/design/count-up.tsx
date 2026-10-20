"use client";

import { useEffect, useState } from "react";

const prefersLessMotion = () =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A number that counts up from zero, unless the person asked for less motion. */
export function CountUp({ to, ms = 900 }: { to: number; ms?: number }) {
  const [still] = useState(prefersLessMotion);
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (still || to === 0 || typeof requestAnimationFrame !== "function") return;
    let frame = 0;
    const start = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / ms);
      setShown(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [to, ms, still]);
  return <>{still || to === 0 || typeof requestAnimationFrame !== "function" ? to : shown}</>;
}
