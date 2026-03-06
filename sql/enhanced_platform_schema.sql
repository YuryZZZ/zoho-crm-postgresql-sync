-- ENHANCED ZOHO CRM DATA PLATFORM - POSTGRESQL SCHEMA
-- Supports: On-demand sync, dynamic tables, Excel/Google Sheets integration
-- Generated: 2026-01-20

-- ====================
-- EXTENSIONS
-- ====================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "tablefunc"; -- For pivot/crosstab
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- For monitoring

-- ====================
-- TABLE METADATA REGISTRY
-- ====================

CREATE TABLE table_metadata (
    -- Core identifiers
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    description TEXT,
    
    -- Table classification
    table_type VARCHAR(50) NOT NULL CHECK (table_type IN (
        'zoho_sync',      -- Syncs to Zoho CRM
        'support',        -- Supporting data, no sync
        'user_defined',   -- User-created tables
        'external',       -- External data sources
        'calculation'     -- Calculated/derived tables
    )),
    
    -- Sync configuration (only for zoho_sync tables)
    sync_to_zoho BOOLEAN DEFAULT false,
    zoho_module VARCHAR(100),
    sync_config JSONB DEFAULT '{}',
    
    -- Schema definition for dynamic tables
    schema_definition JSONB NOT NULL DEFAULT '[]',
    
    -- Permissions and ownership
    created_by VARCHAR(100) NOT NULL,
    owner_user_id VARCHAR(100),
    read_permissions JSONB DEFAULT '[]',  -- List of user/group IDs
    write_permissions JSONB DEFAULT '[]', -- List of user/group IDs
    
    -- Audit trail
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_data_update TIMESTAMP WITH TIME ZONE,
    
    -- Statistics
    row_count BIGINT DEFAULT 0,
    storage_size_bytes BIGINT DEFAULT 0,
    
    -- Indexes
    INDEX idx_table_metadata_type ON table_metadata(table_type),
    INDEX idx_table_metadata_created_by ON table_metadata(created_by),
    INDEX idx_table_metadata_updated ON table_metadata(updated_at DESC)
);

-- ====================
-- SYNC REQUEST QUEUE
-- ====================

CREATE TABLE sync_requests (
    -- Request identifiers
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id VARCHAR(50) UNIQUE NOT NULL, -- User-friendly ID
    table_name VARCHAR(100) NOT NULL,
    
    -- User information
    user_id VARCHAR(100) NOT NULL,
    user_email VARCHAR(255),
    
    -- Request details
    status VARCHAR(50) NOT NULL CHECK (status IN (
        'pending',      -- Waiting in queue
        'processing',   -- Currently being processed
        'completed',    -- Successfully completed
        'failed',       -- Failed with errors
        'cancelled'     -- Cancelled by user
    )),
    
    sync_direction VARCHAR(20) NOT NULL CHECK (sync_direction IN (
        'to_zoho',      -- PostgreSQL → Zoho CRM
        'from_zoho',    -- Zoho CRM → PostgreSQL
        'bidirectional' -- Both directions
    )),
    
    -- Data scope
    filter_conditions JSONB DEFAULT '{}', -- Which records to sync
    record_ids JSONB DEFAULT '[]',       -- Specific record IDs
    sync_all BOOLEAN DEFAULT true,       -- Sync entire table
    
    -- Statistics
    total_records INTEGER,
    processed_records INTEGER DEFAULT 0,
    successful_records INTEGER DEFAULT 0,
    failed_records INTEGER DEFAULT 0,
    
    -- Timing
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    estimated_completion TIMESTAMP WITH TIME ZONE,
    
    -- Results and errors
    error_message TEXT,
    error_details JSONB DEFAULT '{}',
    result_summary JSONB DEFAULT '{}',
    
    -- Priority and scheduling
    priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10), -- 1=highest, 10=lowest
    scheduled_for TIMESTAMP WITH TIME ZONE, -- For future execution
    
    -- Foreign keys
    FOREIGN KEY (table_name) REFERENCES table_metadata(table_name) ON DELETE CASCADE,
    
    -- Indexes
    INDEX idx_sync_requests_status ON sync_requests(status),
    INDEX idx_sync_requests_user ON sync_requests(user_id),
    INDEX idx_sync_requests_table ON sync_requests(table_name),
    INDEX idx_sync_requests_created ON sync_requests(requested_at DESC),
    INDEX idx_sync_requests_priority ON sync_requests(priority, requested_at)
);

