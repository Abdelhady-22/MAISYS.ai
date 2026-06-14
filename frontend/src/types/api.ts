// Mirrors services/drug-service/models/schemas.py.
// Keep in sync — any backend schema change should update this file
// in the same commit.

export type Language = "en" | "ar";
export type Severity = "minor" | "moderate" | "major" | "contraindicated";
export type VisualType =
  | "comparison_table"
  | "severity_bar"
  | "dosing_flowchart"
  | "pk_curve"
  | "card";

export interface BilingualText {
  en: string;
  ar: string;
}

export interface Citation {
  source: string;
  title?: string | null;
  url?: string | null;
  chunk_id?: string | null;
  snippet?: string | null;
}

export interface AgentMeta {
  agent_name: string;
  confidence: number;
  latency_ms: number;
  tokens_used: number;
  disclaimer: BilingualText;
}

// ── Lookup ──────────────────────────────────────────────────────

export interface LookupData {
  rxcui: string;
  generic_name: string;
  brand_names: string[];
  drug_class: string | null;
  indications: BilingualText[];
  mechanism_of_action: BilingualText | null;
  contraindications: BilingualText[];
}

// ── Interactions ────────────────────────────────────────────────

export interface InteractionPair {
  drug_a: string;
  drug_b: string;
  severity: Severity;
  description: BilingualText;
  source_tier: "ddimdl" | "drug_rag" | "web_search";
}

export interface InteractionsData {
  pairs: InteractionPair[];
  overall_severity: Severity | null;
}

// ── Dosage ──────────────────────────────────────────────────────

export interface DosageRegimen {
  population: "adult" | "pediatric" | "elderly" | "renal" | "hepatic";
  standard_dose: BilingualText;
  max_daily: BilingualText | null;
  notes: BilingualText | null;
}

export interface DosageData {
  regimens: DosageRegimen[];
  adjustments_applied: BilingualText[];
}

// ── Comparison ──────────────────────────────────────────────────

export interface ComparisonRow {
  drug_rxcui: string;
  drug_name: string;
  mechanism: BilingualText;
  efficacy_summary: BilingualText;
  common_side_effects: BilingualText[];
  cost_tier: "$" | "$$" | "$$$" | "$$$$";
  contraindications: BilingualText[];
  drug_class: string | null;
}

export interface ComparisonData {
  rows: ComparisonRow[];
}

// ── Pharmacokinetics ────────────────────────────────────────────

export interface PKData {
  absorption: {
    tmax_hours: number | null;
    bioavailability_percent: number | null;
    notes: BilingualText | null;
  };
  distribution: {
    vd_l_per_kg: number | null;
    protein_binding_percent: number | null;
  };
  metabolism: {
    primary_cyp_enzymes: string[];
    notes: BilingualText | null;
  };
  excretion: {
    half_life_hours: number | null;
    primary_route: "renal" | "hepatic" | "fecal" | "mixed" | null;
  };
}

// ── Free-text query ─────────────────────────────────────────────

export interface QueryRequest {
  text: string;
  language: Language;
  job_id?: string;
}

export interface QueryResponse {
  primary_agent: string;
  called_agents: string[];
  data: Record<string, unknown>;
  citations: Citation[];
  meta: AgentMeta;
  visual_type: VisualType;
}

// ── API envelope ────────────────────────────────────────────────

export interface APIResponse<T> {
  success: boolean;
  data: T;
  error?: { code: string; message: string };
}

// ── Progress events ─────────────────────────────────────────────

export interface ProgressEvent {
  status: "started" | "in_progress" | "completed" | "failed";
  message: string;
  job_id: string;
  percent: number | null;
  details: Record<string, unknown>;
}
