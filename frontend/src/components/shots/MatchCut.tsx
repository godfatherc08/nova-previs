import { useEffect, useState } from "react";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { DURATION_MATCH_CUT, EASE_CINEMA } from "@/lib/motion";
import { cn } from "@/lib/utils";

interface MatchCutProps {
  stillUrl: string | null;
  clipUrl: string | null;
  active: boolean;
  onComplete?: () => void;
  className?: string;
}

export function MatchCut({
  stillUrl,
  clipUrl,
  active,
  onComplete,
  className,
}: MatchCutProps) {
  const reduced = useReducedMotion();
  const [phase, setPhase] = useState<"idle" | "hold" | "cut" | "done">("idle");

  useEffect(() => {
    if (!active || !stillUrl || !clipUrl) {
      setPhase("idle");
      return;
    }
    setPhase("hold");
    const holdTimer = setTimeout(() => setPhase("cut"), reduced ? 100 : 600);
    const doneTimer = setTimeout(() => {
      setPhase("done");
      onComplete?.();
    }, reduced ? 400 : DURATION_MATCH_CUT);
    return () => {
      clearTimeout(holdTimer);
      clearTimeout(doneTimer);
    };
  }, [active, stillUrl, clipUrl, reduced, onComplete]);

  if (!active || phase === "idle" || phase === "done") return null;

  return (
    <div
      className={cn("relative aspect-video w-full overflow-hidden bg-black", className)}
      aria-hidden
    >
      {stillUrl && (
        <img
          src={stillUrl}
          alt=""
          className={cn(
            "absolute inset-0 h-full w-full object-cover",
            phase === "cut" && "opacity-0",
          )}
          style={{
            transition: reduced
              ? "opacity 200ms"
              : `opacity 600ms ${EASE_CINEMA}`,
          }}
        />
      )}
      {clipUrl && (
        <video
          src={clipUrl}
          muted
          playsInline
          className={cn(
            "absolute inset-0 h-full w-full object-cover",
            phase === "hold" ? "opacity-0" : "opacity-100",
          )}
          style={{
            transition: reduced
              ? "opacity 200ms"
              : `opacity 600ms ${EASE_CINEMA}`,
          }}
        />
      )}
    </div>
  );
}
