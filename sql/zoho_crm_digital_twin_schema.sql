-- ZOHO CRM DIGITAL TWIN - POSTGRESQL SCHEMA
-- Complete bidirectional sync database schema
-- Generated: 2026-01-15

-- ====================
-- DATABASE SETUP
-- ====================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ====================
-- CORE TABLES (Zoho CRM Modules)
-- ====================

-- Leads Table
CREATE TABLE leads (
    -- System Fields
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending' CHECK (sync_status IN ('pending', 'synced', 'modified', 'conflict', 'error')),
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    -- Zoho CRM Fields (Standard Lead Fields)
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    lead_source VARCHAR(100),
    company VARCHAR(255),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(255) GENERATED ALWAYS AS (COALESCE(first_name || ' ' || last_name, first_name, last_name)) STORED,
    title VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    mobile VARCHAR(50),
    fax VARCHAR(50),
    website VARCHAR(255),
    industry VARCHAR(100),
    annual_revenue DECIMAL(15,2),
    number_of_employees INTEGER,
    email_opt_out BOOLEAN DEFAULT false,
    description TEXT,
    
    -- Address Fields
    street VARCHAR(500),
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    country VARCHAR(100),
    
    -- Status Fields
    lead_status VARCHAR(50),
    rating VARCHAR(50),
    converted BOOLEAN DEFAULT false,
    converted_date TIMESTAMP WITH TIME ZONE,
    converted_account_id VARCHAR(100),
    converted_contact_id VARCHAR(100),
    converted_deal_id VARCHAR(100),
    
    -- Custom Fields (JSONB for flexibility)
    custom_fields JSONB DEFAULT '{}',
    
    -- Sync Metadata
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100),
    
    -- Indexes
    CONSTRAINT leads_email_unique UNIQUE NULLS NOT DISTINCT (email),
    CONSTRAINT leads_phone_unique UNIQUE NULLS NOT DISTINCT (phone)
);

-- Contacts Table
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    -- Contact Fields
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    account_id VARCHAR(100),
    account_name VARCHAR(255),
    lead_source VARCHAR(100),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(255) GENERATED ALWAYS AS (COALESCE(first_name || ' ' || last_name, first_name, last_name)) STORED,
    title VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    mobile VARCHAR(50),
    fax VARCHAR(50),
    department VARCHAR(100),
    assistant VARCHAR(100),
    assistant_phone VARCHAR(50),
    reports_to VARCHAR(100),
    email_opt_out BOOLEAN DEFAULT false,
    description TEXT,
    
    -- Address
    mailing_street VARCHAR(500),
    mailing_city VARCHAR(100),
    mailing_state VARCHAR(100),
    mailing_zip VARCHAR(20),
    mailing_country VARCHAR(100),
    
    other_street VARCHAR(500),
    other_city VARCHAR(100),
    other_state VARCHAR(100),
    other_zip VARCHAR(20),
    other_country VARCHAR(100),
    
    -- Status
    contact_type VARCHAR(50),
    date_of_birth DATE,
    skype_id VARCHAR(100),
    twitter VARCHAR(100),
    linkedin VARCHAR(255),
    
    -- Custom Fields
    custom_fields JSONB DEFAULT '{}',
    
    -- Sync Metadata
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100),
    
    -- Indexes
    CONSTRAINT contacts_email_unique UNIQUE NULLS NOT DISTINCT (email)
);

-- Accounts Table
CREATE TABLE accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    -- Account Fields
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    account_name VARCHAR(255) NOT NULL,
    account_number VARCHAR(100),
    account_type VARCHAR(100),
    industry VARCHAR(100),
    annual_revenue DECIMAL(15,2),
    rating VARCHAR(50),
    phone VARCHAR(50),
    fax VARCHAR(50),
    website VARCHAR(255),
    ticker_symbol VARCHAR(50),
    ownership VARCHAR(100),
    employees INTEGER,
    sic_code VARCHAR(50),
    parent_account_id VARCHAR(100),
    parent_account_name VARCHAR(255),
    email_opt_out BOOLEAN DEFAULT false,
    description TEXT,
    
    -- Address
    billing_street VARCHAR(500),
    billing_city VARCHAR(100),
    billing_state VARCHAR(100),
    billing_zip VARCHAR(20),
    billing_country VARCHAR(100),
    
    shipping_street VARCHAR(500),
    shipping_city VARCHAR(100),
    shipping_state VARCHAR(100),
    shipping_zip VARCHAR(20),
    shipping_country VARCHAR(100),
    
    -- Custom Fields
    custom_fields JSONB DEFAULT '{}',
    
    -- Sync Metadata
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

