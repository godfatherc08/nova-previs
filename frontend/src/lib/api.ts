import type { ShotSpec } from "./shotSpec";

/**
 * Provisional API contract — nova/api/routes.py is not built yet (backlog 1.4).
 * Shapes follow Nova_PRD.md §5/§11 and Nova_File_Structure.md.
 * Update this file when the backend contract lands.
 */

export type ShotStatus =
  | "DRAFT"
  | "REFINING"
  | "LOCKED"
  | "ANIMATIC_PENDING"
  | "ANIMATIC_READY"
  | "ASSEMBLED";

export interface ShotListItem {
  shot_id: string;
  order: number;
  description: string;
  shot_size?: string;
  intent?: string;
}

export interface ShotVersion {
  version: number;
  frame_url: string | null;
  spec: ShotSpec;
  created_at?: string;
}

export interface Shot {
  shot_id: string;
  order: number;
  status: ShotStatus;
  description: string;
  current_version: number;
  versions: ShotVersion[];
  locked_frame_url: string | null;
  animatic_clip_url: string | null;
  animatic_audio_url: string | null;
  manifest_url: string | null;
  error: string | null;
}

export interface Project {
  project_id: string;
  scene_text: string;
  shot_list: ShotListItem[];
  shots: Shot[];
  sequence_url: string | null;
  sequence_manifest_url: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary {
  project_id: string;
  scene_text: string;
  shot_count: number;
  created_at: string;
  updated_at: string;
}

export interface Take {
  take_id: string;
  frame_url: string;
}

export interface TakesResponse {
  takes: Take[];
  errors: string[];
}

export interface ProvenanceManifest {
  shot_id?: string;
  project_id?: string;
  model?: string;
  provider?: string;
  params?: Record<string, unknown>;
  seed?: number | string;
  sha256?: string;
  hash?: string;
  timestamp?: string;
  chain?: Array<{ stage: string; model: string; hash: string }>;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });

  if (!res.ok) {
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      body = await res.text();
    }
    const message =
      typeof body === "object" && body && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed (${res.status})`;
    throw new ApiError(message, res.status, body);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listProjects: () => request<ProjectSummary[]>("/projects"),

  createProject: (scene_text: string) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({ scene_text }),
    }),

  getProject: (projectId: string) =>
    request<Project>(`/projects/${projectId}`),

  updateShotList: (projectId: string, shot_list: ShotListItem[]) =>
    request<Project>(`/projects/${projectId}/shot-list`, {
      method: "PUT",
      body: JSON.stringify({ shot_list }),
    }),

  generateStoryboard: (projectId: string) =>
    request<Project>(`/projects/${projectId}/generate-storyboard`, {
      method: "POST",
    }),

  generateShot: (projectId: string, shotId: string) =>
    request<Shot>(`/projects/${projectId}/shots/${shotId}/generate`, {
      method: "POST",
    }),

  generateTakes: (projectId: string, shotId: string, count = 3) =>
    request<TakesResponse>(`/projects/${projectId}/shots/${shotId}/takes`, {
      method: "POST",
      body: JSON.stringify({ count }),
    }),

  promoteTake: (projectId: string, shotId: string, take_id: string) =>
    request<Shot>(`/projects/${projectId}/shots/${shotId}/takes/promote`, {
      method: "POST",
      body: JSON.stringify({ take_id }),
    }),

  refineShot: (projectId: string, shotId: string, instruction: string) =>
    request<Shot>(`/projects/${projectId}/shots/${shotId}/refine`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    }),

  updateShotSpec: (
    projectId: string,
    shotId: string,
    spec: ShotSpec,
  ) =>
    request<Shot>(`/projects/${projectId}/shots/${shotId}/spec`, {
      method: "PUT",
      body: JSON.stringify({ spec }),
    }),

  lockShot: (projectId: string, shotId: string, version?: number) =>
    request<Shot>(`/projects/${projectId}/shots/${shotId}/lock`, {
      method: "POST",
      body: JSON.stringify({ version }),
    }),

  assembleSequence: (projectId: string) =>
    request<Project>(`/projects/${projectId}/assemble`, {
      method: "POST",
    }),

  getManifest: (projectId: string, shotId?: string) =>
    request<ProvenanceManifest>(
      shotId
        ? `/projects/${projectId}/shots/${shotId}/manifest`
        : `/projects/${projectId}/manifest`,
    ),
};
