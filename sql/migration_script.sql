-- Migration Script for Enhanced Zoho CRM Platform
-- Applies enhanced schema to existing Cloud SQL PostgreSQL instance
-- Run this script after deploying the enhanced_platform_complete_schema.sql

-- ============================================
-- MIGRATION: BACKUP EXISTING DATA
-- ============================================

-- Create backup of critical existing tables
CREATE TABLE IF NOT EXISTS backup_users AS SELECT * FROM users;
CREATE TABLE IF NOT EXISTS backup_table_metadata AS SELECT * FROM table_metadata;
CREATE TABLE IF NOT EXISTS backup_sync_requests AS SELECT * FROM sync_requests;

-- ============================================
-- MIGRATION: TEMPORARY DISABLE CONSTRAINTS
-- ============================================

-- Temporarily disable foreign key constraints for migration
ALTER TABLE sync_requests DROP CONSTRAINT IF EXISTS sync_requests_table_name_fkey;
ALTER TABLE sync_requests DROP CONSTRAINT IF EXISTS sync_requests_user_id_fkey;

-- ============================================
-- MIGRATION: CREATE NEW TABLES IF NOT EXISTS
-- ============================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create users table if it doesn't exist
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    is_admin BOOLEAN DEFAULT false,
    last_login TIMESTAMP WITH TIME ZONE,
    failed_login_attempts INTEGER DEFAULT 0,
    account_locked_until TIMESTAMP WITH TIME ZONE,
    mfa_enabled BOOLEAN DEFAULT false,
    mfa_secret VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_by UUID REFERENCES users(id),
    metadata JSONB DEFAULT '{}'
);

-- Create user_sessions table
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_token VARCHAR(512) UNIQUE NOT NULL,
    refresh_token VARCHAR(512) UNIQUE NOT NULL,
    user_agent TEXT,
    ip_address INET,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked BOOLEAN DEFAULT false,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create api_keys table
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    key_hash VARCHAR(512) UNIQUE NOT NULL,
    scopes JSONB DEFAULT '["read", "write"]',
    expires_at TIMESTAMP WITH TIME ZONE,
    last_used TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create table_metadata if it doesn't exist
CREATE TABLE IF NOT EXISTS table_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    description TEXT,
    table_type VARCHAR(50) CHECK (table_type IN ('zoho_sync', 'support', 'user_defined', 'system')),
    sync_to_zoho BOOLEAN DEFAULT false,
    zoho_module VARCHAR(100),
    schema_definition JSONB NOT NULL DEFAULT '{}',
    row_level_security_enabled BOOLEAN DEFAULT false,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true
);

-- Create table_permissions table
CREATE TABLE IF NOT EXISTS table_permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL REFERENCES table_metadata(table_name) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    permission_type VARCHAR(50) CHECK (permission_type IN ('owner', 'admin', 'editor', 'viewer', 'none')),
    can_read BOOLEAN DEFAULT false,
    can_write BOOLEAN DEFAULT false,
    can_delete BOOLEAN DEFAULT false,
    can_manage BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_name, user_id)
);

-- Create sync_requests if it doesn't exist
CREATE TABLE IF NOT EXISTS sync_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL REFERENCES table_metadata(table_name),
    user_id UUID NOT NULL REFERENCES users(id),
    status VARCHAR(50) CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')) DEFAULT 'pending',
    sync_direction VARCHAR(20) CHECK (sync_direction IN ('to_zoho', 'from_zoho', 'bidirectional')) NOT NULL,
    records_count INTEGER DEFAULT 0,
    records_processed INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    filter_criteria JSONB DEFAULT '{}',
    priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    requested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create sync_logs table
CREATE TABLE IF NOT EXISTS sync_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sync_request_id UUID REFERENCES sync_requests(id) ON DELETE CASCADE,
    table_name VARCHAR(100) NOT NULL,
    record_id VARCHAR(255),
    operation VARCHAR(50) CHECK (operation IN ('create', 'update', 'delete', 'skip', 'error')),
    zoho_id VARCHAR(255),
    local_id VARCHAR(255),
    status VARCHAR(50),
    error_message TEXT,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create table_formulas table
