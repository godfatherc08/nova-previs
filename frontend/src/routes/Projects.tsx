import { Link } from "react-router-dom";
import { useProjects } from "@/hooks/useShots";
import { LeaderCountdown } from "@/components/shots/LeaderCountdown";
import { Button } from "@/components/ui/button";

export function Projects() {
  const { data, isLoading, error } = useProjects();

  return (
    <div className="flex flex-1 flex-col py-12">
      <div className="mb-8 flex items-center justify-between">
        <h1 className="font-display text-3xl uppercase text-light">Projects</h1>
        <Button asChild variant="secondary">
          <Link to="/new">New scene</Link>
        </Button>
      </div>

      {isLoading && <LeaderCountdown label="Loading projects" />}

      {error && (
        <p className="text-sm text-silver">
          Could not load projects — the API may not be available yet.
        </p>
      )}

      {data && data.length === 0 && (
        <p className="text-silver">No projects yet. Describe a scene to begin.</p>
      )}

      {data && data.length > 0 && (
        <ul className="space-y-3">
          {data.map((p) => (
            <li key={p.project_id}>
              <Link
                to={`/p/${p.project_id}`}
                className="block border border-graphite bg-film-base p-4 transition-colors hover:border-silver focus-visible:border-key"
              >
                <p className="font-mono text-xs text-silver">{p.project_id}</p>
                <p className="mt-1 line-clamp-2 text-sm text-light">
                  {p.scene_text}
                </p>
                <p className="mt-2 font-mono text-[10px] uppercase text-graphite">
                  {p.shot_count} shots · {new Date(p.updated_at).toLocaleDateString()}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
