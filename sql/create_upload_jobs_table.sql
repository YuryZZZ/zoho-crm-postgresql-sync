-- Create upload_jobs table for large file tracking
-- Run this SQL in PostgreSQL to enable chunked upload support

CREATE TABLE IF NOT EXISTS upload_jobs (
    id SERIAL PRIMARY KEY,
    upload_id VARCHAR(100) UNIQUE NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL,
    target_table VARCHAR(100) NOT NULL,
    chunks_total INTEGER NOT NULL,
    chunks_received INTEGER DEFAULT 0,
    chunks_received_list JSONB DEFAULT '[]',
    status VARCHAR(50) DEFAULT 'uploading' CHECK (status IN ('uploading', 'processing', 'completed', 'error', 'cancelled')),
    records_processed INTEGER DEFAULT 0,
    records_inserted INTEGER DEFAULT 0,
    records_updated INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    error_message TEXT,
    error_details JSONB DEFAULT '{}',
    column_mapping JSONB DEFAULT '{}',
    processing_started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    metadata JSONB DEFAULT '{}'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_upload_jobs_status ON upload_jobs(status);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_target_table ON upload_jobs(target_table);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_created_at ON upload_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_upload_jobs_upload_id ON upload_jobs(upload_id);

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_upload_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_upload_jobs_updated_at ON upload_jobs;
CREATE TRIGGER trg_upload_jobs_updated_at
    BEFORE UPDATE ON upload_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_upload_jobs_updated_at();

-- View for active uploads
CREATE OR REPLACE VIEW active_uploads AS
SELECT 
    upload_id,
    file_name,
    target_table,
    status,
    chunks_total,
    chunks_received,
    ROUND((chunks_received::numeric / NULLIF(chunks_total, 0)) * 100, 2) as upload_percent,
    records_processed,
    records_inserted,
    created_at,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - created_at))/60 as age_minutes
FROM upload_jobs
WHERE status IN ('uploading', 'processing')
ORDER BY created_at DESC;

-- Cleanup function for old uploads
CREATE OR REPLACE FUNCTION cleanup_old_upload_jobs(max_age_hours INTEGER DEFAULT 24)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM upload_jobs 
    WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '1 hour' * max_age_hours
      AND status IN ('completed', 'error', 'cancelled');
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