CREATE TABLE IF NOT EXISTS table_formulas (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL REFERENCES table_metadata(table_name) ON DELETE CASCADE,
    column_name VARCHAR(100) NOT NULL,
    formula_expression TEXT NOT NULL,
    formula_type VARCHAR(50) CHECK (formula_type IN ('calculated', 'validation', 'derived', 'aggregated')),
    data_type VARCHAR(50) CHECK (data_type IN ('text', 'numeric', 'boolean', 'date', 'timestamp')),
    depends_on JSONB DEFAULT '[]',
    calculation_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    last_calculated TIMESTAMP WITH TIME ZONE,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_name, column_name)
);

-- Create formula_execution_logs table
CREATE TABLE IF NOT EXISTS formula_execution_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    formula_id UUID REFERENCES table_formulas(id) ON DELETE CASCADE,
    table_name VARCHAR(100) NOT NULL,
    record_count INTEGER DEFAULT 0,
    execution_time_ms INTEGER,
    status VARCHAR(50) CHECK (status IN ('success', 'partial', 'failed')),
    error_message TEXT,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create google_sheets_connections table
CREATE TABLE IF NOT EXISTS google_sheets_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    connection_name VARCHAR(255) NOT NULL,
    spreadsheet_id VARCHAR(255) NOT NULL,
    sheet_name VARCHAR(255),
    access_token TEXT,
    refresh_token TEXT,
    token_expires_at TIMESTAMP WITH TIME ZONE,
    sync_enabled BOOLEAN DEFAULT true,
    sync_interval_minutes INTEGER DEFAULT 5,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(50) DEFAULT 'idle',
    mapping_config JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, spreadsheet_id, sheet_name)
);

-- Create data_uploads table
CREATE TABLE IF NOT EXISTS data_uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    file_name VARCHAR(255) NOT NULL,
    file_size_bytes BIGINT,
    file_type VARCHAR(50) CHECK (file_type IN ('excel', 'csv', 'json', 'google_sheets')),
    target_table VARCHAR(100) REFERENCES table_metadata(table_name),
    upload_mode VARCHAR(50) CHECK (upload_mode IN ('append', 'replace', 'update')) DEFAULT 'append',
    records_total INTEGER DEFAULT 0,
    records_processed INTEGER DEFAULT 0,
    records_failed INTEGER DEFAULT 0,
    status VARCHAR(50) CHECK (status IN ('uploading', 'processing', 'completed', 'failed', 'cancelled')) DEFAULT 'uploading',
    error_message TEXT,
    storage_path TEXT,
    metadata JSONB DEFAULT '{}',
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE
);

-- Create saved_queries table
CREATE TABLE IF NOT EXISTS saved_queries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    query_text TEXT NOT NULL,
    query_type VARCHAR(50) CHECK (query_type IN ('sql', 'visual', 'filter', 'aggregation')),
    table_name VARCHAR(100) REFERENCES table_metadata(table_name),
    parameters JSONB DEFAULT '{}',
    is_public BOOLEAN DEFAULT false,
    execution_count INTEGER DEFAULT 0,
    last_executed TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create query_execution_history table
CREATE TABLE IF NOT EXISTS query_execution_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    query_id UUID REFERENCES saved_queries(id) ON DELETE SET NULL,
    query_text TEXT NOT NULL,
    execution_time_ms INTEGER,
    rows_returned INTEGER,
    status VARCHAR(50) CHECK (status IN ('success', 'error', 'cancelled')),
    error_message TEXT,
    parameters JSONB DEFAULT '{}',
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    action_type VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    table_name VARCHAR(100),
    old_values JSONB,
    new_values JSONB,
    ip_address INET,
    user_agent TEXT,
    status VARCHAR(50) CHECK (status IN ('success', 'failure', 'warning')),
    error_message TEXT,
    performed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create data_enrichment_configs table
