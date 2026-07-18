import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useCreateProject } from "@/hooks/useShots";
import { ApiError } from "@/lib/api";

export function NewScene() {
  const navigate = useNavigate();
  const [scene, setScene] = useState("");
  const create = useCreateProject();

  const handleSubmit = async () => {
    const trimmed = scene.trim();
    if (!trimmed) return;
    try {
      const project = await create.mutateAsync(trimmed);
      navigate(`/p/${project.project_id}`);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="flex flex-1 flex-col justify-center py-12">
      <div className="mx-auto w-full max-w-2xl">
        <p className="font-mono text-sm uppercase tracking-[0.3em] text-silver">
          FADE IN:
        </p>
        <Textarea
          className="mt-4 min-h-[280px] border-0 border-b border-graphite bg-transparent text-lg leading-relaxed focus-visible:ring-0 focus-visible:ring-offset-0"
          placeholder="A woman in a tattered coat walks through a destroyed city as drones circle overhead, then ducks into a ruined building."
          value={scene}
          onChange={(e) => setScene(e.target.value)}
          aria-label="Scene description"
        />
        <div className="mt-8 flex items-center justify-between">
          <p className="text-xs text-graphite">
            Describe your scene to begin
          </p>
          <Button
            onClick={handleSubmit}
            disabled={!scene.trim() || create.isPending}
            size="lg"
          >
            {create.isPending ? "Breaking down scene…" : "Generate shot list"}
          </Button>
        </div>
        {create.error && (
          <p className="mt-4 text-sm text-silver" role="alert">
            {create.error instanceof ApiError
              ? create.error.message
              : "Could not create project — the API may not be running yet."}
          </p>
        )}
      </div>
    </div>
  );
}