-- Deals Table
CREATE TABLE deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    -- Deal Fields
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    deal_name VARCHAR(255) NOT NULL,
    account_id VARCHAR(100),
    account_name VARCHAR(255),
    contact_id VARCHAR(100),
    contact_name VARCHAR(255),
    pipeline VARCHAR(100),
    stage VARCHAR(100),
    amount DECIMAL(15,2),
    currency_code VARCHAR(10) DEFAULT 'USD',
    expected_revenue DECIMAL(15,2),
    probability DECIMAL(5,2) CHECK (probability >= 0 AND probability <= 100),
    close_date DATE,
    type VARCHAR(100),
    lead_source VARCHAR(100),
    next_step VARCHAR(500),
    description TEXT,
    
    -- Custom Fields
    custom_fields JSONB DEFAULT '{}',
    
    -- Sync Metadata
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

-- Tasks Table
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    -- Task Fields
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    subject VARCHAR(500) NOT NULL,
    due_date TIMESTAMP WITH TIME ZONE,
    status VARCHAR(50),
    priority VARCHAR(50),
    send_notification_email BOOLEAN DEFAULT false,
    description TEXT,
    recurrence_activity VARCHAR(100),
    reminder VARCHAR(100),
    
    -- Related Records
    related_to_module VARCHAR(100),
    related_to_id VARCHAR(100),
    related_to_name VARCHAR(255),
    
    -- Custom Fields
    custom_fields JSONB DEFAULT '{}',
    
    -- Sync Metadata
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

-- Events Table
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    -- Event Fields
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    subject VARCHAR(500) NOT NULL,
    start_datetime TIMESTAMP WITH TIME ZONE,
    end_datetime TIMESTAMP WITH TIME ZONE,
    venue VARCHAR(500),
    all_day BOOLEAN DEFAULT false,
    description TEXT,
    recurrence_activity VARCHAR(100),
    reminder VARCHAR(100),
    
    -- Participants
    participants JSONB DEFAULT '[]',
    
    -- Related Records
    related_to_module VARCHAR(100),
    related_to_id VARCHAR(100),
    related_to_name VARCHAR(255),
    
    -- Custom Fields
    custom_fields JSONB DEFAULT '{}',
    
    -- Sync Metadata
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

-- ====================
-- SUPPORTING TABLES
-- ====================

-- Users Table (from Zoho CRM)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    full_name VARCHAR(255),
    role VARCHAR(100),
    profile VARCHAR(100),
    status VARCHAR(50),
    phone VARCHAR(50),
    mobile VARCHAR(50),
    country VARCHAR(100),
    language VARCHAR(50),
    timezone VARCHAR(100),
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Modules Metadata Table
CREATE TABLE modules_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    module_name VARCHAR(100) UNIQUE NOT NULL,
    api_name VARCHAR(100) UNIQUE NOT NULL,
    singular_label VARCHAR(100),
    plural_label VARCHAR(100),
    fields JSONB DEFAULT '[]',
    custom_fields JSONB DEFAULT '[]',
    last_sync_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ====================
-- SYNC MANAGEMENT TABLES
-- ====================

-- Sync Jobs Table
CREATE TABLE sync_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type VARCHAR(50) NOT NULL CHECK (job_type IN ('full_sync', 'incremental_sync', 'module_sync', 'record_sync')),
    module_name VARCHAR(100),
    status VARCHAR(50) NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    direction VARCHAR(20) CHECK (direction IN ('pull', 'push', 'bidirectional')),
    
    -- Statistics
    total_records INTEGER DEFAULT 0,
    processed_records INTEGER DEFAULT 0,
    created_records INTEGER DEFAULT 0,
    updated_records INTEGER DEFAULT 0,
    deleted_records INTEGER DEFAULT 0,
    failed_records INTEGER DEFAULT 0,
    
    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    
    -- Error Handling
    error_message TEXT,
    error_details JSONB,
    retry_count INTEGER DEFAULT 0,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Sync Log Table
CREATE TABLE sync_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID REFERENCES sync_jobs(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(20) CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical')),
    module_name VARCHAR(100),
    record_id VARCHAR(100),
    record_type VARCHAR(100),
    action VARCHAR(50) CHECK (action IN ('create', 'update', 'delete', 'skip', 'error')),
    message TEXT,
    details JSONB
);

