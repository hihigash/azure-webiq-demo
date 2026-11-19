export type ColumnId = 'A' | 'B' | 'C';
export type RunMode = 'lite' | 'advanced';
export type RunStatus = 'idle' | 'running' | 'completed' | 'error';

export interface Preset {
  id: string;
  label: string;
  question: string;
  mode: RunMode;
  useScope: boolean;
  responseFilter: string[];
}

export interface Classification {
  name: string;
  domains: string[];
}

export interface Pack {
  id: string;
  title: string;
  description: string;
  scopeName: string | null;
  allowedDomains: string[];
  presets: Preset[];
  classifications: Classification[];
}

export interface Pricing {
  version: string;
  currency: string;
}

export interface Config {
  pack: Pack;
  pricing: Pricing;
  demoMode: boolean;
  limits: { columns: number; allowedDomains: number; questionMaxLength: number };
}

export interface Citation {
  id: string;
  title: string;
  url: string;
  source: string;
  excerpt: string;
  publishedAt: string;
  dateKind: string;
  evidenceIds: string[];
  classification: string;
}

export interface Evidence {
  id: string;
  title: string;
  url: string;
  source: string;
  text: string;
  citationIds: string[];
  kind: string;
  structured: Record<string, unknown>;
}

export interface Metrics {
  elapsedMs: number | null;
  inputTokens: number | null;
  reasoningTokens: number | null;
  outputTokens: number | null;
  searchRequests: number | null;
  searchRequestUnit: string;
  estimatedCost: number | null;
  costCurrency: string | null;
  unavailableFields: string[];
}

export interface ColumnResult {
  columnId: ColumnId;
  label: string;
  status: 'success' | 'error';
  answer: string;
  citations: Citation[];
  evidence: Evidence[];
  metrics: Metrics;
  settings: Record<string, unknown>;
  scopeApplied?: boolean | null;
  error?: { code?: string; message: string } | null;
}

export interface RunEvent {
  event: 'progress' | 'result' | 'error' | 'done';
  columnId: ColumnId;
  elapsedMs: number;
  sequence: number;
  message?: string | null;
  result?: ColumnResult;
}

export interface ProgressItem {
  sequence: number;
  elapsedMs: number;
  message: string;
}

export interface ColumnState {
  id: ColumnId;
  name: string;
  status: RunStatus;
  progress: ProgressItem[];
  result: ColumnResult | null;
  error: string | null;
}

export interface RunState {
  columns: Record<ColumnId, ColumnState>;
  running: boolean;
  startedAt: string | null;
  completedAt: string | null;
}

export interface RunRequest {
  question: string;
  presetId?: string;
  scopeName?: string;
  mode: RunMode;
  responseFilter: string[];
}

export interface RunSnapshot {
  runId: string;
  question: string;
  columns: ColumnResult[];
  settings: Record<string, unknown>;
  pricingVersion: string;
  createdAt: string;
}