CREATE TABLE IF NOT EXISTS data_enrichment_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    enrichment_type VARCHAR(50) CHECK (enrichment_type IN ('cleaning', 'validation', 'transformation', 'augmentation', 'deduplication')),
    target_table VARCHAR(100) REFERENCES table_metadata(table_name),
    configuration JSONB NOT NULL DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    run_on_insert BOOLEAN DEFAULT true,
    run_on_update BOOLEAN DEFAULT true,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create system_config table
CREATE TABLE IF NOT EXISTS system_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    config_key VARCHAR(255) UNIQUE NOT NULL,
    config_value JSONB NOT NULL,
    config_type VARCHAR(50) CHECK (config_type IN ('string', 'number', 'boolean', 'array', 'object')),
    description TEXT,
    is_encrypted BOOLEAN DEFAULT false,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- MIGRATION: CREATE INDEXES
-- ============================================

-- Indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_email_active ON users(email, is_active);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires ON user_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);

-- Indexes for table_metadata
CREATE INDEX IF NOT EXISTS idx_table_metadata_type ON table_metadata(table_type);
CREATE INDEX IF NOT EXISTS idx_table_metadata_sync ON table_metadata(sync_to_zoho);
CREATE INDEX IF NOT EXISTS idx_table_metadata_active_type ON table_metadata(is_active, table_type);

-- Indexes for table_permissions
CREATE INDEX IF NOT EXISTS idx_table_permissions_user ON table_permissions(user_id);
CREATE INDEX IF NOT EXISTS idx_table_permissions_table ON table_permissions(table_name);

-- Indexes for sync_requests
CREATE INDEX IF NOT EXISTS idx_sync_requests_status ON sync_requests(status);
CREATE INDEX IF NOT EXISTS idx_sync_requests_user ON sync_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_sync_requests_table ON sync_requests(table_name);
CREATE INDEX IF NOT EXISTS idx_sync_requests_created ON sync_requests(requested_at);
CREATE INDEX IF NOT EXISTS idx_sync_requests_pending ON sync_requests(status, priority) WHERE status = 'pending';

-- Indexes for sync_logs
CREATE INDEX IF NOT EXISTS idx_sync_logs_request ON sync_logs(sync_request_id);
CREATE INDEX IF NOT EXISTS idx_sync_logs_table ON sync_logs(table_name);
CREATE INDEX IF NOT EXISTS idx_sync_logs_created ON sync_logs(created_at);

-- Indexes for table_formulas
CREATE INDEX IF NOT EXISTS idx_table_formulas_table ON table_formulas(table_name);
CREATE INDEX IF NOT EXISTS idx_table_formulas_active ON table_formulas(is_active);

-- Indexes for formula_execution_logs
CREATE INDEX IF NOT EXISTS idx_formula_logs_formula ON formula_execution_logs(formula_id);
CREATE INDEX IF NOT EXISTS idx_formula_logs_executed ON formula_execution_logs(executed_at);

-- Indexes for google_sheets_connections
CREATE INDEX IF NOT EXISTS idx_google_sheets_user ON google_sheets_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_google_sheets_sync ON google_sheets_connections(sync_enabled);

-- Indexes for data_uploads
CREATE INDEX IF NOT EXISTS idx_data_uploads_user ON data_uploads(user_id);
CREATE INDEX IF NOT EXISTS idx_data_uploads_status ON data_uploads(status);
CREATE INDEX IF NOT EXISTS idx_data_uploads_uploaded ON data_uploads(uploaded_at);
CREATE INDEX IF NOT EXISTS idx_data_uploads_recent ON data_uploads(user_id, uploaded_at DESC);

