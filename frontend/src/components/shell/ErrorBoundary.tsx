import { Component, type ReactNode } from "react";

/**
 * Backlog 9.3: last-resort error boundary. Per-request failures are handled
 * inline (TanStack Query error states, the shot error card), so this only
 * catches unexpected *render* crashes — it keeps a thrown component from
 * blanking the whole SPA and gives the user a way back.
 */
interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    // Surfaced for the demo/debug console; no telemetry backend for MVP.
    console.error("Nova render error:", error);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-black p-8 text-center">
          <h1 className="font-display text-2xl uppercase text-light">
            Something broke on set
          </h1>
          <p className="max-w-md text-sm text-silver">
            An unexpected error interrupted the shot. Your work is saved — the
            frame, spec, and any locked artifacts are persisted in B2.
          </p>
          <a
            href="/"
            className="rounded-sm border border-graphite px-4 py-2 font-mono text-sm text-light hover:border-silver"
          >
            Back to start
          </a>
        </div>
      );
    }
    return this.props.children;
  }
}
