import { useState } from "react";
import { Button } from "@/components/ui/button";
import { LeaderCountdown } from "./LeaderCountdown";
import type { Take } from "@/lib/api";

/**
 * Backlog 8.6: multi-take fan-out. Generate 2–3 parallel candidates for the
 * current spec and promote one to a real version. Candidates live under B2's
 * lifecycle-swept scratch/ prefix — unpromoted takes auto-expire, so this UI
 * never needs an explicit discard.
 */
interface TakePickerProps {
  disabled?: boolean;
  generating?: boolean;
  promoting?: boolean;
  takes: Take[] | null;
  errors: string[];
  onGenerate: (count: number) => void;
  onPromote: (takeId: string) => void;
}

export function TakePicker({
  disabled,
  generating,
  promoting,
  takes,
  errors,
  onGenerate,
  onPromote,
}: TakePickerProps) {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="space-y-3 border-t border-graphite p-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <p className="font-display text-sm uppercase text-light">
            Multi-take
          </p>
          <p className="text-xs text-silver">
            Fan out parallel takes, then promote your pick to a version.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={disabled || generating}
            onClick={() => onGenerate(2)}
          >
            2 takes
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={disabled || generating}
            onClick={() => onGenerate(3)}
          >
            3 takes
          </Button>
        </div>
      </div>

      {generating && <LeaderCountdown label="Generating takes" className="h-24" />}

      {takes && takes.length > 0 && (
        <>
          <div className="grid grid-cols-3 gap-2">
            {takes.map((take) => (
              <button
                key={take.take_id}
                type="button"
                onClick={() => setSelected(take.take_id)}
                className={
                  "relative aspect-video overflow-hidden rounded-sm border transition-colors " +
                  (selected === take.take_id
                    ? "border-light ring-1 ring-light"
                    : "border-graphite hover:border-silver")
                }
              >
                <img
                  src={take.frame_url}
                  alt={`Take ${take.take_id}`}
                  className="h-full w-full object-cover"
                />
                <span className="absolute bottom-0 left-0 bg-black/70 px-1 font-mono text-[10px] text-light">
                  {take.take_id}
                </span>
              </button>
            ))}
          </div>
          <Button
            size="sm"
            disabled={!selected || promoting}
            onClick={() => selected && onPromote(selected)}
          >
            {promoting ? "Promoting…" : "Promote selected take"}
          </Button>
        </>
      )}

      {errors.length > 0 && (
        <p className="text-xs text-[color:var(--warning,#e0a030)]">
          {errors.length} take{errors.length > 1 ? "s" : ""} failed and were
          skipped.
        </p>
      )}
    </div>
  );
}