-- Change Detection Table
CREATE TABLE changes_detected (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL,
    record_id UUID NOT NULL,
    zoho_id VARCHAR(100),
    change_type VARCHAR(20) CHECK (change_type IN ('created', 'updated', 'deleted')),
    change_source VARCHAR(20) CHECK (change_source IN ('zoho', 'postgres', 'system')),
    old_values JSONB,
    new_values JSONB,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE,
    processing_status VARCHAR(20) DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'synced', 'conflict', 'error')),
    conflict_resolution VARCHAR(50),
    sync_job_id UUID REFERENCES sync_jobs(id)
);

-- Conflict Resolution Table
CREATE TABLE conflicts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    table_name VARCHAR(100) NOT NULL,
    record_id UUID NOT NULL,
    zoho_id VARCHAR(100),
    conflict_type VARCHAR(50) CHECK (conflict_type IN ('data_mismatch', 'deletion_conflict', 'creation_conflict', 'timestamp_conflict')),
    zoho_data JSONB,
    postgres_data JSONB,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    postgres_modified_time TIMESTAMP WITH TIME ZONE,
    detected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution VARCHAR(50) CHECK (resolution IN ('zoho_wins', 'postgres_wins', 'merged', 'manual', 'skipped')),
    resolved_by VARCHAR(100),
    resolution_notes TEXT
);

-- ====================
-- AUDIT TABLES
-- ====================

-- Audit Trail Table
CREATE TABLE audit_trail (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    user_id VARCHAR(100),
    user_email VARCHAR(255),
    action VARCHAR(50) NOT NULL,
    table_name VARCHAR(100),
    record_id UUID,
    zoho_id VARCHAR(100),
    old_values JSONB,
    new_values JSONB,
    ip_address INET,
    user_agent TEXT,
    request_id VARCHAR(100)
);

-- API Call Log Table
CREATE TABLE api_call_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    api_endpoint VARCHAR(500),
    http_method VARCHAR(10),
    status_code INTEGER,
    response_time_ms INTEGER,
    request_size_bytes INTEGER,
    response_size_bytes INTEGER,
    success BOOLEAN,
    error_message TEXT,
    sync_job_id UUID REFERENCES sync_jobs(id)
);

-- ====================
-- INDEXES
-- ====================

-- Leads Indexes
CREATE INDEX idx_leads_zoho_id ON leads(zoho_id);
CREATE INDEX idx_leads_email ON leads(email);
CREATE INDEX idx_leads_company ON leads(company);
CREATE INDEX idx_leads_sync_status ON leads(sync_status);
CREATE INDEX idx_leads_updated_at ON leads(updated_at);
CREATE INDEX idx_leads_zoho_modified_time ON leads(zoho_modified_time);

-- Contacts Indexes
CREATE INDEX idx_contacts_zoho_id ON contacts(zoho_id);
CREATE INDEX idx_contacts_email ON contacts(email);
CREATE INDEX idx_contacts_account_id ON contacts(account_id);
CREATE INDEX idx_contacts_sync_status ON contacts(sync_status);

-- Accounts Indexes
CREATE INDEX idx_accounts_zoho_id ON accounts(zoho_id);
CREATE INDEX idx_accounts_account_name ON accounts(account_name);
CREATE INDEX idx_accounts_sync_status ON accounts(sync_status);

-- Deals Indexes
CREATE INDEX idx_deals_zoho_id ON deals(zoho_id);
CREATE INDEX idx_deals_account_id ON deals(account_id);
CREATE INDEX idx_deals_stage ON deals(stage);
CREATE INDEX idx_deals_sync_status ON deals(sync_status);

-- Tasks Indexes
CREATE INDEX idx_tasks_zoho_id ON tasks(zoho_id);
CREATE INDEX idx_tasks_related_to ON tasks(related_to_id);
CREATE INDEX idx_tasks_due_date ON tasks(due_date);
CREATE INDEX idx_tasks_sync_status ON tasks(sync_status);

-- Events Indexes
CREATE INDEX idx_events_zoho_id ON events(zoho_id);
CREATE INDEX idx_events_start_datetime ON events(start_datetime);
CREATE INDEX idx_events_sync_status ON events(sync_status);

