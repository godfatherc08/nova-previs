/** Shared motion timing tokens — all gated by useReducedMotion at call sites. */

export const EASE_CINEMA = "cubic-bezier(0.22, 1, 0.36, 1)";
export const EASE_SNAP = "cubic-bezier(0.4, 0, 0.2, 1)";

export const DURATION_FAST = 200;
export const DURATION_MEDIUM = 400;
export const DURATION_SLOW = 800;
export const DURATION_MATCH_CUT = 1200;
export const DURATION_DOLLY = 1400;

export const LETTERBOX_TRANSITION = `var(--letterbox-duration, ${DURATION_SLOW}ms) ${EASE_CINEMA}`;

import type { CSSProperties } from "react";

export function motionStyle(
  reduced: boolean,
  props: Record<string, string | number>,
): CSSProperties {
  if (reduced) {
    const snap: CSSProperties = {};
    for (const [key, value] of Object.entries(props)) {
      if (key.includes("transition") || key.includes("animation")) continue;
      (snap as Record<string, string | number>)[key] = value;
    }
    return snap;
  }
  return props as CSSProperties;
}
