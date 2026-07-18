import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ShareLinkProps {
  url: string | null;
  className?: string;
}

export function ShareLink({ url, className }: ShareLinkProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard may be unavailable */
    }
  };

  if (!url) {
    return (
      <div
        className={cn(
          "border border-graphite bg-film-base p-8 text-center text-sm text-silver",
          className,
        )}
      >
        Share link will appear once the sequence is assembled
      </div>
    );
  }

  return (
    <div
      className={cn(
        "border border-graphite bg-black p-8 text-center vignette",
        className,
      )}
    >
      <p className="mb-2 font-display text-2xl uppercase tracking-widest text-light">
        Now screening
      </p>
      <p className="mb-6 font-mono text-xs uppercase tracking-[0.4em] text-silver">
        Durable previs link
      </p>
      <p className="mb-6 break-all font-mono text-sm text-light">{url}</p>
      <Button onClick={copy} variant="secondary">
        {copied ? "Copied" : "Copy link"}
      </Button>
    </div>
  );
}
