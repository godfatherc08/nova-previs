import { useReducedMotion } from "@/hooks/useReducedMotion";
import { LETTERBOX_TRANSITION } from "@/lib/motion";
import { cn } from "@/lib/utils";

export type LetterboxStage = "academy" | "widescreen" | "scope";

interface LetterboxProps {
  stage: LetterboxStage;
  children: React.ReactNode;
  className?: string;
}

export function Letterbox({ stage, children, className }: LetterboxProps) {
  const reduced = useReducedMotion();

  return (
    <div
      data-stage={stage}
      className={cn("relative flex min-h-screen flex-col", className)}
      style={
        {
          "--letterbox-duration": reduced ? "0ms" : undefined,
        } as React.CSSProperties
      }
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 z-40 bg-black"
        style={{
          height: "var(--letterbox-bar)",
          transition: `height ${LETTERBOX_TRANSITION}`,
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 z-40 bg-black"
        style={{
          height: "var(--letterbox-bar)",
          transition: `height ${LETTERBOX_TRANSITION}`,
        }}
      />
      <div
        className="relative z-10 mx-auto flex w-full max-w-[100vw] flex-1 flex-col px-4 py-[calc(var(--letterbox-bar)+1rem)]"
        style={{
          maxWidth: `min(100vw, calc((100vh - 2 * var(--letterbox-bar)) * var(--letterbox-ratio)))`,
          transition: `max-width ${LETTERBOX_TRANSITION}`,
        }}
      >
        {children}
      </div>
    </div>
  );
}