-- ====================
-- FORMULA DEFINITIONS
-- ====================

CREATE TABLE table_formulas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL,
    
    -- Formula definition
    column_name VARCHAR(100) NOT NULL,
    formula_expression TEXT NOT NULL,
    formula_type VARCHAR(50) CHECK (formula_type IN (
        'excel_like',   -- Excel-style formulas
        'sql_function', -- SQL functions
        'python_code',  -- Python code execution
        'custom'        -- Custom calculation
    )),
    
    -- Dependencies and execution
    depends_on JSONB DEFAULT '[]', -- Columns this formula depends on
    calculation_order INTEGER DEFAULT 0,
    is_volatile BOOLEAN DEFAULT false, -- Recalculate on any change
    
    -- Configuration
    data_type VARCHAR(50), -- Expected result type
    default_value TEXT,    -- Default if calculation fails
    validation_rules JSONB DEFAULT '{}',
    
    -- Performance
    cache_results BOOLEAN DEFAULT true,
    cache_ttl_seconds INTEGER DEFAULT 300, -- 5 minutes
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    last_calculated_at TIMESTAMP WITH TIME ZONE,
    calculation_count BIGINT DEFAULT 0,
    
    -- Audit
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Foreign keys
    FOREIGN KEY (table_name) REFERENCES table_metadata(table_name) ON DELETE CASCADE,
    
    -- Constraints
    UNIQUE(table_name, column_name),
    
    -- Indexes
    INDEX idx_table_formulas_table ON table_formulas(table_name),
    INDEX idx_table_formulas_active ON table_formulas(is_active),
    INDEX idx_table_formulas_depends ON table_formulas USING GIN(depends_on)
);

-- ====================
-- DATA UPLOAD HISTORY
-- ====================

CREATE TABLE data_uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    upload_id VARCHAR(50) UNIQUE NOT NULL,
    
    -- Source information
    table_name VARCHAR(100) NOT NULL,
    source_type VARCHAR(50) CHECK (source_type IN (
        'excel_file',
        'csv_file', 
        'google_sheets',
        'json_file',
        'api_import',
        'manual_entry'
    )),
    
    source_details JSONB DEFAULT '{}', -- File name, sheet name, URL, etc.
    
    -- Upload statistics
    total_rows INTEGER NOT NULL,
    imported_rows INTEGER DEFAULT 0,
    skipped_rows INTEGER DEFAULT 0,
    error_rows INTEGER DEFAULT 0,
    
    -- Processing status
    status VARCHAR(50) CHECK (status IN (
        'uploading',
        'validating',
        'processing',
        'enriching',
        'completed',
        'failed',
        'partial'
    )),
    
    -- File information
    file_size_bytes BIGINT,
    file_hash VARCHAR(64), -- For deduplication
    storage_path TEXT,     -- Where file is stored
    
    -- User information
    uploaded_by VARCHAR(100) NOT NULL,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Processing timeline
    processing_started TIMESTAMP WITH TIME ZONE,
    processing_completed TIMESTAMP WITH TIME ZONE,
    
    -- Results
    validation_errors JSONB DEFAULT '[]',
    import_summary JSONB DEFAULT '{}',
    
    -- Foreign keys
    FOREIGN KEY (table_name) REFERENCES table_metadata(table_name) ON DELETE CASCADE,
    
    -- Indexes
    INDEX idx_data_uploads_table ON data_uploads(table_name),
    INDEX idx_data_uploads_status ON data_uploads(status),
    INDEX idx_data_uploads_uploaded ON data_uploads(uploaded_at DESC),
    INDEX idx_data_uploads_user ON data_uploads(uploaded_by)
);

-- ====================
-- DATA ENRICHMENT LOG
-- ====================

