-- ============================================================================
-- ADD REAL CUSTOM MODULES (Based on actual Zoho CRM data)
-- Removes Project_Leads (non-existent) and adds Client_Leads, Projects_Tender, Projects_Contracts
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- REMOVE OBSOLETE MODULE: Project_Leads
-- ============================================================================

-- Drop table if exists (custom module not in CRM)
DROP TABLE IF EXISTS project_leads CASCADE;

-- Remove from modules_metadata
DELETE FROM modules_metadata WHERE module_name = 'Project_Leads';

-- ============================================================================
-- CUSTOM MODULES: Create tables for actual CRM custom modules
-- ============================================================================

-- Client_Leads Table (Custom Module)
CREATE TABLE IF NOT EXISTS client_leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    name VARCHAR(255),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_client_leads_zoho_id ON client_leads(zoho_id);
CREATE INDEX IF NOT EXISTS idx_client_leads_sync_status ON client_leads(sync_status);

-- Projects_Tender Table (Custom Module)
CREATE TABLE IF NOT EXISTS projects_tender (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    name VARCHAR(255),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_projects_tender_zoho_id ON projects_tender(zoho_id);
CREATE INDEX IF NOT EXISTS idx_projects_tender_sync_status ON projects_tender(sync_status);

-- Projects_Contracts Table (Custom Module)
CREATE TABLE IF NOT EXISTS projects_contracts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    name VARCHAR(255),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_projects_contracts_zoho_id ON projects_contracts(zoho_id);
CREATE INDEX IF NOT EXISTS idx_projects_contracts_sync_status ON projects_contracts(sync_status);

-- ============================================================================
-- UPDATE MODULES METADATA
-- ============================================================================

INSERT INTO modules_metadata (module_name, api_name, singular_label, plural_label, fields, custom_fields)
VALUES 
    ('Client_Leads', 'client_leads', 'Client Lead', 'Client Leads', '[]'::jsonb, '[]'::jsonb),
    ('Projects_Tender', 'projects_tender', 'Projects Tender', 'Projects Tender', '[]'::jsonb, '[]'::jsonb),
    ('Projects_Contracts', 'projects_contracts', 'Projects Contract', 'Projects Contracts', '[]'::jsonb, '[]'::jsonb)
ON CONFLICT (module_name) DO UPDATE SET
    updated_at = CURRENT_TIMESTAMP;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

SELECT 'Migration Complete' as status,
       (SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('client_leads', 'projects_tender', 'projects_contracts')) as new_tables_created,
       (SELECT COUNT(*) FROM modules_metadata WHERE module_name IN ('Client_Leads', 'Projects_Tender', 'Projects_Contracts')) as modules_registered;