-- Indexes for saved_queries
CREATE INDEX IF NOT EXISTS idx_saved_queries_user ON saved_queries(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_queries_table ON saved_queries(table_name);

-- Indexes for query_execution_history
CREATE INDEX IF NOT EXISTS idx_query_history_user ON query_execution_history(user_id);
CREATE INDEX IF NOT EXISTS idx_query_history_executed ON query_execution_history(executed_at);

-- Indexes for audit_logs
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_performed ON audit_logs(performed_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);

-- Indexes for data_enrichment_configs
CREATE INDEX IF NOT EXISTS idx_enrichment_configs_table ON data_enrichment_configs(target_table);
CREATE INDEX IF NOT EXISTS idx_enrichment_configs_active ON data_enrichment_configs(is_active);

-- Indexes for system_config
CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(config_key);

-- ============================================
-- MIGRATION: CREATE VIEWS
-- ============================================

-- View for dashboard statistics
CREATE OR REPLACE VIEW platform_stats AS
SELECT 
    (SELECT COUNT(*) FROM users WHERE is_active = true) as active_users,
    (SELECT COUNT(*) FROM table_metadata WHERE is_active = true) as active_tables,
    (SELECT COUNT(*) FROM sync_requests WHERE status = 'pending') as pending_syncs,
    (SELECT COUNT(*) FROM data_uploads WHERE status = 'processing') as processing_uploads,
    (SELECT COUNT(*) FROM google_sheets_connections WHERE sync_enabled = true) as active_sheets_connections;

-- View for user activity
CREATE OR REPLACE VIEW user_activity_summary AS
SELECT 
    u.id as user_id,
    u.email,
    u.full_name,
    COUNT(DISTINCT al.id) as total_actions,
    MAX(al.performed_at) as last_activity,
    COUNT(DISTINCT sr.id) as sync_requests_count,
    COUNT(DISTINCT du.id) as uploads_count
FROM users u
LEFT JOIN audit_logs al ON al.user_id = u.id
LEFT JOIN sync_requests sr ON sr.user_id = u.id
LEFT JOIN data_uploads du ON du.user_id = u.id
WHERE u.is_active = true
GROUP BY u.id, u.email, u.full_name;

-- ============================================
-- MIGRATION: CREATE FUNCTIONS AND TRIGGERS
-- ============================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Function for audit logging
CREATE OR REPLACE FUNCTION log_audit_event()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO audit_logs (
        user_id,
        action_type,
        resource_type,
        resource_id,
        table_name,
        old_values,
        new_values
    ) VALUES (
        COALESCE(NEW.updated_by, NEW.created_by),
        TG_OP,
        TG_TABLE_NAME,
        COALESCE(NEW.id::text, OLD.id::text),
        TG_TABLE_NAME,
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN row_to_json(OLD) ELSE NULL END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN row_to_json(NEW) ELSE NULL END
    );
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to tables
DO $$ 
DECLARE 
    tbl RECORD;
BEGIN
    FOR tbl IN 
        SELECT table_name 
        FROM information_schema.columns 
        WHERE column_name = 'updated_at' 
        AND table_schema = 'public'
        AND table_name NOT LIKE 'pg_%'
        AND table_name NOT IN ('backup_users', 'backup_table_metadata', 'backup_sync_requests')
    LOOP
        EXECUTE format('
            DROP TRIGGER IF EXISTS update_%s_updated_at ON %s;
            CREATE TRIGGER update_%s_updated_at
            BEFORE UPDATE ON %s
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        ', tbl.table_name, tbl.table_name, tbl.table_name, tbl.table_name);
    END LOOP;
END $$;

-- ============================================
-- MIGRATION: INSERT DEFAULT DATA
-- ============================================

-- Insert default admin user if not exists (password: Admin123!)
INSERT INTO users (id, email, username, full_name, password_hash, is_active, is_admin)
SELECT 
    '00000000-0000-0000-0000-000000000001',
    'admin@zoho-platform.com',
    'admin',
    'System Administrator',
    -- bcrypt hash for 'Admin123!'
    '$2b$12$LQv3c1yqBWVHxkd0L9kZjOqCMLv5gQlHJUuB7tCKvj6pJN9JQY8W2',
    true,
    true
WHERE NOT EXISTS (SELECT 1 FROM users WHERE email = 'admin@zoho-platform.com');

-- Insert system configuration
INSERT INTO system_config (config_key, config_value, config_type, description)
SELECT 'platform.name', '"Enhanced Zoho CRM Platform"', 'string', 'Platform display name'
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'platform.name');

INSERT INTO system_config (config_key, config_value, config_type, description)
SELECT 'platform.version', '"1.0.0"', 'string', 'Platform version'
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'platform.version');

