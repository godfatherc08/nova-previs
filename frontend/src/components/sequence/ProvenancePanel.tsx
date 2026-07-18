import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { useManifest } from "@/hooks/useShots";
import { LeaderCountdown } from "@/components/shots/LeaderCountdown";

interface ProvenancePanelProps {
  projectId: string;
  shotId?: string;
  triggerLabel?: string;
}

export function ProvenancePanel({
  projectId,
  shotId,
  triggerLabel = "View provenance",
}: ProvenancePanelProps) {
  const { data, isLoading, error } = useManifest(projectId, shotId);

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button variant="ghost" size="sm">
          {triggerLabel}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="overflow-y-auto">
        <SheetHeader>
          <SheetTitle>Film can label</SheetTitle>
          <SheetDescription>
            SHA-256 provenance manifest — the digital edge code
          </SheetDescription>
        </SheetHeader>

        {isLoading && <LeaderCountdown label="Loading manifest" />}

        {error && (
          <p className="mt-4 text-sm text-silver">
            Manifest unavailable — the backend may not expose this endpoint yet.
          </p>
        )}

        {data && (
          <div className="mt-6 space-y-4 border border-graphite bg-black p-4 font-mono text-xs">
            {data.sha256 && (
              <div>
                <p className="text-silver">SHA-256</p>
                <p className="break-all text-light">{data.sha256}</p>
              </div>
            )}
            {data.hash && (
              <div>
                <p className="text-silver">hash</p>
                <p className="break-all text-light">{data.hash}</p>
              </div>
            )}
            {data.model && (
              <div>
                <p className="text-silver">model</p>
                <p className="text-light">{data.model}</p>
              </div>
            )}
            {data.provider && (
              <div>
                <p className="text-silver">provider</p>
                <p className="text-light">{data.provider}</p>
              </div>
            )}
            {data.timestamp && (
              <div>
                <p className="text-silver">timestamp</p>
                <p className="text-light">{data.timestamp}</p>
              </div>
            )}
            {data.chain && data.chain.length > 0 && (
              <div>
                <p className="mb-2 text-silver">chain</p>
                {data.chain.map((entry, i) => (
                  <div key={i} className="mb-2 border-l border-graphite pl-3">
                    <p className="text-light">{entry.stage}</p>
                    <p className="text-silver">{entry.model}</p>
                    <p className="break-all text-graphite">{entry.hash}</p>
                  </div>
                ))}
              </div>
            )}
            <pre className="overflow-x-auto whitespace-pre-wrap text-graphite">
              {JSON.stringify(data, null, 2)}
            </pre>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
