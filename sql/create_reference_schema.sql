-- Create reference_data schema for data enrichment
-- Run this SQL in PostgreSQL to enable reference data features

-- Create schema
CREATE SCHEMA IF NOT EXISTS reference_data;

-- Table metadata for uploaded reference tables
CREATE TABLE IF NOT EXISTS reference_data.table_metadata (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200),
    description TEXT,
    source_system VARCHAR(100),
    uploaded_by VARCHAR(100),
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    record_count INTEGER DEFAULT 0,
    file_name VARCHAR(255),
    file_hash VARCHAR(64),
    column_mappings JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE
);

-- Enrichment rules for matching and enriching data
CREATE TABLE IF NOT EXISTS reference_data.enrichment_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    source_table VARCHAR(100) NOT NULL REFERENCES reference_data.table_metadata(table_name),
    target_table VARCHAR(100) NOT NULL,
    match_criteria JSONB NOT NULL DEFAULT '{}',
    enrich_mappings JSONB NOT NULL DEFAULT '{}',
    confidence_threshold DECIMAL(5,2) DEFAULT 80.00,
    auto_apply BOOLEAN DEFAULT FALSE,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP,
    total_matches INTEGER DEFAULT 0
);

-- Enrichment results (pending/approved/rejected)
CREATE TABLE IF NOT EXISTS reference_data.enrichment_results (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES reference_data.enrichment_rules(id) ON DELETE CASCADE,
    source_table VARCHAR(100) NOT NULL,
    target_table VARCHAR(100) NOT NULL,
    source_record_id VARCHAR(100) NOT NULL,
    target_record_id VARCHAR(100) NOT NULL,
    match_confidence DECIMAL(5,2) NOT NULL,
    field_updates JSONB NOT NULL DEFAULT '{}',
    review_status VARCHAR(20) DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected', 'applied')),
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    applied_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for performance
CREATE INDEX IF NOT EXISTS idx_enrichment_results_rule_id ON reference_data.enrichment_results(rule_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_results_status ON reference_data.enrichment_results(review_status);
CREATE INDEX IF NOT EXISTS idx_enrichment_results_target ON reference_data.enrichment_results(target_table, target_record_id);

-- Trigger to update updated_at on enrichment_rules
CREATE OR REPLACE FUNCTION reference_data.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_enrichment_rules_updated_at ON reference_data.enrichment_rules;
CREATE TRIGGER trg_enrichment_rules_updated_at
    BEFORE UPDATE ON reference_data.enrichment_rules
    FOR EACH ROW
    EXECUTE FUNCTION reference_data.update_updated_at();

-- View for pending enrichments summary
CREATE OR REPLACE VIEW reference_data.pending_enrichments_summary AS
SELECT 
    er.target_table,
    COUNT(*) as pending_count,
    COUNT(DISTINCT er.target_record_id) as unique_records
FROM reference_data.enrichment_results er
WHERE er.review_status = 'pending'
GROUP BY er.target_table;

-- Grant permissions (adjust as needed)
-- GRANT ALL ON SCHEMA reference_data TO zoho_admin;
-- GRANT ALL ON ALL TABLES IN SCHEMA reference_data TO zoho_admin;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA reference_data TO zoho_admin;

-- Insert sample enrichment rule template (optional)
-- Uncomment to add a sample rule
/*
INSERT INTO reference_data.table_metadata (table_name, display_name, description, source_system, record_count, tags)
VALUES ('ref_company_data', 'Company Reference Data', 'External company information', 'External Provider', 1000, ARRAY['companies', 'enrichment'])
ON CONFLICT (table_name) DO NOTHING;

INSERT INTO reference_data.enrichment_rules (
    name, description, source_table, target_table, match_criteria, enrich_mappings, confidence_threshold
) VALUES (
    'Enrich Contacts with Company Data',
    'Match contacts to company reference data by company name',
    'ref_company_data',
    'contacts',
    '{"match_field": "company", "target_field": "account_name", "fuzzy": true}'::jsonb,
    '{"industry": "industry", "company_size": "number_of_employees"}'::jsonb,
    85.00
)
ON CONFLICT DO NOTHING;
*/
