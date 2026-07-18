import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { Shot } from "@/lib/api";
import { ShotCard } from "./ShotCard";
import { cn } from "@/lib/utils";

interface ShotStripProps {
  shots: Shot[];
  selectedShotId: string | null;
  focusedShotId: string | null;
  onSelect: (shotId: string) => void;
  onHover?: (shotId: string | null) => void;
  onReorder?: (shotIds: string[]) => void;
  matchCutShotId?: string | null;
  onMatchCutComplete?: (shotId: string) => void;
  editable?: boolean;
}

function SortableShotCard({
  shot,
  index,
  selected,
  focused,
  onClick,
  showMatchCut,
  onMatchCutComplete,
  editable,
}: {
  shot: Shot;
  index: number;
  selected: boolean;
  focused: boolean;
  onClick: () => void;
  showMatchCut: boolean;
  onMatchCutComplete?: () => void;
  editable: boolean;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: shot.shot_id, disabled: !editable });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn("touch-manipulation", isDragging && "z-10 opacity-80")}
      {...(editable ? { ...attributes, ...listeners } : {})}
    >
      <ShotCard
        shot={shot}
        index={index}
        selected={selected}
        focused={focused}
        onClick={onClick}
        showMatchCut={showMatchCut}
        onMatchCutComplete={onMatchCutComplete}
      />
    </div>
  );
}

export function ShotStrip({
  shots,
  selectedShotId,
  focusedShotId,
  onSelect,
  onHover,
  onReorder,
  matchCutShotId,
  onMatchCutComplete,
  editable = false,
}: ShotStripProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  const sorted = [...shots].sort((a, b) => a.order - b.order);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !onReorder) return;
    const ids = sorted.map((s) => s.shot_id);
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    const next = [...ids];
    const [moved] = next.splice(oldIndex, 1);
    next.splice(newIndex, 0, moved);
    onReorder(next);
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext
        items={sorted.map((s) => s.shot_id)}
        strategy={verticalListSortingStrategy}
      >
        <div
          className={cn(
            "flex gap-4",
            "max-md:flex-col md:overflow-x-auto md:pb-4",
            "md:flex-row",
          )}
          role="list"
          aria-label="Shot strip"
        >
          {sorted.map((shot, index) => (
            <div
              key={shot.shot_id}
              className="max-md:w-full md:min-w-[200px] md:max-w-[220px] md:flex-shrink-0"
              onMouseEnter={() => {
                onHover?.(shot.shot_id);
              }}
              onMouseLeave={() => onHover?.(null)}
            >
              <SortableShotCard
                shot={shot}
                index={index}
                selected={selectedShotId === shot.shot_id}
                focused={focusedShotId === shot.shot_id}
                onClick={() => onSelect(shot.shot_id)}
                showMatchCut={matchCutShotId === shot.shot_id}
                onMatchCutComplete={() =>
                  onMatchCutComplete?.(shot.shot_id)
                }
                editable={editable}
              />
            </div>
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
