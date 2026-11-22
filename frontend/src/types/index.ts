export type MatchStatus = "CONFIDENT_SHORTLIST" | "NO_CONFIDENT_MATCH";
export type SlotKind = "exact" | "confusable" | "unknown" | "mismatch" | "hard_mismatch" | "unobserved";

export interface Clip {
  id: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  camera_label: string;
  location: string | null;
  recorded_at: string | null;
  ingested_at: string;
  fps: number;
  width: number;
  height: number;
  duration_sec: number;
  frame_count: number;
  codec: string;
  processing: Record<string, number>;
}

export interface AuditEntry {
  id: number;
  vehicle_id: string | null;
  actor: string;
  action: string;
  field: string | null;
  ai_extracted: string | null;
  investigator_verified: string | null;
  note: string | null;
  created_at: string;
}

export interface CaseSummary {
  id: string;
  title: string;
  description: string;
  status: string;
  error: string | null;
  pipeline_version: string | null;
  created_at: string;
  updated_at: string;
  clip_count: number;
  vehicle_count: number;
  running: boolean;
}

export interface CaseDetail extends CaseSummary {
  runtime: Record<string, unknown>;
  clips: Clip[];
  entities: Entity[];
  audit: AuditEntry[];
}

export interface RegistryVehicle {
  id: number | null;
  plate: string;
  make: string;
  model: string;
  body_type: string;
  colour: string;
  year: number | null;
  owner_name: string | null;
  owner_city: string | null;
  status: string;
}

export interface SlotDiff {
  position: number;
  query: string;
  registry: string;
  kind: SlotKind;
  confidence: number;
  contribution: number;
}

export interface Candidate {
  rank: number;
  vehicle: RegistryVehicle;
  score: number;
  confidence: number;
  sub_scores: {
    plate: number;
    colour: number | null;
    body_type: number | null;
    make_model: number | null;
    coverage: number;
    plate_quality: number;
  };
  weights: Record<string, number>;
  slot_diff: SlotDiff[];
  alignment_offset: number;
  hard_mismatches: number;
  vetoed: boolean;
  contradictions: string[];
  reasons: string[];
}

export interface MatchResult {
  status: MatchStatus;
  regime: string;
  query_plate: string;
  known_chars: number;
  candidates: Candidate[];
  rejected_candidates: Candidate[];
  diagnostics: string[];
  registry_size: number;
  elapsed_ms: number;
}

export interface FusedSlot {
  position: number;
  char: string;
  confidence: number;
  candidates: { char: string; probability: number }[];
  support_frames: number;
  observed_frames: number;
}

export interface MatrixRow {
  frame_idx: number;
  timestamp_sec: number;
  raw_text: string;
  source: string;
  sharpness: number;
  cells: { char: string; confidence: number }[];
}

export interface FusedPlate {
  text: string;
  known_count: number;
  reads_used?: number;
  reads_rejected?: number;
  slots: FusedSlot[];
  matrix: MatrixRow[];
}

export interface VehicleAttributes {
  colours: { label: string; confidence: number }[];
  body_type: { label: string; confidence: number; source?: string };
  make_model: {
    status: string;
    predictions: { make: string; model: string; confidence: number }[];
    below_threshold: { make: string; model: string; confidence: number }[];
  };
  yolo_class?: string;
}

export interface VehicleSummary {
  id: string;
  clip_id: string;
  camera_label: string;
  entity_id: string | null;
  track_id: number;
  first_seen_sec: number;
  last_seen_sec: number;
  frames_tracked: number;
  best_crop: string | null;
  plate: string;
  known_chars: number;
  attributes: VehicleAttributes;
  status: MatchStatus | null;
  top_plate: string | null;
  top_confidence: number | null;
  overridden: boolean;
}

export interface Keyframe {
  frame_idx: number;
  timestamp_sec: number;
  sharpness: number;
  frame: string;
  crop: string;
  plate_raw?: string;
  plate_enhanced?: string;
  plate_text?: string;
  plate_sharpness?: number;
  ocr_source?: string;
}

export interface EvidenceSlot {
  char: string;
  confidence: number;
  locked: boolean;
}

export interface VehicleDetail extends VehicleSummary {
  keyframes: Keyframe[];
  fused_plate: FusedPlate;
  active_evidence: { plate: { slots: EvidenceSlot[] }; colours: { label: string }[]; body_type: string | null };
  match_result: MatchResult;
  overrides: { slots?: Record<string, string>; colour?: string; body_type?: string };
  clip: Clip;
  entity: Entity | null;
}

export interface EntityLink {
  a: string;
  b: string;
  score: number;
  visual: number;
  plate: number | null;
  attributes: number | null;
  temporal_factor: number;
  temporal_note: string;
  weights: Record<string, number>;
}

export interface TimelineEntry {
  vehicle_id: string;
  clip_id: string;
  camera_label: string;
  location: string | null;
  first_seen_sec: number;
  last_seen_sec: number;
  absolute_time: string | null;
  plate: string;
  best_crop: string | null;
}

export interface Entity {
  id: string;
  fused_plate: FusedPlate;
  timeline: TimelineEntry[];
  links: EntityLink[];
  match_result: MatchResult;
}

export interface Health {
  status: string;
  pipeline_version: string;
  registry_count: number;
  models: { device: string; plate_ocr: { engine: string | null }; clip: { loaded: boolean }; detector: { loaded: boolean } };
}

export interface ProgressEvent {
  stage: string;
  percent: number;
  message: string;
  status: string;
}

export interface OverridePayload {
  slots?: { position: number; char: string }[];
  colour?: string;
  body_type?: string;
  note?: string;
  reset?: boolean;
}

export interface MatchTestPayload {
  plate: string;
  plate_confidence: number;
  colour?: string;
  body_type?: string;
  body_confidence: number;
  make?: string;
  model?: string;
}

export const COLOURS = ["white", "silver", "grey", "black", "red", "maroon", "blue", "green", "yellow", "orange", "brown", "beige"];
export const BODY_TYPES = ["sedan", "hatchback", "suv", "two-wheeler", "auto-rickshaw", "pickup_truck", "heavy_truck", "bus", "van"];
