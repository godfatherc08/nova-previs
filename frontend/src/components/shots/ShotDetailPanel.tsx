import { useCallback, useState } from "react";
import type { Shot } from "@/lib/api";
import {
  CAMERA_ANGLES,
  GRADE_CONTRASTS,
  LIGHTING_KEYS,
  SHOT_SIZES,
  type ShotSpec,
} from "@/lib/shotSpec";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { RefineInput } from "./RefineInput";
import { LockConfirm } from "./LockConfirm";
import { LeaderCountdown } from "./LeaderCountdown";
import { cn } from "@/lib/utils";

interface ShotDetailPanelProps {
  shot: Shot | null;
  onSpecChange: (spec: ShotSpec) => void;
  onRefine: (instruction: string) => void;
  onLock: (version: number) => void;
  onVersionSelect: (version: number) => void;
  onGenerate?: () => void;
  previewVersion?: number | null;
  refining?: boolean;
  locking?: boolean;
  generating?: boolean;
  readOnly?: boolean;
}

function TagInput({
  value,
  onChange,
  placeholder,
  disabled,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const t = draft.trim();
    if (!t || value.includes(t)) return;
    onChange([...value, t]);
    setDraft("");
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {value.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-sm border border-graphite bg-black px-2 py-0.5 font-mono text-xs"
          >
            {tag}
            {!disabled && (
              <button
                type="button"
                className="text-silver hover:text-light"
                onClick={() => onChange(value.filter((v) => v !== tag))}
                aria-label={`Remove ${tag}`}
              >
                ×
              </button>
            )}
          </span>
        ))}
      </div>
      {!disabled && (
        <div className="flex gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={placeholder}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
          />
          <Button type="button" variant="secondary" size="sm" onClick={add}>
            Add
          </Button>
        </div>
      )}
    </div>
  );
}

