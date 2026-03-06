-- Initialize Staging Workflow Schema
-- Run this SQL to create the staging schema and tables

-- Create staging schema
CREATE SCHEMA IF NOT EXISTS zoho_staging;

-- Staging table for pending changes
CREATE TABLE IF NOT EXISTS zoho_staging.pending_changes (
    id SERIAL PRIMARY KEY,
    staging_id VARCHAR(100) UNIQUE NOT NULL,
    source_table VARCHAR(100) NOT NULL,
    source_record_id VARCHAR(100),
    zoho_record_id VARCHAR(100),
    change_type VARCHAR(20) NOT NULL CHECK (change_type IN ('create', 'update', 'delete', 'enrich')),
    original_data JSONB,
    proposed_data JSONB NOT NULL,
    validation_status VARCHAR(20) DEFAULT 'pending' CHECK (validation_status IN ('pending', 'valid', 'invalid', 'approved', 'rejected')),
    validation_errors JSONB DEFAULT '[]'::jsonb,
    review_status VARCHAR(20) DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    push_status VARCHAR(20) DEFAULT 'pending' CHECK (push_status IN ('pending', 'queued', 'pushed', 'failed')),
    push_attempts INTEGER DEFAULT 0,
    last_push_error TEXT,
    pushed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP + INTERVAL '7 days'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_staging_source_table ON zoho_staging.pending_changes(source_table);
CREATE INDEX IF NOT EXISTS idx_staging_validation_status ON zoho_staging.pending_changes(validation_status);
CREATE INDEX IF NOT EXISTS idx_staging_review_status ON zoho_staging.pending_changes(review_status);
CREATE INDEX IF NOT EXISTS idx_staging_push_status ON zoho_staging.pending_changes(push_status);
CREATE INDEX IF NOT EXISTS idx_staging_expires ON zoho_staging.pending_changes(expires_at);

-- Validation rules table
CREATE TABLE IF NOT EXISTS zoho_staging.validation_rules (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    rule_type VARCHAR(50) NOT NULL CHECK (rule_type IN ('required', 'email', 'phone', 'url', 'regex', 'range', 'enum', 'custom')),
    rule_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_name, field_name, rule_type)
);

-- Sync queue for approved changes
CREATE TABLE IF NOT EXISTS zoho_staging.sync_queue (
    id SERIAL PRIMARY KEY,
    staging_id VARCHAR(100) NOT NULL REFERENCES zoho_staging.pending_changes(staging_id),
    priority INTEGER DEFAULT 5,
    scheduled_for TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    processing_status VARCHAR(20) DEFAULT 'queued' CHECK (processing_status IN ('queued', 'processing', 'completed', 'failed')),
    retry_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON zoho_staging.sync_queue(processing_status);
CREATE INDEX IF NOT EXISTS idx_sync_queue_scheduled ON zoho_staging.sync_queue(scheduled_for);

-- Audit log
CREATE TABLE IF NOT EXISTS zoho_staging.audit_log (
    id SERIAL PRIMARY KEY,
    staging_id VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    performed_by VARCHAR(100),
    old_values JSONB,
    new_values JSONB,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_staging_id ON zoho_staging.audit_log(staging_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON zoho_staging.audit_log(created_at);

-- Staging table registry
CREATE TABLE IF NOT EXISTS zoho_staging.staging_table_registry (
    id SERIAL PRIMARY KEY,
    staging_table VARCHAR(100) UNIQUE NOT NULL,
    source_table VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP + INTERVAL '7 days',
    custom_fields JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT TRUE
);

-- Insert sample validation rules for common fields
INSERT INTO zoho_staging.validation_rules (table_name, field_name, rule_type, rule_config, error_message)
VALUES 
    ('contacts', 'email', 'email', '{}', 'Email must be valid'),
    ('contacts', 'first_name', 'required', '{}', 'First name is required'),
    ('contacts', 'last_name', 'required', '{}', 'Last name is required'),
    ('accounts', 'account_name', 'required', '{}', 'Account name is required'),
    ('leads', 'email', 'email', '{}', 'Email must be valid'),
    ('leads', 'last_name', 'required', '{}', 'Last name is required')
ON CONFLICT (table_name, field_name, rule_type) DO NOTHING;

-- Function to clean up expired staging data
CREATE OR REPLACE FUNCTION zoho_staging.cleanup_expired()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    -- Move expired records to archive or delete
    DELETE FROM zoho_staging.pending_changes 
    WHERE expires_at < CURRENT_TIMESTAMP 
      AND push_status IN ('pushed', 'failed');
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    -- Clean up old staging tables
    -- Note: This requires dynamic SQL and should be run manually or via scheduled job
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- View for pending changes summary
CREATE OR REPLACE VIEW zoho_staging.pending_changes_summary AS
SELECT 
    source_table,
    validation_status,
    review_status,
    push_status,
    COUNT(*) as count
FROM zoho_staging.pending_changes
GROUP BY source_table, validation_status, review_status, push_status;

-- Grant permissions (adjust as needed)
-- GRANT ALL ON SCHEMA zoho_staging TO zoho_admin;
-- GRANT ALL ON ALL TABLES IN SCHEMA zoho_staging TO zoho_admin;
