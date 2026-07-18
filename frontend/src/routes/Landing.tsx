import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { MuybridgeHero } from "@/components/hero/MuybridgeHero";

interface LandingProps {
  pointerX: number;
  containerWidth: number;
}

export function Landing({ pointerX, containerWidth }: LandingProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-12 py-16">
      <div className="text-center">
        <h1 className="font-display text-4xl uppercase leading-tight text-light md:text-6xl">
          Nova
        </h1>
        <p className="mt-4 max-w-xl text-balance text-sm text-silver md:text-base">
          Twelve photographs proved a horse could fly. Nova does it for your
          scene.
        </p>
      </div>

      <MuybridgeHero pointerX={pointerX} containerWidth={containerWidth} />

      <div className="flex flex-col items-center gap-4 sm:flex-row">
        <Button asChild size="lg">
          <Link to="/new">Begin a scene</Link>
        </Button>
        <Button asChild variant="ghost" size="lg">
          <Link to="/projects">Past projects</Link>
        </Button>
      </div>
    </div>
  );
}
