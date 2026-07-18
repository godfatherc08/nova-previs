import { useReducedMotion } from "@/hooks/useReducedMotion";
import { cn } from "@/lib/utils";

interface LeaderCountdownProps {
  label?: string;
  className?: string;
}

const NUMERALS = ["5", "4", "3", "2", "1"];

export function LeaderCountdown({
  label = "Generating",
  className,
}: LeaderCountdownProps) {
  const reduced = useReducedMotion();

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 py-12",
        className,
      )}
      role="status"
      aria-live="polite"
      aria-label={`${label} — film leader countdown`}
    >
      <div
        className={cn(
          "relative flex h-24 w-24 items-center justify-center rounded-full border-2 border-graphite",
          !reduced && "animate-leader-spin",
        )}
      >
        <span className="font-mono text-3xl text-leader">
          {NUMERALS[Math.floor(Date.now() / 800) % NUMERALS.length]}
        </span>
      </div>
      <p className="font-mono text-xs uppercase tracking-[0.3em] text-silver">
        {label}
      </p>
      <p className="font-mono text-[10px] uppercase tracking-widest text-graphite">
        Picture start
      </p>
    </div>
  );
}