CREATE TABLE data_enrichment_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Enrichment context
    table_name VARCHAR(100) NOT NULL,
    enrichment_type VARCHAR(100) NOT NULL, -- 'cleaning', 'validation', 'geocoding', etc.
    
    -- Scope
    record_count INTEGER NOT NULL,
    column_names JSONB DEFAULT '[]',
    
    -- Execution
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds DECIMAL(10,3),
    
    -- Results
    changes_applied INTEGER DEFAULT 0,
    errors_found INTEGER DEFAULT 0,
    warnings INTEGER DEFAULT 0,
    
    -- Details
    enrichment_config JSONB DEFAULT '{}',
    result_details JSONB DEFAULT '{}',
    error_log JSONB DEFAULT '[]',
    
    -- Performed by
    executed_by VARCHAR(100),
    
    -- Foreign keys
    FOREIGN KEY (table_name) REFERENCES table_metadata(table_name) ON DELETE CASCADE,
    
    -- Indexes
    INDEX idx_data_enrichment_table ON data_enrichment_log(table_name),
    INDEX idx_data_enrichment_type ON data_enrichment_log(enrichment_type),
    INDEX idx_data_enrichment_time ON data_enrichment_log(started_at DESC)
);

-- ====================
-- USER SESSIONS & REQUESTS
-- ====================

CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id VARCHAR(100) UNIQUE NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    
    -- Session details
    ip_address INET,
    user_agent TEXT,
    referrer TEXT,
    
    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    
    -- Session data
    session_data JSONB DEFAULT '{}',
    
    -- Indexes
    INDEX idx_user_sessions_user ON user_sessions(user_id),
    INDEX idx_user_sessions_expires ON user_sessions(expires_at),
    INDEX idx_user_sessions_activity ON user_sessions(last_activity DESC)
);

CREATE TABLE api_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id VARCHAR(100) UNIQUE,
    
    -- Request details
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    user_id VARCHAR(100),
    session_id VARCHAR(100),
    
    -- Timing
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    response_time_ms INTEGER,
    
    -- Status
    status_code INTEGER,
    success BOOLEAN,
    
    -- Request/Response data
    request_headers JSONB DEFAULT '{}',
    request_body TEXT,
    response_headers JSONB DEFAULT '{}',
    response_body TEXT,
    
    -- Errors
    error_message TEXT,
    stack_trace TEXT,
    
    -- Performance
    query_count INTEGER DEFAULT 0,
    query_time_ms INTEGER DEFAULT 0,
    
    -- Foreign keys
    FOREIGN KEY (session_id) REFERENCES user_sessions(session_id) ON DELETE SET NULL,
    
    -- Indexes
    INDEX idx_api_requests_endpoint ON api_requests(endpoint),
    INDEX idx_api_requests_user ON api_requests(user_id),
    INDEX idx_api_requests_time ON api_requests(requested_at DESC),
    INDEX idx_api_requests_status ON api_requests(status_code)
);

-- ====================
-- AUDIT TRAIL
-- ====================

CREATE TABLE audit_trail (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- Event information
    event_type VARCHAR(100) NOT NULL,
    event_subtype VARCHAR(100),
    
    -- Entity information
    table_name VARCHAR(100),
    record_id VARCHAR(100),
    column_name VARCHAR(100),
    
    -- Changes
    old_value JSONB,
    new_value JSONB,
    change_description TEXT,
    
    -- User context
    user_id VARCHAR(100),
    user_email VARCHAR(255),
    ip_address INET,
    
    -- Timing
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Additional context
    request_id VARCHAR(100),
    session_id VARCHAR(100),
    
    -- Indexes
    INDEX idx_audit_trail_event ON audit_trail(event_type),
    INDEX idx_audit_trail_table ON audit_trail(table_name),
    INDEX idx_audit_trail_user ON audit_trail(user_id),
    INDEX idx_audit_trail_time ON audit_trail(created_at DESC)
);

-- ====================
-- SYSTEM CONFIGURATION
-- ====================

CREATE TABLE system_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    config_key VARCHAR(100) UNIQUE NOT NULL,
    config_value JSONB NOT NULL,
    config_type VARCHAR(50) CHECK (config_type IN ('string', 'number', 'boolean', 'array', 'object')),
    description TEXT,
    
    -- Scope
    scope VARCHAR(50) DEFAULT 'global' CHECK (scope IN ('global', 'user', 'table', 'module')),
    scope_id VARCHAR(100), -- user_id, table_name, etc.
    
    -- Versioning
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true,
    
    -- Audit
    created_by VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100),
    
    -- Indexes
    INDEX idx_system_config_key ON system_config(config_key),
    INDEX idx_system_config_scope ON system_config(scope, scope_id),
    INDEX idx_system_config_active ON system_config(is_active)
);

