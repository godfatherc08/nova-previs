import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Project, type Shot, type ShotListItem } from "@/lib/api";
import type { ShotSpec } from "@/lib/shotSpec";

const POLL_MS = 2500;

export function projectKey(projectId: string) {
  return ["project", projectId] as const;
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: projectKey(projectId ?? ""),
    queryFn: () => api.getProject(projectId!),
    enabled: !!projectId,
    refetchInterval: (query) => {
      const data = query.state.data as Project | undefined;
      if (!data) return false;
      const needsPoll = data.shots.some((s) =>
        ["REFINING", "ANIMATIC_PENDING", "DRAFT"].includes(s.status),
      );
      return needsPoll ? POLL_MS : false;
    },
  });
}

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scene_text: string) => api.createProject(scene_text),
    onSuccess: (project) => {
      qc.setQueryData(projectKey(project.project_id), project);
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useUpdateShotList(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shot_list: ShotListItem[]) =>
      api.updateShotList(projectId, shot_list),
    onSuccess: (project) => {
      qc.setQueryData(projectKey(projectId), project);
    },
  });
}

export function useGenerateStoryboard(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.generateStoryboard(projectId),
    onSuccess: (project) => {
      qc.setQueryData(projectKey(projectId), project);
    },
  });
}

export function useGenerateShot(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (shotId: string) => api.generateShot(projectId, shotId),
    onSuccess: (shot: Shot) => {
      qc.setQueryData<Project>(projectKey(projectId), (old) =>
        old
          ? {
              ...old,
              shots: old.shots.map((s) =>
                s.shot_id === shot.shot_id ? shot : s,
              ),
            }
          : old,
      );
    },
  });
}

export function useGenerateTakes(projectId: string) {
  return useMutation({
    mutationFn: ({ shotId, count }: { shotId: string; count?: number }) =>
      api.generateTakes(projectId, shotId, count),
  });
}

export function usePromoteTake(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shotId, takeId }: { shotId: string; takeId: string }) =>
      api.promoteTake(projectId, shotId, takeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKey(projectId) });
    },
  });
}

export function useRefineShot(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      shotId,
      instruction,
    }: {
      shotId: string;
      instruction: string;
    }) => api.refineShot(projectId, shotId, instruction),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKey(projectId) });
    },
  });
}

export function useUpdateShotSpec(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ shotId, spec }: { shotId: string; spec: ShotSpec }) =>
      api.updateShotSpec(projectId, shotId, spec),
    onSuccess: (shot: Shot) => {
      qc.setQueryData<Project>(projectKey(projectId), (old) => {
        if (!old) return old;
        return {
          ...old,
          shots: old.shots.map((s) =>
            s.shot_id === shot.shot_id ? shot : s,
          ),
        };
      });
    },
  });
}

export function useLockShot(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      shotId,
      version,
    }: {
      shotId: string;
      version?: number;
    }) => api.lockShot(projectId, shotId, version),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKey(projectId) });
    },
  });
}

export function useAssembleSequence(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.assembleSequence(projectId),
    onSuccess: (project) => {
      qc.setQueryData(projectKey(projectId), project);
    },
  });
}

export function useManifest(projectId: string, shotId?: string) {
  return useQuery({
    queryKey: ["manifest", projectId, shotId ?? "sequence"],
    queryFn: () => api.getManifest(projectId, shotId),
    enabled: !!projectId,
  });
}
