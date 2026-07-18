import { Link, useParams } from "react-router-dom";
import { useProject } from "@/hooks/useShots";
import { SequencePlayer } from "@/components/sequence/SequencePlayer";
import { ShareLink } from "@/components/sequence/ShareLink";
import { ProvenancePanel } from "@/components/sequence/ProvenancePanel";
import { LeaderCountdown } from "@/components/shots/LeaderCountdown";
import { Button } from "@/components/ui/button";

export function Sequence() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project, isLoading, error } = useProject(projectId);

  if (isLoading) {
    return <LeaderCountdown label="Loading sequence" className="flex-1" />;
  }

  if (error || !project) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4">
        <p className="text-silver">Sequence unavailable.</p>
        <Button asChild variant="secondary">
          <Link to="/new">Start over</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-8 py-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl uppercase text-light">
            Previs sequence
          </h1>
          <p className="mt-1 font-mono text-xs text-silver">
            {project.project_id}
          </p>
        </div>
        <div className="flex gap-2">
          <ProvenancePanel projectId={project.project_id} />
          <Button asChild variant="secondary">
            <Link to={`/p/${project.project_id}`}>Back to storyboard</Link>
          </Button>
        </div>
      </header>

      <SequencePlayer
        sequenceUrl={project.sequence_url}
        shots={project.shots}
      />

      <ShareLink url={project.sequence_url} />
    </div>
  );
}