-- ====================
-- VIEWS FOR REPORTING
-- ====================

-- View for table statistics
CREATE VIEW table_statistics AS
SELECT 
    tm.table_name,
    tm.display_name,
    tm.table_type,
    tm.sync_to_zoho,
    tm.row_count,
    tm.storage_size_bytes,
    tm.last_data_update,
    COUNT(DISTINCT sr.id) as sync_request_count,
    COUNT(DISTINCT du.id) as upload_count,
    COUNT(DISTINCT tf.id) as formula_count
FROM table_metadata tm
LEFT JOIN sync_requests sr ON sr.table_name = tm.table_name
LEFT JOIN data_uploads du ON du.table_name = tm.table_name
LEFT JOIN table_formulas tf ON tf.table_name = tm.table_name
GROUP BY tm.id, tm.table_name, tm.display_name, tm.table_type, tm.sync_to_zoho, 
         tm.row_count, tm.storage_size_bytes, tm.last_data_update;

-- View for sync performance
CREATE VIEW sync_performance AS
SELECT 
    table_name,
    sync_direction,
    COUNT(*) as total_requests,
    AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration_seconds,
    MIN(EXTRACT(EPOCH FROM (completed_at - started_at))) as min_duration_seconds,
    MAX(EXTRACT(EPOCH FROM (completed_at - started_at))) as max_duration_seconds,
    AVG(successful_records::DECIMAL / NULLIF(total_records, 0)) as success_rate,
    SUM(total_records) as total_records_processed
FROM sync_requests 
WHERE status = 'completed' AND started_at IS NOT NULL AND completed_at IS NOT NULL
GROUP BY table_name, sync_direction;

-- View for user activity
CREATE VIEW user_activity_summary AS
SELECT 
    user_id,
    COUNT(DISTINCT session_id) as session_count,
    MIN(created_at) as first_activity,
    MAX(last_activity) as last_activity,
    COUNT(DISTINCT table_name) as tables_accessed,
    COUNT(*) as total_requests,
    SUM(CASE WHEN success = true THEN 1 ELSE 0 END) as successful_requests,
    AVG(response_time_ms) as avg_response_time_ms
FROM api_requests ar
LEFT JOIN user_sessions us ON ar.session_id = us.session_id
WHERE ar.requested_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
GROUP BY user_id;

-- ====================
-- FUNCTIONS AND TRIGGERS
-- ====================

-- Function to update table_metadata.updated_at
CREATE OR REPLACE FUNCTION update_table_metadata_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_table_metadata_timestamp
    BEFORE UPDATE ON table_metadata
    FOR EACH ROW
    EXECUTE FUNCTION update_table_metadata_timestamp();

