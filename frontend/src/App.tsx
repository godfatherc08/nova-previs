import { useCallback, useEffect, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { FilmGrain } from "@/components/shell/FilmGrain";
import { KeyLightCursor } from "@/components/shell/KeyLightCursor";
import { Letterbox, type LetterboxStage } from "@/components/shell/Letterbox";
import { ErrorBoundary } from "@/components/shell/ErrorBoundary";
import { Landing } from "@/routes/Landing";
import { NewScene } from "@/routes/NewScene";
import { Storyboard } from "@/routes/Storyboard";
import { Sequence } from "@/routes/Sequence";
import { Projects } from "@/routes/Projects";
import { usePointerFine } from "@/hooks/usePointerFine";

function stageForPath(pathname: string): LetterboxStage {
  if (pathname === "/" || pathname === "/new") return "academy";
  if (pathname.startsWith("/p/") && pathname.endsWith("/sequence"))
    return "scope";
  if (pathname.startsWith("/p/") || pathname === "/projects")
    return "widescreen";
  return "academy";
}

function AppShell() {
  const location = useLocation();
  const fine = usePointerFine();
  const containerRef = useRef<HTMLDivElement>(null);
  const [pointer, setPointer] = useState({ x: 0, y: 0 });
  const [containerWidth, setContainerWidth] = useState(0);
  const rafRef = useRef<number>(0);
  const pendingRef = useRef({ x: 0, y: 0 });

  const stage = stageForPath(location.pathname);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      setContainerWidth(entry.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      if (!fine) return;
      pendingRef.current = { x: e.clientX, y: e.clientY };
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        setPointer(pendingRef.current);
        rafRef.current = 0;
      });
    },
    [fine],
  );

  useEffect(() => {
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [onPointerMove]);

  return (
    <div ref={containerRef} className="relative min-h-screen">
      <FilmGrain />
      <KeyLightCursor pointer={pointer} />
      <Letterbox stage={stage}>
        <Routes>
          <Route
            path="/"
            element={
              <Landing
                pointerX={pointer.x}
                containerWidth={containerWidth}
              />
            }
          />
          <Route path="/new" element={<NewScene />} />
          <Route path="/p/:projectId" element={<Storyboard />} />
          <Route path="/p/:projectId/sequence" element={<Sequence />} />
          <Route path="/projects" element={<Projects />} />
        </Routes>
      </Letterbox>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </ErrorBoundary>
  );
}
