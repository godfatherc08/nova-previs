import { useCallback, useRef } from "react";
import { usePointerFine } from "@/hooks/usePointerFine";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { cn } from "@/lib/utils";

/** Stylized Muybridge gallop — 12 monochrome silhouette frames, public-domain homage. */
const FRAME_COUNT = 12;

function horseFrame(index: number) {
  const phase = (index / FRAME_COUNT) * Math.PI * 2;
  const legA = Math.sin(phase) * 18;
  const legB = Math.sin(phase + Math.PI) * 18;
  return (
    <svg
      viewBox="0 0 120 80"
      className="h-full w-full"
      aria-hidden
      fill="currentColor"
    >
      <ellipse cx="60" cy="58" rx="38" ry="6" fill="var(--graphite)" opacity="0.4" />
      <path d="M22 48 Q35 28 55 32 Q72 22 88 30 Q95 34 92 42 L85 48 Q78 52 68 50 L58 54 Q48 58 38 54 Z" />
      <circle cx="82" cy="34" r="5" />
      <line x1="34" y1="52" x2={34 + legA * 0.15} y2={68 + Math.abs(legA) * 0.1} stroke="currentColor" strokeWidth="3" />
      <line x1="48" y1="54" x2={48 - legB * 0.12} y2={68 + Math.abs(legB) * 0.08} stroke="currentColor" strokeWidth="3" />
      <line x1="62" y1="52" x2={62 + legB * 0.14} y2={68 + Math.abs(legB) * 0.1} stroke="currentColor" strokeWidth="3" />
      <line x1="76" y1="48" x2={76 - legA * 0.13} y2={66 + Math.abs(legA) * 0.09} stroke="currentColor" strokeWidth="3" />
    </svg>
  );
}

interface MuybridgeHeroProps {
  pointerX: number;
  containerWidth: number;
}

export function MuybridgeHero({ pointerX, containerWidth }: MuybridgeHeroProps) {
  const fine = usePointerFine();
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);

  const getFrame = useCallback(() => {
    if (reduced) return Math.floor(FRAME_COUNT / 2);
    if (!fine || containerWidth <= 0) return 0;
    const ratio = Math.max(0, Math.min(1, pointerX / containerWidth));
    return Math.min(FRAME_COUNT - 1, Math.floor(ratio * FRAME_COUNT));
  }, [pointerX, containerWidth, fine, reduced]);

  const frame = getFrame();

  return (
    <div
      ref={containerRef}
      className="relative mx-auto w-full max-w-3xl vignette"
      role="img"
      aria-label="Muybridge galloping horse — move cursor to crank the animation"
    >
      <div className="flex gap-1 overflow-hidden border-y border-graphite bg-film-base py-3">
        {Array.from({ length: FRAME_COUNT }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "aspect-[3/2] flex-1 border border-graphite/50 bg-black p-1 transition-opacity duration-75",
              i === frame ? "opacity-100 text-light" : "opacity-25 text-silver",
            )}
          >
            {horseFrame(i)}
          </div>
        ))}
      </div>
      <p className="mt-3 text-center font-mono text-xs uppercase tracking-widest text-silver">
        {fine && !reduced
          ? "Crank the gallop — move your cursor"
          : "Twelve photographs proved a horse could fly"}
      </p>
    </div>
  );
}