export function ShotDetailPanel({
  shot,
  onSpecChange,
  onRefine,
  onLock,
  onVersionSelect,
  onGenerate,
  previewVersion,
  refining,
  locking,
  generating,
  readOnly,
}: ShotDetailPanelProps) {
  // The version being viewed: an explicitly previewed older version (backlog
  // 3.7 scrub), else the current one.
  const viewedVersion =
    shot?.versions.find((v) => v.version === previewVersion) ??
    shot?.versions.find((v) => v.version === shot.current_version);
  const spec = viewedVersion?.spec;
  const isPreviewingOld =
    previewVersion != null && previewVersion !== shot?.current_version;
  const frameUrl =
    (isPreviewingOld
      ? viewedVersion?.frame_url
      : (shot?.locked_frame_url ?? viewedVersion?.frame_url)) ?? null;

  const updateSpec = useCallback(
    (patch: Partial<ShotSpec>) => {
      if (!spec) return;
      onSpecChange({ ...spec, ...patch });
    },
    [spec, onSpecChange],
  );

  if (!shot) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center border border-graphite bg-film-base p-8 text-center text-sm text-silver">
        Select a shot to view the camera report
      </div>
    );
  }

  const isLocked =
    shot.status === "LOCKED" ||
    shot.status === "ANIMATIC_PENDING" ||
    shot.status === "ANIMATIC_READY" ||
    shot.status === "ASSEMBLED";

  const isGenerating =
    shot.status === "DRAFT" ||
    shot.status === "REFINING" ||
    shot.status === "ANIMATIC_PENDING";

  // Fields are frozen when locked, in read-only mode, or while previewing a
  // prior version (that version is immutable history — refine to branch).
  const fieldsDisabled = readOnly || isLocked || isPreviewingOld;

  return (
    <div className="border border-graphite bg-film-base">
      <div className="border-b border-graphite px-4 py-3">
        <h2 className="font-display text-lg uppercase text-light">
          Camera report — {shot.shot_id}
        </h2>
        <p className="font-mono text-xs text-silver">
          v{shot.current_version} · {shot.status.replace(/_/g, " ")}
        </p>
      </div>

      <div className="relative aspect-video bg-black">
        {shot.error && !frameUrl ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="max-w-md text-sm text-[color:var(--warning,#e0a030)]">
              Generation failed: {shot.error}
            </p>
            {!readOnly && onGenerate && (
              <Button
                variant="secondary"
                size="sm"
                onClick={onGenerate}
                disabled={generating}
              >
                {generating ? "Retrying…" : "Retry generation"}
              </Button>
            )}
          </div>
        ) : (isGenerating || generating) && !frameUrl ? (
          <LeaderCountdown
            label={
              shot.status === "ANIMATIC_PENDING"
                ? "Generating animatic"
                : "Generating frame"
            }
          />
        ) : frameUrl ? (
          <img
            src={frameUrl}
            alt={`Shot ${shot.shot_id} preview`}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-silver">
            No frame yet
            {!readOnly && onGenerate && (
              <Button variant="secondary" size="sm" onClick={onGenerate}>
                Generate frame
              </Button>
            )}
          </div>
        )}
      </div>

      {shot.versions.length > 1 && (
        <div className="flex items-center gap-1 overflow-x-auto border-b border-graphite p-3">
          {shot.versions.map((v) => (
            <button
              key={v.version}
              type="button"
              onClick={() => onVersionSelect(v.version)}
              className={cn(
                "shrink-0 rounded-sm border px-3 py-1 font-mono text-xs transition-colors",
                v.version === (viewedVersion?.version ?? shot.current_version)
                  ? "border-light bg-black text-light"
                  : "border-graphite text-silver hover:border-silver",
              )}
            >
              v{v.version}
            </button>
          ))}
          {isPreviewingOld && (
            <span className="ml-2 font-mono text-xs text-silver">
              viewing v{previewVersion} · refine from here to branch
            </span>
          )}
        </div>
      )}

      {spec && (
        <Tabs defaultValue="camera" className="p-4">
          <TabsList className="w-full flex-wrap h-auto gap-1">
            <TabsTrigger value="camera">Camera</TabsTrigger>
            <TabsTrigger value="lens">Lens</TabsTrigger>
            <TabsTrigger value="framing">Framing</TabsTrigger>
            <TabsTrigger value="lighting">Lighting</TabsTrigger>
            <TabsTrigger value="grade">Grade</TabsTrigger>
            <TabsTrigger value="subject">Subject</TabsTrigger>
            <TabsTrigger value="world">World</TabsTrigger>
            <TabsTrigger value="refs">continuity_refs</TabsTrigger>
          </TabsList>

          <TabsContent value="camera" className="space-y-3">
            <div>
              <Label htmlFor="intent">intent</Label>
              <Input
                id="intent"
                value={spec.intent}
                disabled={fieldsDisabled}
                onChange={(e) => updateSpec({ intent: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label>camera.angle</Label>
              <Select
                value={spec.camera.angle}
                disabled={fieldsDisabled}
                onValueChange={(v) =>
                  updateSpec({
                    camera: {
                      ...spec.camera,
                      angle: v as ShotSpec["camera"]["angle"],
                    },
                  })
                }
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CAMERA_ANGLES.map((a) => (
                    <SelectItem key={a} value={a}>
                      {a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="height_m">camera.height_m</Label>
              <Input
                id="height_m"
                type="number"
                step="0.1"
                min={0.1}
                max={50}
                value={spec.camera.height_m}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    camera: {
                      ...spec.camera,
                      height_m: parseFloat(e.target.value) || 1.5,
                    },
                  })
                }
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="movement">camera.movement</Label>
              <Input
                id="movement"
                value={spec.camera.movement}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    camera: { ...spec.camera, movement: e.target.value },
                  })
                }
                className="mt-1"
              />
            </div>
          </TabsContent>

          <TabsContent value="lens" className="space-y-3">
            <div>
              <Label htmlFor="focal_length_mm">lens.focal_length_mm</Label>
              <Input
                id="focal_length_mm"
                type="number"
                min={8}
                max={800}
                value={spec.lens.focal_length_mm}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    lens: {
                      ...spec.lens,
                      focal_length_mm: parseFloat(e.target.value) || 35,
                    },
                  })
                }
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="aperture_f">lens.aperture_f</Label>
              <Input
                id="aperture_f"
                type="number"
                step="0.1"
                min={0.95}
                max={32}
                value={spec.lens.aperture_f}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    lens: {
                      ...spec.lens,
                      aperture_f: parseFloat(e.target.value) || 2.8,
                    },
                  })
                }
                className="mt-1"
              />
            </div>
          </TabsContent>

          <TabsContent value="framing" className="space-y-3">
            <div>
              <Label>framing.shot_size</Label>
              <Select
                value={spec.framing.shot_size}
                disabled={fieldsDisabled}
                onValueChange={(v) =>
                  updateSpec({
                    framing: {
                      ...spec.framing,
                      shot_size: v as ShotSpec["framing"]["shot_size"],
                    },
                  })
                }
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SHOT_SIZES.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="composition">framing.composition</Label>
              <Input
                id="composition"
                value={spec.framing.composition}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    framing: {
                      ...spec.framing,
                      composition: e.target.value,
                    },
                  })
                }
                className="mt-1"
              />
            </div>
          </TabsContent>

          <TabsContent value="lighting" className="space-y-3">
            <div>
              <Label>lighting.key</Label>
              <Select
                value={spec.lighting.key}
                disabled={fieldsDisabled}
                onValueChange={(v) =>
                  updateSpec({
                    lighting: {
                      ...spec.lighting,
                      key: v as ShotSpec["lighting"]["key"],
                    },
                  })
                }
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LIGHTING_KEYS.map((k) => (
                    <SelectItem key={k} value={k}>
                      {k}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="mood">lighting.mood</Label>
              <Input
                id="mood"
                value={spec.lighting.mood}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    lighting: { ...spec.lighting, mood: e.target.value },
                  })
                }
                className="mt-1"
              />
            </div>
            <div>
              <Label>lighting.practicals</Label>
              <TagInput
                value={spec.lighting.practicals ?? []}
                onChange={(practicals) =>
                  updateSpec({
                    lighting: { ...spec.lighting, practicals },
                  })
                }
                placeholder="Add practical light source"
                disabled={fieldsDisabled}
              />
            </div>
          </TabsContent>

          <TabsContent value="grade" className="space-y-3">
            <div>
              <Label htmlFor="look">grade.look</Label>
              <Input
                id="look"
                value={spec.grade.look}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    grade: { ...spec.grade, look: e.target.value },
                  })
                }
                className="mt-1"
              />
            </div>
            <div>
              <Label>grade.contrast</Label>
              <Select
                value={spec.grade.contrast}
                disabled={fieldsDisabled}
                onValueChange={(v) =>
                  updateSpec({
                    grade: {
                      ...spec.grade,
                      contrast: v as ShotSpec["grade"]["contrast"],
                    },
                  })
                }
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {GRADE_CONTRASTS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </TabsContent>

          <TabsContent value="subject" className="space-y-3">
            <div>
              <Label htmlFor="primary">subject.primary</Label>
              <Input
                id="primary"
                value={spec.subject.primary}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    subject: { ...spec.subject, primary: e.target.value },
                  })
                }
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="blocking">subject.blocking</Label>
              <Input
                id="blocking"
                value={spec.subject.blocking}
                disabled={fieldsDisabled}
                onChange={(e) =>
                  updateSpec({
                    subject: { ...spec.subject, blocking: e.target.value },
                  })
                }
                className="mt-1"
              />
            </div>
          </TabsContent>

          <TabsContent value="world" className="space-y-3">
            <Label>world</Label>
            <TagInput
              value={spec.world ?? []}
              onChange={(world) => updateSpec({ world })}
              placeholder="Add environment element"
              disabled={fieldsDisabled}
            />
          </TabsContent>

          <TabsContent value="refs" className="space-y-3">
            <Label>continuity_refs</Label>
            <TagInput
              value={spec.continuity_refs ?? []}
              onChange={(continuity_refs) => updateSpec({ continuity_refs })}
              placeholder="e.g. s1_frame"
              disabled={fieldsDisabled}
            />
          </TabsContent>
        </Tabs>
      )}

      {!readOnly && !isLocked && (
        <div className="space-y-4 border-t border-graphite p-4">
          <RefineInput
            onRefine={onRefine}
            disabled={isGenerating}
            loading={refining}
          />
          <div className="flex flex-wrap gap-3">
            {spec && (
              <LockConfirm
                shotId={shot.shot_id}
                version={shot.current_version}
                onConfirm={() => onLock(shot.current_version)}
                disabled={!frameUrl || isGenerating}
                loading={locking}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
