// Backend 버전 1 API와 대응하는 공통 TypeScript 규약이다.
export type User = {
  id: string;
  email: string;
  name: string;
  role: "ADMIN" | "USER";
  is_active: boolean;
};

export type Parser = {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  provider: string | null;
  model_name: string | null;
  model_version: string | null;
  execution_type: "BUILTIN" | "HTTP" | "COMMAND";
  adapter_key: string;
  base_url: string | null;
  command_template: string[] | null;
  default_config: Record<string, unknown>;
  config_schema: Record<string, unknown>;
  capabilities: string[];
  supported_formats: string[];
  timeout_seconds: number;
  is_active: boolean;
  created_by: string;
};

export type ParserPreset = {
  id: string;
  parser_connector_id: string;
  name: string;
  description: string | null;
  config: Record<string, unknown>;
  created_by: string;
  created_at: string;
};

export type DocumentItem = {
  id: string;
  original_filename: string;
  mime_type: string;
  extension: string;
  file_size: number;
  sha256: string;
  page_count: number | null;
  uploaded_by: string;
  created_at: string;
};

export type Run = {
  id: string;
  parser_snapshot: {
    name: string;
    model_name?: string;
    model_version?: string;
  };
  parse_status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "INTERRUPTED";
  deidentification_status: string;
  latency_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  deidentification: DeidentificationSummary | null;
};

export type DeidentificationSummary = {
  provider: string;
  input_type: string;
  detected_entity_count: number | null;
  masked_entity_count: number | null;
  masked_file_available: boolean;
  latency_ms: number | null;
  error_message: string | null;
};

export type ManualEvaluation = {
  id: string;
  run_id: string;
  evaluator_id: string;
  text_score: number | null;
  table_score: number | null;
  reading_order_score: number | null;
  deidentification_score: number | null;
  is_preferred: boolean;
  notes: string | null;
};

export type TableCell = {
  row: number;
  column: number;
  row_span: number;
  column_span: number;
  text: string;
};

export type CanonicalTable = {
  id: string | null;
  page_number: number | null;
  text: string;
  html: string | null;
  cells: TableCell[];
};

export type Experiment = {
  id: string;
  name: string;
  description: string | null;
  document_id: string;
  document_filename: string;
  created_at: string;
  status: "PENDING" | "RUNNING" | "PARTIALLY_COMPLETED" | "COMPLETED" | "FAILED";
  run_count: number;
};

export type ExperimentDetail = Experiment & {
  run_deidentification: boolean;
  runs: Run[];
};

export type ComparisonRun = {
  run_id: string;
  parser_name: string;
  parser_version: string | null;
  parse_status: string;
  deidentification_status: string;
  metrics: {
    latency_ms: number | null;
    page_count: number | null;
    text_length: number;
    block_count: number;
    table_count: number;
    image_count: number;
    result_size_bytes: number;
    page_text_lengths: number[];
  };
  preview_text: string | null;
  text: string | null;
  markdown: string | null;
  deidentified: string | null;
  deidentification: DeidentificationSummary | null;
  canonical: Record<string, unknown> | unknown[] | null;
  tables: CanonicalTable[];
  evaluation: ManualEvaluation | null;
};

export type Comparison = {
  experiment_id: string;
  document: { id: string; filename: string };
  runs: ComparisonRun[];
};

export type TextDiff = {
  base_run_id: string;
  target_run_id: string;
  similarity_ratio: number;
  added_count: number;
  removed_count: number;
  diff: Array<{ type: "equal" | "added" | "removed"; text: string }>;
};