-- Sync Management Indexes
CREATE INDEX idx_sync_jobs_status ON sync_jobs(status);
CREATE INDEX idx_sync_jobs_created_at ON sync_jobs(created_at);
CREATE INDEX idx_changes_detected_status ON changes_detected(processing_status);
CREATE INDEX idx_changes_detected_detected_at ON changes_detected(detected_at);
CREATE INDEX idx_conflicts_resolved_at ON conflicts(resolved_at) WHERE resolved_at IS NULL;

-- ====================
-- FUNCTIONS & TRIGGERS
-- ====================

-- Update updated_at timestamp trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply triggers to all main tables
CREATE TRIGGER update_leads_updated_at BEFORE UPDATE ON leads FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_contacts_updated_at BEFORE UPDATE ON contacts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_accounts_updated_at BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_deals_updated_at BEFORE UPDATE ON deals FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_tasks_updated_at BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_events_updated_at BEFORE UPDATE ON events FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Change detection trigger function
CREATE OR REPLACE FUNCTION detect_changes()
RETURNS TRIGGER AS $$
DECLARE
    old_json JSONB;
    new_json JSONB;
    change_source VARCHAR(20);
BEGIN
    -- Determine change source
    IF TG_OP = 'INSERT' THEN
        change_source := 'postgres';
        old_json := '{}';
        new_json := to_jsonb(NEW);
    ELSIF TG_OP = 'UPDATE' THEN
        change_source := 'postgres';
        old_json := to_jsonb(OLD);
        new_json := to_jsonb(NEW);
    ELSIF TG_OP = 'DELETE' THEN
        change_source := 'postgres';
        old_json := to_jsonb(OLD);
        new_json := '{}';
    END IF;
    
    -- Insert into changes_detected table
    INSERT INTO changes_detected (
        table_name,
        record_id,
        zoho_id,
        change_type,
        change_source,
        old_values,
        new_values
    ) VALUES (
        TG_TABLE_NAME,
        CASE 
            WHEN TG_OP = 'DELETE' THEN OLD.id
            ELSE NEW.id
        END,
        CASE 
            WHEN TG_OP = 'DELETE' THEN OLD.zoho_id
            ELSE NEW.zoho_id
        END,
        TG_OP,
        change_source,
        old_json,
        new_json
    );
    
    RETURN NULL;
END;
$$ language 'plpgsql';

-- Apply change detection triggers (exclude sync management tables)
CREATE TRIGGER detect_leads_changes AFTER INSERT OR UPDATE OR DELETE ON leads FOR EACH ROW EXECUTE FUNCTION detect_changes();
CREATE TRIGGER detect_contacts_changes AFTER INSERT OR UPDATE OR DELETE ON contacts FOR EACH ROW EXECUTE FUNCTION detect_changes();
CREATE TRIGGER detect_accounts_changes AFTER INSERT OR UPDATE OR DELETE ON accounts FOR EACH ROW EXECUTE FUNCTION detect_changes();
CREATE TRIGGER detect_deals_changes AFTER INSERT OR UPDATE OR DELETE ON deals FOR EACH ROW EXECUTE FUNCTION detect_changes();
CREATE TRIGGER detect_tasks_changes AFTER INSERT OR UPDATE OR DELETE ON tasks FOR EACH ROW EXECUTE FUNCTION detect_changes();
CREATE TRIGGER detect_events_changes AFTER INSERT OR UPDATE OR DELETE ON events FOR EACH ROW EXECUTE FUNCTION detect_changes();

-- ====================
-- VIEWS
-- ====================

-- Sync Status View
CREATE VIEW sync_status_view AS
SELECT 
    'leads' as module_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN sync_status = 'synced' THEN 1 END) as synced_records,
    COUNT(CASE WHEN sync_status = 'modified' THEN 1 END) as modified_records,
    COUNT(CASE WHEN sync_status = 'conflict' THEN 1 END) as conflict_records,
    COUNT(CASE WHEN sync_status = 'error' THEN 1 END) as error_records,
    MAX(last_sync_at) as last_sync_time
FROM leads
UNION ALL
SELECT 
    'contacts' as module_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN sync_status = 'synced' THEN 1 END) as synced_records,
    COUNT(CASE WHEN sync_status = 'modified' THEN 1 END) as modified_records,
    COUNT(CASE WHEN sync_status = 'conflict' THEN 1 END) as conflict_records,
    COUNT(CASE WHEN sync_status = 'error' THEN 1 END) as error_records,
    MAX(last_sync_at) as last_sync_time
