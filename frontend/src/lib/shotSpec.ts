/**
 * TypeScript mirror of schema/shot_spec.schema.json — keep in lockstep.
 * Do not rename or add fields here without updating the schema.
 */

export const CAMERA_ANGLES = [
  "eye-level",
  "low",
  "high",
  "overhead",
  "dutch",
  "worms-eye",
  "over-the-shoulder",
] as const;

export const SHOT_SIZES = [
  "extreme wide",
  "wide",
  "full",
  "medium wide",
  "medium",
  "medium close-up",
  "close-up",
  "extreme close-up",
  "insert",
] as const;

export const LIGHTING_KEYS = [
  "high-key",
  "low-key",
  "flat",
  "natural",
  "chiaroscuro",
] as const;

export const GRADE_CONTRASTS = ["low", "medium", "high"] as const;

export type CameraAngle = (typeof CAMERA_ANGLES)[number];
export type ShotSize = (typeof SHOT_SIZES)[number];
export type LightingKey = (typeof LIGHTING_KEYS)[number];
export type GradeContrast = (typeof GRADE_CONTRASTS)[number];

export interface Camera {
  angle: CameraAngle;
  height_m: number;
  movement: string;
}

export interface Lens {
  focal_length_mm: number;
  aperture_f: number;
}

export interface Framing {
  shot_size: ShotSize;
  composition: string;
}

export interface Lighting {
  key: LightingKey;
  mood: string;
  practicals?: string[];
}

export interface Grade {
  look: string;
  contrast: GradeContrast;
}

export interface Subject {
  primary: string;
  blocking: string;
}

export interface ShotSpec {
  shot_id: string;
  version?: number;
  intent: string;
  camera: Camera;
  lens: Lens;
  framing: Framing;
  lighting: Lighting;
  grade: Grade;
  subject: Subject;
  world?: string[];
  continuity_refs?: string[];
}

export function emptyShotSpec(shotId: string, intent = ""): ShotSpec {
  return {
    shot_id: shotId,
    version: 1,
    intent,
    camera: { angle: "eye-level", height_m: 1.5, movement: "static" },
    lens: { focal_length_mm: 35, aperture_f: 2.8 },
    framing: { shot_size: "medium", composition: "centered subject" },
    lighting: { key: "natural", mood: "neutral daylight", practicals: [] },
    grade: { look: "neutral", contrast: "medium" },
    subject: { primary: "", blocking: "" },
    world: [],
    continuity_refs: [],
  };
}
