import { useEffect, useRef } from "react";
import { usePointerFine } from "@/hooks/usePointerFine";
import { useReducedMotion } from "@/hooks/useReducedMotion";

interface KeyLightCursorProps {
  pointer: { x: number; y: number };
}

export function KeyLightCursor({ pointer }: KeyLightCursorProps) {
  const fine = usePointerFine();
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || !fine || reduced) return;
    ref.current.style.setProperty("--cursor-x", `${pointer.x}px`);
    ref.current.style.setProperty("--cursor-y", `${pointer.y}px`);
  }, [pointer.x, pointer.y, fine, reduced]);

  if (!fine || reduced) return null;

  return (
    <div
      ref={ref}
      aria-hidden
      className="pointer-events-none fixed inset-0 z-[90]"
      style={{
        background: `radial-gradient(600px circle at var(--cursor-x, 50%) var(--cursor-y, 50%), rgba(255,255,255,0.06), transparent 60%)`,
      }}
    />
  );
}
