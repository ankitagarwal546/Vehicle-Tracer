export type MatchStatus = "CONFIDENT_SHORTLIST" | "NO_CONFIDENT_MATCH";
export type Outcome = "PLATE_CANDIDATE" | "AMBIGUOUS" | "NO_REGISTRY_MATCH" | "INSUFFICIENT_PLATE" | "UNREADABLE_PLATE";
export type ReviewStatus = "proposed" | "confirmed" | "rejected";
export type PlateScript = "latin" | "non_latin";
export type PlateFormat = "latin_any" | "india_rto" | "uk" | "non_latin_digits";
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
  plate_script: PlateScript;
  plate_format: PlateFormat;
  timezone: string | null;
  latitude: number | null;
  longitude: number | null;
  synthetic: boolean;
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
  stale: boolean;
}

export interface CaseCounts {
  tracks: number;
  plate_candidates: number;
  ambiguous: number;
  no_registry_match: number;
  insufficient_plate: number;
  unreadable_plate: number;
  possible_links: number;
  confirmed_links: number;
  rejected_links: number;
  fragments_merged: number;
  clips_missing_time: number;
}

export interface CaseDetail extends CaseSummary {
  runtime: Record<string, unknown>;
  summary: CaseCounts;
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
  source: string;
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
  exact_chars: number;
  confusable_chars: number;
  hard_mismatches: number;
  plate_supported: boolean;
  blocking_reasons: string[];
  vetoed: boolean;
  contradictions: string[];
  reasons: string[];
}

export interface MatchResult {
  status: MatchStatus;
  outcome: Outcome;
  reason_codes: string[];
  regime: string;
  query_plate: string;
  known_chars: number;
  candidates: Candidate[];
  rejected_candidates: Candidate[];
  attribute_suggestions: { similar_count: number; vehicles: RegistryVehicle[]; basis: string[] };
  diagnostics: string[];
  thresholds: Record<string, number>;
  score_is_calibrated: boolean;
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
  source_supported_frames?: number;
  unknown_reason?: string | null;
  evidence?: SlotVote[];
}

export interface SlotVote {
  frame_idx: number;
  timestamp_sec: number;
  char: string;
  confidence: number;
  source: string;
  source_supported?: boolean;
  ocr_engine?: string;
  crop?: string | null;
  crop_sha256?: string | null;
  alternatives?: { char: string; probability: number }[];
  variants?: { variant: string; char: string; confidence: number }[];
}

export interface MatrixRow {
  frame_idx: number;
  timestamp_sec: number;
  raw_text: string;
  source: string;
  derived?: boolean;
  sharpness: number;
  cells: { char: string; confidence: number }[];
}

export interface FusedPlate {
  text: string;
  known_count: number;
  reads_used?: number;
  reads_rejected?: number;
  rejected_reads?: { frame_idx: number; timestamp_sec: number; raw_text: string; reason: string }[];
  stack_crop?: string | null;
  slots: FusedSlot[];
  matrix: MatrixRow[];
}

export interface VehicleAttributes {
  colours: { label: string; confidence: number }[];
  body_type: { label: string; confidence: number; source?: string; distribution?: { label: string; confidence: number }[] };
  make_model: {
    status: string;
    predictions: { make: string; model: string; confidence: number }[];
    below_threshold: { make: string; model: string; confidence: number }[];
  };
  yolo_class?: string;
  partial_view?: boolean;
  merged_track_ids?: number[];
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
  outcome: Outcome | null;
  reason_codes: string[];
  diagnostics: string[];
  top_plate: string | null;
  top_score: number | null;
  closest_plate: string | null;
  overridden: boolean;
  link_status: ReviewStatus | null;
  plate_script: PlateScript;
  plate_format: PlateFormat;
  readability: "none" | "partial" | "comparable";
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
  plate_quality?: number;
  frame_sharpness?: number;
  brightness?: number;
  contrast?: number;
  low_sharpness?: boolean;
  plate_box_confidence?: number;
  plate_crop_size?: [number, number];
  crop_sha256?: string;
  ocr_engine?: string;
  rectification?: { status: string; reason: string };
  variants?: { name: string; label: string; kind: string; image: string; text: string; mean_confidence: number }[];
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
  plate_compared: number;
  plate_exact: number;
  plate_contradictions: number;
  attributes: number | null;
  temporal_status: "plausible" | "weak" | "implausible" | "unavailable";
  temporal_factor: number;
  temporal_note: string;
  location_context: string;
  evidence_tier: string;
  evidence_reason: string;
  weights: Record<string, number>;
}

export interface TimelineEntry {
  vehicle_id: string;
  clip_id: string;
  camera_label: string;
  location: string | null;
  timezone?: string | null;
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
  review_status: ReviewStatus;
  evidence_tier: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
}

export interface Health {
  status: string;
  pipeline_version: string;
  registry_count: number;
  synthetic_count: number;
  models: {
    device: string;
    plate_ocr: { engine: string | null };
    clip: { loaded: boolean };
    detector: { loaded: boolean };
    assets: { ready: boolean; missing: string[]; install_command: string; attributes_reid: { installed: boolean } };
  };
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
  plate_format?: PlateFormat;
  colour?: string;
  body_type?: string;
  body_confidence: number;
  make?: string;
  model?: string;
}

export const PLATE_FORMATS: { value: PlateFormat; label: string }[] = [
  { value: "latin_any", label: "Latin A–Z, 0–9" },
  { value: "india_rto", label: "India RTO / BH" },
  { value: "uk", label: "UK" },
  { value: "non_latin_digits", label: "Non-Latin, digits only" },
];

export const COLOURS = ["white", "silver", "grey", "black", "red", "maroon", "blue", "green", "yellow", "orange", "brown", "beige"];
export const BODY_TYPES = ["sedan", "hatchback", "suv", "two-wheeler", "auto-rickshaw", "pickup_truck", "heavy_truck", "bus", "van"];
