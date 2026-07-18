import { useState } from "react";
import type { Shot } from "@/lib/api";
import { LeaderCountdown } from "./LeaderCountdown";
import { MatchCut } from "./MatchCut";
import { usePointerFine } from "@/hooks/usePointerFine";
import { cn } from "@/lib/utils";

const STATUS_LABELS: Record<Shot["status"], string> = {
  DRAFT: "Draft",
  REFINING: "Refining",
  LOCKED: "Locked",
  ANIMATIC_PENDING: "Generating animatic",
  ANIMATIC_READY: "Ready",
  ASSEMBLED: "Assembled",
};

interface ShotCardProps {
  shot: Shot;
  index: number;
  selected?: boolean;
  focused?: boolean;
  onClick?: () => void;
  showMatchCut?: boolean;
  onMatchCutComplete?: () => void;
}

export function ShotCard({
  shot,
  index,
  selected,
  focused,
  onClick,
  showMatchCut,
  onMatchCutComplete,
}: ShotCardProps) {
  const fine = usePointerFine();
  const [playing, setPlaying] = useState(false);

  const currentVersion = shot.versions.find(
    (v) => v.version === shot.current_version,
  );
  const frameUrl =
    shot.locked_frame_url ??
    currentVersion?.frame_url ??
    null;

  const isGenerating =
    shot.status === "DRAFT" ||
    shot.status === "REFINING" ||
    shot.status === "ANIMATIC_PENDING";

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group relative w-full text-left transition-all duration-300",
        fine && !focused && "rack-blur",
        fine && focused && "rack-focus",
        selected && "ring-2 ring-light",
      )}
    >
      <div className="film-strip-edge absolute bottom-0 left-0 top-0 w-3 opacity-40" />
      <div className="ml-4 border border-graphite bg-film-base">
        <div className="flex items-center justify-between border-b border-graphite px-3 py-2">
          <span className="font-mono text-xs text-silver">
            {String(index + 1).padStart(2, "0")}
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wider text-silver">
            {STATUS_LABELS[shot.status]}
          </span>
        </div>

        <div className="relative aspect-video bg-black">
          {showMatchCut &&
          shot.status === "ANIMATIC_READY" &&
          shot.animatic_clip_url ? (
            <MatchCut
              stillUrl={shot.locked_frame_url ?? frameUrl}
              clipUrl={shot.animatic_clip_url}
              active
              onComplete={onMatchCutComplete}
            />
          ) : isGenerating && !frameUrl ? (
            <LeaderCountdown
              label={
                shot.status === "ANIMATIC_PENDING"
                  ? "Generating animatic"
                  : "Generating frame"
              }
              className="h-full"
            />
          ) : frameUrl ? (
            <img
              src={frameUrl}
              alt={`Shot ${shot.shot_id} frame`}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full items-center justify-center p-4 text-center text-xs text-silver">
              {shot.description || shot.shot_id}
            </div>
          )}

          {shot.status === "ANIMATIC_READY" && shot.animatic_clip_url && !showMatchCut && (
            <div
              className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
              onClick={(e) => {
                e.stopPropagation();
                setPlaying((p) => !p);
              }}
            >
              {playing ? (
                <video
                  src={shot.animatic_clip_url}
                  muted
                  playsInline
                  autoPlay
                  className="h-full w-full object-cover"
                />
              ) : (
                <span className="font-mono text-xs uppercase tracking-widest text-light">
                  Play animatic
                </span>
              )}
            </div>
          )}
        </div>

        <div className="px-3 py-2">
          <p className="truncate font-mono text-xs text-light">
            {currentVersion?.spec.framing.shot_size ?? shot.description}
          </p>
          <p className="truncate text-xs text-silver">
            {currentVersion?.spec.intent ?? shot.description}
          </p>
        </div>

        {shot.error && (
          <p className="border-t border-graphite px-3 py-2 text-xs text-silver">
            {shot.error}
          </p>
        )}
      </div>
    </button>
  );
}