INSERT INTO system_config (config_key, config_value, config_type, description)
SELECT 'security.password.min_length', '8', 'number', 'Minimum password length'
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'security.password.min_length');

INSERT INTO system_config (config_key, config_value, config_type, description)
SELECT 'security.password.require_special', 'true', 'boolean', 'Require special characters in passwords'
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'security.password.require_special');

INSERT INTO system_config (config_key, config_value, config_type, description)
SELECT 'sync.default_interval', '5', 'number', 'Default sync interval in minutes'
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'sync.default_interval');

INSERT INTO system_config (config_key, config_value, config_type, description)
SELECT 'storage.max_upload_size_mb', '100', 'number', 'Maximum file upload size in MB'
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'storage.max_upload_size_mb');

INSERT INTO system_config (config_key, config_value, config_type, description)
SELECT 'ui.default_theme', '"light"', 'string', 'Default UI theme'
WHERE NOT EXISTS (SELECT 1 FROM system_config WHERE config_key = 'ui.default_theme');

-- Insert default system tables
INSERT INTO table_metadata (table_name, display_name, table_type, sync_to_zoho, schema_definition)
SELECT 'users', 'Users', 'system', false, '{"columns": [], "description": "System users table"}'
WHERE NOT EXISTS (SELECT 1 FROM table_metadata WHERE table_name = 'users');

INSERT INTO table_metadata (table_name, display_name, table_type, sync_to_zoho, schema_definition)
SELECT 'table_metadata', 'Table Metadata', 'system', false, '{"columns": [], "description": "Table metadata registry"}'
WHERE NOT EXISTS (SELECT 1 FROM table_metadata WHERE table_name = 'table_metadata');

INSERT INTO table_metadata (table_name, display_name, table_type, sync_to_zoho, schema_definition)
SELECT 'sync_requests', 'Sync Requests', 'system', false, '{"columns": [], "description": "Sync request queue"}'
WHERE NOT EXISTS (SELECT 1 FROM table_metadata WHERE table_name = 'sync_requests');

-- Grant admin user full permissions on all tables
INSERT INTO table_permissions (table_name, user_id, permission_type, can_read, can_write, can_delete, can_manage)
SELECT tm.table_name, u.id, 'owner', true, true, true, true
FROM table_metadata tm
CROSS JOIN users u
WHERE u.email = 'admin@zoho-platform.com'
AND NOT EXISTS (
    SELECT 1 FROM table_permissions tp 
    WHERE tp.table_name = tm.table_name 
    AND tp.user_id = u.id
);

-- ============================================
-- MIGRATION: RESTORE CONSTRAINTS
-- ============================================

-- Re-enable foreign key constraints
ALTER TABLE sync_requests 
ADD CONSTRAINT sync_requests_table_name_fkey 
FOREIGN KEY (table_name) REFERENCES table_metadata(table_name);

ALTER TABLE sync_requests 
ADD CONSTRAINT sync_requests_user_id_fkey 
FOREIGN KEY (user_id) REFERENCES users(id);

-- ============================================
-- MIGRATION: CLEANUP BACKUP TABLES
-- ============================================

-- Optional: Drop backup tables after verification
-- DROP TABLE IF EXISTS backup_users;
-- DROP TABLE IF EXISTS backup_table_metadata;
-- DROP TABLE IF EXISTS backup_sync_requests;

-- ============================================
-- MIGRATION COMPLETE
-- ============================================

SELECT 'Migration completed successfully!' as migration_status,
       (SELECT COUNT(*) FROM users) as total_users,
       (SELECT COUNT(*) FROM table_metadata) as total_tables,
       (SELECT COUNT(*) FROM system_config) as total_configs;