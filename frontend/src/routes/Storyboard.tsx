import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  useAssembleSequence,
  useGenerateShot,
  useGenerateStoryboard,
  useGenerateTakes,
  useLockShot,
  useProject,
  usePromoteTake,
  useRefineShot,
  useUpdateShotList,
  useUpdateShotSpec,
} from "@/hooks/useShots";
import type { Take } from "@/lib/api";
import { ShotStrip } from "@/components/shots/ShotStrip";
import { ShotDetailPanel } from "@/components/shots/ShotDetailPanel";
import { TakePicker } from "@/components/shots/TakePicker";
import { LeaderCountdown } from "@/components/shots/LeaderCountdown";
import { ProvenancePanel } from "@/components/sequence/ProvenancePanel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ShotListItem } from "@/lib/api";
import { useReducedMotion } from "@/hooks/useReducedMotion";
import { DURATION_DOLLY, EASE_CINEMA } from "@/lib/motion";
import { cn } from "@/lib/utils";

type Phase = "shot-list" | "storyboard";

function SortableShotRow({
  item,
  index,
  onRemove,
  onChange,
}: {
  item: ShotListItem;
  index: number;
  onRemove: (shotId: string) => void;
  onChange: (shotId: string, patch: Partial<ShotListItem>) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: item.shot_id });

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.5 : 1,
      }}
      className="film-strip-edge relative border border-graphite bg-film-base p-4 pl-6"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label={`Reorder shot ${index + 1}`}
            className="cursor-grab touch-none px-1 text-silver hover:text-light active:cursor-grabbing"
            {...attributes}
            {...listeners}
          >
            ⠿
          </button>
          <span className="font-mono text-xs text-silver">
            {String(index + 1).padStart(2, "0")}
          </span>
        </div>
        <Button variant="ghost" size="sm" onClick={() => onRemove(item.shot_id)}>
          Remove
        </Button>
      </div>
      <Textarea
        value={item.description}
        onChange={(e) =>
          onChange(item.shot_id, {
            description: e.target.value,
            intent: e.target.value,
          })
        }
        className="min-h-[80px] font-sans"
      />
      <Input
        className="mt-2"
        placeholder="shot_size tag"
        value={item.shot_size ?? ""}
        onChange={(e) => onChange(item.shot_id, { shot_size: e.target.value })}
      />
    </div>
  );
}

