CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS studies (
  nct_id TEXT PRIMARY KEY,
  condition_group TEXT NOT NULL,
  title TEXT NOT NULL,
  brief_summary TEXT,
  detailed_description TEXT,
  conditions TEXT[] NOT NULL DEFAULT '{}',
  interventions JSONB NOT NULL DEFAULT '[]',
  study_type TEXT,
  phases TEXT[] NOT NULL DEFAULT '{}',
  enrollment INT,
  overall_status TEXT NOT NULL,
  why_stopped TEXT,
  sponsor TEXT NOT NULL,
  sponsor_class TEXT,
  start_date DATE,
  primary_completion_date DATE,
  primary_completion_type TEXT,
  completion_date DATE,
  completion_type TEXT,
  first_posted DATE,
  last_update_posted DATE,
  results_first_posted DATE,
  has_results BOOLEAN NOT NULL DEFAULT FALSE,
  is_fda_regulated BOOLEAN NOT NULL DEFAULT FALSE,
  is_applicable_trial BOOLEAN NOT NULL DEFAULT FALSE,
  registered_primary_outcomes JSONB NOT NULL DEFAULT '[]',
  reported_primary_outcomes JSONB NOT NULL DEFAULT '[]',
  adverse_events JSONB,
  reference_pmids TEXT[] NOT NULL DEFAULT '{}',
  layer_ingested_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_studies_sponsor ON studies (sponsor);
CREATE INDEX IF NOT EXISTS idx_studies_condition ON studies (condition_group);

CREATE TABLE IF NOT EXISTS papers (
  pmid TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  abstract TEXT,
  journal TEXT,
  pub_date DATE,
  is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,   -- guardrail demo papers only
  layer_ingested_at TIMESTAMPTZ,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS study_papers (
  nct_id TEXT NOT NULL REFERENCES studies(nct_id) ON DELETE CASCADE,
  pmid TEXT NOT NULL REFERENCES papers(pmid) ON DELETE CASCADE,
  link_source TEXT NOT NULL,                     -- registry_reference | pubmed_si | synthetic
  PRIMARY KEY (nct_id, pmid)
);

CREATE TABLE IF NOT EXISTS sponsor_profiles (
  sponsor TEXT PRIMARY KEY,
  sponsor_class TEXT,
  total_studies INT NOT NULL,
  applicable_completed INT NOT NULL,
  results_posted INT NOT NULL,
  missing_results INT NOT NULL,
  compliance_rate REAL,                          -- NULL when < 3 applicable completed trials
  avg_reporting_delay_days REAL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',         -- queued|running|completed|failed|blocked
  created_by TEXT NOT NULL DEFAULT 'public',     -- public|admin
  is_showcase BOOLEAN NOT NULL DEFAULT FALSE,
  selected_agents TEXT[] NOT NULL DEFAULT '{}',
  routing_reason TEXT,
  condition_group TEXT,
  brief TEXT,
  signals_count INT NOT NULL DEFAULT 0,
  pending_review_count INT NOT NULL DEFAULT 0,
  agent_stats JSONB NOT NULL DEFAULT '{}',
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  events JSONB NOT NULL DEFAULT '[]',            -- stored SSE events, used for replay
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  duration_ms INT
);

CREATE TABLE IF NOT EXISTS signals (
  signal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
  agent TEXT NOT NULL,
  signal_type TEXT NOT NULL,
  nct_id TEXT REFERENCES studies(nct_id),
  sponsor TEXT,
  related_nct_ids TEXT[] NOT NULL DEFAULT '{}',
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  evidence JSONB NOT NULL,
  confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  threshold REAL NOT NULL,
  citation_verified BOOLEAN,                     -- NULL = not checked
  status TEXT NOT NULL,                          -- auto_approved|pending_review|approved|rejected
  edited BOOLEAN NOT NULL DEFAULT FALSE,
  original_summary TEXT,
  review_reason TEXT,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (nct_id IS NOT NULL OR sponsor IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals (status);
CREATE INDEX IF NOT EXISTS idx_signals_agent ON signals (agent);
CREATE INDEX IF NOT EXISTS idx_signals_nct ON signals (nct_id);

CREATE TABLE IF NOT EXISTS agent_rules (
  rule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent TEXT NOT NULL,
  rule_text TEXT NOT NULL,
  source TEXT NOT NULL,                          -- default | learned
  learned_from_signal_id UUID REFERENCES signals(signal_id) ON DELETE SET NULL,
  reviewer_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (agent, rule_text)
);

CREATE TABLE IF NOT EXISTS guardrail_events (
  event_id BIGSERIAL PRIMARY KEY,
  run_id UUID REFERENCES runs(run_id) ON DELETE SET NULL,
  stage TEXT NOT NULL,     -- input|tool_output|signal_validation|citation_check|usage_limit
  agent TEXT,
  action TEXT NOT NULL,    -- blocked|dropped|capped|sanitized|stopped
  reason TEXT NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_runs (
  eval_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  suite TEXT NOT NULL,                           -- trials | routing
  models JSONB NOT NULL,
  dataset_size INT NOT NULL,
  metrics JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