FROM contacts
UNION ALL
SELECT 
    'accounts' as module_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN sync_status = 'synced' THEN 1 END) as synced_records,
    COUNT(CASE WHEN sync_status = 'modified' THEN 1 END) as modified_records,
    COUNT(CASE WHEN sync_status = 'conflict' THEN 1 END) as conflict_records,
    COUNT(CASE WHEN sync_status = 'error' THEN 1 END) as error_records,
    MAX(last_sync_at) as last_sync_time
FROM accounts
UNION ALL
SELECT 
    'deals' as module_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN sync_status = 'synced' THEN 1 END) as synced_records,
    COUNT(CASE WHEN sync_status = 'modified' THEN 1 END) as modified_records,
    COUNT(CASE WHEN sync_status = 'conflict' THEN 1 END) as conflict_records,
    COUNT(CASE WHEN sync_status = 'error' THEN 1 END) as error_records,
    MAX(last_sync_at) as last_sync_time
FROM deals
UNION ALL
SELECT 
    'tasks' as module_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN sync_status = 'synced' THEN 1 END) as synced_records,
    COUNT(CASE WHEN sync_status = 'modified' THEN 1 END) as modified_records,
    COUNT(CASE WHEN sync_status = 'conflict' THEN 1 END) as conflict_records,
    COUNT(CASE WHEN sync_status = 'error' THEN 1 END) as error_records,
    MAX(last_sync_at) as last_sync_time
FROM tasks
UNION ALL
SELECT 
    'events' as module_name,
    COUNT(*) as total_records,
    COUNT(CASE WHEN sync_status = 'synced' THEN 1 END) as synced_records,
    COUNT(CASE WHEN sync_status = 'modified' THEN 1 END) as modified_records,
    COUNT(CASE WHEN sync_status = 'conflict' THEN 1 END) as conflict_records,
    COUNT(CASE WHEN sync_status = 'error' THEN 1 END) as error_records,
    MAX(last_sync_at) as last_sync_time
FROM events;

-- Recent Changes View
CREATE VIEW recent_changes_view AS
SELECT 
    cd.id,
    cd.table_name,
    cd.record_id,
    cd.zoho_id,
    cd.change_type,
    cd.change_source,
    cd.detected_at,
    cd.processing_status,
    j.status as sync_job_status
FROM changes_detected cd
LEFT JOIN sync_jobs j ON cd.sync_job_id = j.id
WHERE cd.detected_at > CURRENT_TIMESTAMP - INTERVAL '24 hours'
ORDER BY cd.detected_at DESC;

-- ====================
-- INITIAL DATA
-- ====================

-- Insert default sync job types
INSERT INTO sync_jobs (job_type, status, direction) VALUES 
('full_sync', 'completed', 'pull'),
('incremental_sync', 'pending', 'bidirectional')
ON CONFLICT DO NOTHING;

-- ====================
-- COMMENTS
-- ====================

COMMENT ON TABLE leads IS 'Zoho CRM Leads - Digital twin with bidirectional sync';
COMMENT ON TABLE contacts IS 'Zoho CRM Contacts - Digital twin with bidirectional sync';
COMMENT ON TABLE accounts IS 'Zoho CRM Accounts - Digital twin with bidirectional sync';
COMMENT ON TABLE deals IS 'Zoho CRM Deals - Digital twin with bidirectional sync';
COMMENT ON TABLE tasks IS 'Zoho CRM Tasks - Digital twin with bidirectional sync';
COMMENT ON TABLE events IS 'Zoho CRM Events - Digital twin with bidirectional sync';

COMMENT ON COLUMN leads.sync_status IS 'pending, synced, modified, conflict, error';
COMMENT ON COLUMN contacts.sync_status IS 'pending, synced, modified, conflict, error';
COMMENT ON COLUMN accounts.sync_status IS 'pending, synced, modified, conflict, error';
COMMENT ON COLUMN deals.sync_status IS 'pending, synced, modified, conflict, error';
COMMENT ON COLUMN tasks.sync_status IS 'pending, synced, modified, conflict, error';
COMMENT ON COLUMN events.sync_status IS 'pending, synced, modified, conflict, error';

COMMENT ON TABLE sync_jobs IS 'Tracks sync operations and their status';
COMMENT ON TABLE changes_detected IS 'Detects and tracks changes for sync processing';
COMMENT ON TABLE conflicts IS 'Records and resolves data conflicts between Zoho and PostgreSQL';

-- ====================
-- GRANTS (Example - adjust for your security model)
-- ====================

-- Example grants (run as superuser)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO zoho_sync_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO zoho_sync_user;