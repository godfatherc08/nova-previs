import { useRef, useState } from "react";
import type { Shot } from "@/lib/api";
import { cn } from "@/lib/utils";

interface SequencePlayerProps {
  sequenceUrl: string | null;
  shots: Shot[];
  className?: string;
}

export function SequencePlayer({
  sequenceUrl,
  shots,
  className,
}: SequencePlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);

  const lockedShots = [...shots]
    .filter((s) => s.animatic_clip_url)
    .sort((a, b) => a.order - b.order);

  const jumpToShot = (index: number) => {
    if (!videoRef.current || lockedShots.length === 0) return;
    const segment = duration / lockedShots.length;
    videoRef.current.currentTime = index * segment;
  };

  return (
    <div className={cn("space-y-4", className)}>
      <div className="relative aspect-[2.39/1] w-full overflow-hidden bg-black vignette">
        {sequenceUrl ? (
          <video
            ref={videoRef}
            src={sequenceUrl}
            controls
            className="h-full w-full object-contain"
            onLoadedMetadata={(e) =>
              setDuration(e.currentTarget.duration)
            }
            onTimeUpdate={(e) =>
              setCurrentTime(e.currentTarget.currentTime)
            }
          />
        ) : (
          <div className="flex h-full items-center justify-center text-silver">
            Sequence not assembled yet
          </div>
        )}
      </div>

      {lockedShots.length > 0 && duration > 0 && (
        <div className="space-y-2">
          <div className="relative h-2 bg-graphite">
            <div
              className="absolute h-full bg-light transition-all"
              style={{ width: `${(currentTime / duration) * 100}%` }}
            />
            {lockedShots.map((shot, i) => (
              <button
                key={shot.shot_id}
                type="button"
                className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-silver hover:bg-key focus-visible:bg-key"
                style={{
                  left: `${(i / lockedShots.length) * 100}%`,
                }}
                onClick={() => jumpToShot(i)}
                aria-label={`Jump to shot ${shot.shot_id}`}
              />
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {lockedShots.map((shot, i) => (
              <button
                key={shot.shot_id}
                type="button"
                onClick={() => jumpToShot(i)}
                className="font-mono text-[10px] uppercase tracking-wider text-silver hover:text-light focus-visible:text-light"
              >
                {shot.shot_id}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