export function Storyboard() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project, isLoading, error } = useProject(projectId);
  const updateShotList = useUpdateShotList(projectId ?? "");
  const generateStoryboard = useGenerateStoryboard(projectId ?? "");
  const refineShot = useRefineShot(projectId ?? "");
  const updateSpec = useUpdateShotSpec(projectId ?? "");
  const lockShot = useLockShot(projectId ?? "");
  const assemble = useAssembleSequence(projectId ?? "");
  const generateShot = useGenerateShot(projectId ?? "");
  const generateTakes = useGenerateTakes(projectId ?? "");
  const promoteTake = usePromoteTake(projectId ?? "");
  // Shots we've already kicked a generation for, so the auto-generate effect
  // fires exactly once per DRAFT shot (a spec-only DRAFT has no frame until
  // the image stage runs — backlog 3.1/3.5).
  const generateRequested = useRef<Set<string>>(new Set());
  const [takes, setTakes] = useState<Take[] | null>(null);
  const [takeErrors, setTakeErrors] = useState<string[]>([]);

  const reduced = useReducedMotion();
  const [phase, setPhase] = useState<Phase>("shot-list");
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [focusedShotId, setFocusedShotId] = useState<string | null>(null);
  const [matchCutShotId, setMatchCutShotId] = useState<string | null>(null);
  const [dollyActive, setDollyActive] = useState(false);
  const prevStatuses = useRef<Record<string, string>>({});

  const [localShotList, setLocalShotList] = useState<ShotListItem[]>([]);

  useEffect(() => {
    if (project?.shot_list) {
      setLocalShotList(project.shot_list);
    }
    if (project?.shots && project.shots.length > 0) {
      setPhase("storyboard");
      if (!selectedShotId) {
        setSelectedShotId(project.shots[0]?.shot_id ?? null);
      }
    }
  }, [project, selectedShotId]);

  useEffect(() => {
    if (!project?.shots) return;
    for (const shot of project.shots) {
      const prev = prevStatuses.current[shot.shot_id];
      if (
        prev === "ANIMATIC_PENDING" &&
        shot.status === "ANIMATIC_READY"
      ) {
        setMatchCutShotId(shot.shot_id);
      }
      prevStatuses.current[shot.shot_id] = shot.status;
    }
  }, [project?.shots]);

  // Auto-generate a frame for any DRAFT shot that has a spec but no frame
  // yet and hasn't errored — turns the "Generating frame" state truthful and
  // walks each shot DRAFT -> REFINING without a manual click. A shot with an
  // error is left alone for the user to retry explicitly (backlog 9.3).
  useEffect(() => {
    if (!project?.shots) return;
    for (const shot of project.shots) {
      const current = shot.versions.find(
        (v) => v.version === shot.current_version,
      );
      const needsFrame =
        shot.status === "DRAFT" &&
        !shot.error &&
        current != null &&
        current.frame_url == null;
      if (needsFrame && !generateRequested.current.has(shot.shot_id)) {
        generateRequested.current.add(shot.shot_id);
        generateShot.mutate(shot.shot_id, {
          onError: () => generateRequested.current.delete(shot.shot_id),
        });
      }
    }
  }, [project?.shots, generateShot]);

  useEffect(() => {
    if (phase === "storyboard") {
      setDollyActive(true);
      const t = setTimeout(
        () => setDollyActive(false),
        reduced ? 0 : DURATION_DOLLY,
      );
      return () => clearTimeout(t);
    }
  }, [phase, reduced]);

  const addShot = () => {
    const id = `s${localShotList.length + 1}`;
    const next: ShotListItem = {
      shot_id: id,
      order: localShotList.length,
      description: "New shot",
      intent: "",
      shot_size: "medium",
    };
    const updated = [...localShotList, next];
    setLocalShotList(updated);
    updateShotList.mutate(updated);
  };

  const removeShot = (shotId: string) => {
    const updated = localShotList
      .filter((s) => s.shot_id !== shotId)
      .map((s, i) => ({ ...s, order: i }));
    setLocalShotList(updated);
    updateShotList.mutate(updated);
  };

  const updateShotListItem = (
    shotId: string,
    patch: Partial<ShotListItem>,
  ) => {
    const updated = localShotList.map((s) =>
      s.shot_id === shotId ? { ...s, ...patch } : s,
    );
    setLocalShotList(updated);
  };

  const saveShotList = () => {
    updateShotList.mutate(localShotList);
  };

  const dndSensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = localShotList.findIndex((s) => s.shot_id === active.id);
    const newIndex = localShotList.findIndex((s) => s.shot_id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;
    const reordered = arrayMove(localShotList, oldIndex, newIndex).map(
      (s, i) => ({ ...s, order: i }),
    );
    setLocalShotList(reordered);
    updateShotList.mutate(reordered);
  };

  const selectedShot =
    project?.shots.find((s) => s.shot_id === selectedShotId) ?? null;

  const allAnimaticReady =
    project?.shots &&
    project.shots.length > 0 &&
    project.shots.every((s) => s.status === "ANIMATIC_READY");

  if (isLoading) {
    return <LeaderCountdown label="Loading project" className="flex-1" />;
  }

  if (error || !project) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
        <p className="text-silver">
          Project not found or API unavailable.
        </p>
        <Button asChild variant="secondary">
          <Link to="/new">Start a new scene</Link>
        </Button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex flex-1 flex-col gap-8 py-8 transition-transform",
        dollyActive && !reduced && "scale-[1.03]",
      )}
      style={{
        transition: reduced
          ? undefined
          : `transform ${DURATION_DOLLY}ms ${EASE_CINEMA}`,
      }}
    >
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs text-silver">{project.project_id}</p>
          <p className="mt-1 line-clamp-2 max-w-xl text-sm text-light">
            {project.scene_text}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ProvenancePanel projectId={project.project_id} />
          {allAnimaticReady && (
            <>
              <Button
                variant="secondary"
                onClick={() => assemble.mutate()}
                disabled={assemble.isPending}
              >
                {assemble.isPending ? "Assembling…" : "Assemble sequence"}
              </Button>
              <Button asChild>
                <Link to={`/p/${project.project_id}/sequence`}>
                  View sequence
                </Link>
              </Button>
            </>
          )}
        </div>
      </header>

      {phase === "shot-list" && (
        <section className="space-y-6">
          <div>
            <h2 className="font-display text-2xl uppercase text-light">
              Shot list
            </h2>
            <p className="mt-1 text-sm text-silver">
              Agent-proposed coverage — reorder, edit, then generate storyboard.
            </p>
          </div>

          <DndContext
            sensors={dndSensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={localShotList.map((s) => s.shot_id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-4">
                {localShotList.map((item, index) => (
                  <SortableShotRow
                    key={item.shot_id}
                    item={item}
                    index={index}
                    onRemove={removeShot}
                    onChange={updateShotListItem}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>

          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={addShot}>
              Add shot
            </Button>
            <Button variant="outline" onClick={saveShotList}>
              Save shot list
            </Button>
            <Button
              onClick={() => {
                saveShotList();
                generateStoryboard.mutate(undefined, {
                  onSuccess: () => setPhase("storyboard"),
                });
              }}
              disabled={generateStoryboard.isPending || localShotList.length === 0}
            >
              {generateStoryboard.isPending
                ? "Generating storyboard…"
                : "Generate storyboard"}
            </Button>
          </div>
        </section>
      )}

      {phase === "storyboard" && project.shots.length > 0 && (
        <section className="space-y-6">
          <div>
            <h2 className="font-display text-2xl uppercase text-light">
              Storyboard
            </h2>
            <p className="mt-1 text-sm text-silver">
              Rack focus across the strip. Refine, lock, watch stills become
              motion.
            </p>
          </div>

          <ShotStrip
            shots={project.shots}
            selectedShotId={selectedShotId}
            focusedShotId={focusedShotId ?? selectedShotId}
            onSelect={(id) => {
              setSelectedShotId(id);
              setFocusedShotId(id);
              setPreviewVersion(null);
              setTakes(null);
              setTakeErrors([]);
            }}
            onHover={(id) => setFocusedShotId(id ?? selectedShotId)}
            matchCutShotId={matchCutShotId}
            onMatchCutComplete={(id) => {
              if (matchCutShotId === id) setMatchCutShotId(null);
            }}
          />

          <ShotDetailPanel
            shot={selectedShot}
            previewVersion={previewVersion}
            onSpecChange={(spec) => {
              if (!selectedShot) return;
              updateSpec.mutate({ shotId: selectedShot.shot_id, spec });
            }}
            onRefine={(instruction) => {
              if (!selectedShot) return;
              setPreviewVersion(null);
              refineShot.mutate({
                shotId: selectedShot.shot_id,
                instruction,
              });
            }}
            onLock={(version) => {
              if (!selectedShot) return;
              lockShot.mutate({
                shotId: selectedShot.shot_id,
                version,
              });
            }}
            onGenerate={() => {
              if (!selectedShot) return;
              generateRequested.current.add(selectedShot.shot_id);
              generateShot.mutate(selectedShot.shot_id);
            }}
            onVersionSelect={(version) =>
              setPreviewVersion((v) => (v === version ? null : version))
            }
            refining={refineShot.isPending}
            locking={lockShot.isPending}
            generating={
              generateShot.isPending &&
              generateShot.variables === selectedShot?.shot_id
            }
          />

          {selectedShot &&
            ["DRAFT", "REFINING"].includes(selectedShot.status) && (
              <TakePicker
                disabled={!selectedShot}
                generating={generateTakes.isPending}
                promoting={promoteTake.isPending}
                takes={takes}
                errors={takeErrors}
                onGenerate={(count) => {
                  setTakes(null);
                  setTakeErrors([]);
                  generateTakes.mutate(
                    { shotId: selectedShot.shot_id, count },
                    {
                      onSuccess: (res) => {
                        setTakes(res.takes);
                        setTakeErrors(res.errors);
                      },
                    },
                  );
                }}
                onPromote={(takeId) => {
                  promoteTake.mutate(
                    { shotId: selectedShot.shot_id, takeId },
                    {
                      onSuccess: () => {
                        setTakes(null);
                        setTakeErrors([]);
                      },
                    },
                  );
                }}
              />
            )}

          {selectedShot && (
            <ProvenancePanel
              projectId={project.project_id}
              shotId={selectedShot.shot_id}
              triggerLabel="Shot provenance"
            />
          )}
        </section>
      )}

      {phase === "storyboard" && project.shots.length === 0 && (
        <LeaderCountdown label="Generating storyboard" />
      )}
    </div>
  );
}