-- Function to log audit trail for table changes
CREATE OR REPLACE FUNCTION log_table_change_audit()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_trail (
        event_type, table_name, record_id, 
        old_value, new_value, change_description,
        user_id, created_at
    ) VALUES (
        'table_metadata_change',
        NEW.table_name,
        NEW.id::TEXT,
        to_jsonb(OLD),
        to_jsonb(NEW),
        'Table metadata updated',
        NEW.created_by,
        CURRENT_TIMESTAMP
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_log_table_change_audit
    AFTER UPDATE ON table_metadata
    FOR EACH ROW
    EXECUTE FUNCTION log_table_change_audit();

-- Function to automatically update row_count
CREATE OR REPLACE FUNCTION update_table_row_count()
RETURNS TRIGGER AS $$
DECLARE
    table_schema TEXT;
    table_name_only TEXT;
    row_count BIGINT;
BEGIN
    -- Parse schema and table name
    table_schema := split_part(TG_TABLE_SCHEMA, '.', 1);
    table_name_only := split_part(TG_TABLE_NAME, '.', 2);
    
    -- Get actual row count (expensive but accurate)
    EXECUTE format('SELECT COUNT(*) FROM %I.%I', table_schema, table_name_only) INTO row_count;
    
    -- Update metadata
    UPDATE table_metadata 
    SET row_count = row_count,
        last_data_update = CURRENT_TIMESTAMP
    WHERE table_name = TG_TABLE_NAME;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Note: Dynamic triggers for user tables will be created programmatically

-- ====================
-- INITIAL CONFIGURATION
-- ====================

-- Insert default configuration
INSERT INTO system_config (config_key, config_value, config_type, description, scope) VALUES
('sync.max_concurrent_requests', '5', 'number', 'Maximum concurrent sync requests', 'global'),
('sync.default_priority', '5', 'number', 'Default priority for sync requests', 'global'),
('sync.timeout_minutes', '30', 'number', 'Sync request timeout in minutes', 'global'),
('upload.max_file_size_mb', '100', 'number', 'Maximum upload file size in MB', 'global'),
('upload.allowed_formats', '["excel", "csv", "json"]', 'array', 'Allowed upload formats', 'global'),
('formula.cache_enabled', 'true', 'boolean', 'Enable formula result caching', 'global'),
('formula.max_recursion_depth', '10', 'number', 'Maximum formula recursion depth', 'global'),
('api.rate_limit_per_minute', '100', 'number', 'API rate limit per minute per user', 'global'),
('security.session_timeout_hours', '24', 'number', 'Session timeout in hours', 'global'),
('monitoring.retention_days', '90', 'number', 'Days to retain monitoring data', 'global');

-- Insert existing Zoho CRM tables into metadata
INSERT INTO table_metadata (
    table_name, display_name, description, table_type, 
    sync_to_zoho, zoho_module, created_by, schema_definition
) VALUES
('leads', 'Leads', 'Zoho CRM Leads', 'zoho_sync', true, 'Leads', 'system', 
 '[{"name": "zoho_id", "type": "varchar", "length": 100, "nullable": false},
   {"name": "first_name", "type": "varchar", "length": 100, "nullable": true},
   {"name": "last_name", "type": "varchar", "length": 100, "nullable": true},
   {"name": "email", "type": "varchar", "length": 255, "nullable": true},
   {"name": "company", "type": "varchar", "length": 255, "nullable": true}]'),
   
('contacts', 'Contacts', 'Zoho CRM Contacts', 'zoho_sync', true, 'Contacts', 'system',
 '[{"name": "zoho_id", "type": "varchar", "length": 100, "nullable": false},
   {"name": "first_name", "type": "varchar", "length": 100, "nullable": true},
   {"name": "last_name", "type": "varchar", "length": 100, "nullable": true},
   {"name": "email", "type": "varchar", "length": 255, "nullable": true},
   {"name": "account_id", "type": "varchar", "length": 100, "nullable": true}]'),
   
('accounts', 'Accounts', 'Zoho CRM Accounts', 'zoho_sync', true, 'Accounts', 'system',
 '[{"name": "zoho_id", "type": "varchar", "length": 100, "nullable": false},
   {"name": "account_name", "type": "varchar", "length": 255, "nullable": true},
   {"name": "website", "type": "varchar", "length": 255, "nullable": true},
   {"name": "industry", "type": "varchar", "length": 100, "nullable": true}]');

-- ====================
-- COMMENTS
-- ====================

COMMENT ON TABLE table_metadata IS 'Metadata registry for all tables in the system';
COMMENT ON TABLE sync_requests IS 'Queue for on-demand sync requests to Zoho CRM';
COMMENT ON TABLE table_formulas IS 'Formula definitions for calculated columns';
COMMENT ON TABLE data_uploads IS 'History of data uploads from various sources';
COMMENT ON TABLE data_enrichment_log IS 'Log of data enrichment operations';
COMMENT ON TABLE user_sessions IS 'User session tracking';
COMMENT ON TABLE api_requests IS 'API request logging for monitoring';
COMMENT ON TABLE audit_trail IS 'Comprehensive audit trail for all changes';
COMMENT ON TABLE system_config IS 'System configuration storage';

COMMENT ON COLUMN table_metadata.schema_definition IS 'JSON array of column definitions for dynamic tables';
COMMENT ON COLUMN sync_requests.filter_conditions IS 'JSON filter conditions for selective sync';
COMMENT ON COLUMN table_formulas.depends_on IS 'JSON array of column names this formula depends on';
COMMENT ON COLUMN data_uploads.source_details IS 'JSON details about the upload source';

-- ====================
-- GRANTS (Example - adjust based on your security model)
-- ====================

-- Example: Create read-only role for reporting
-- CREATE ROLE data_viewer;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO data_viewer;
-- GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO data_viewer;

-- Example: Create application role
-- CREATE ROLE app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- ====================
-- END OF SCHEMA
-- ====================