-- ============================================================================
-- COMPLETE ZOHO CRM DATABASE MIGRATION
-- Adds ALL missing tables including Project Leads custom module
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================================
-- STANDARD MODULES (Missing from current schema)
-- ============================================================================

-- Calls Table
CREATE TABLE IF NOT EXISTS calls (
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
    subject VARCHAR(500) NOT NULL,
    call_type VARCHAR(50),
    call_status VARCHAR(50),
    call_start_time TIMESTAMP WITH TIME ZONE,
    call_duration VARCHAR(50),
    call_purpose VARCHAR(255),
    description TEXT,
    
    related_to_module VARCHAR(100),
    related_to_id VARCHAR(100),
    related_to_name VARCHAR(255),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_calls_zoho_id ON calls(zoho_id);
CREATE INDEX IF NOT EXISTS idx_calls_sync_status ON calls(sync_status);
CREATE INDEX IF NOT EXISTS idx_calls_related_to ON calls(related_to_module, related_to_id);

-- Products Table
CREATE TABLE IF NOT EXISTS products (
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
    product_name VARCHAR(255) NOT NULL,
    product_code VARCHAR(100),
    product_category VARCHAR(100),
    manufacturer VARCHAR(255),
    unit_price DECIMAL(15,2),
    quantity_in_stock INTEGER,
    description TEXT,
    taxable BOOLEAN DEFAULT true,
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_products_zoho_id ON products(zoho_id);
CREATE INDEX IF NOT EXISTS idx_products_sync_status ON products(sync_status);

-- Quotes Table
CREATE TABLE IF NOT EXISTS quotes (
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
    quote_name VARCHAR(255) NOT NULL,
    account_id VARCHAR(100),
    account_name VARCHAR(255),
    contact_id VARCHAR(100),
    contact_name VARCHAR(255),
    deal_id VARCHAR(100),
    deal_name VARCHAR(255),
    stage VARCHAR(100),
    valid_till DATE,
    sub_total DECIMAL(15,2),
    discount DECIMAL(15,2),
    tax DECIMAL(15,2),
    grand_total DECIMAL(15,2),
    description TEXT,
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_quotes_zoho_id ON quotes(zoho_id);
CREATE INDEX IF NOT EXISTS idx_quotes_sync_status ON quotes(sync_status);
CREATE INDEX IF NOT EXISTS idx_quotes_account_id ON quotes(account_id);

-- Sales Orders Table
CREATE TABLE IF NOT EXISTS sales_orders (
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
    sales_order_name VARCHAR(255) NOT NULL,
    account_id VARCHAR(100),
    account_name VARCHAR(255),
    contact_id VARCHAR(100),
    contact_name VARCHAR(255),
    deal_id VARCHAR(100),
    deal_name VARCHAR(255),
    quote_id VARCHAR(100),
    subject VARCHAR(500),
    status VARCHAR(100),
    sub_total DECIMAL(15,2),
    discount DECIMAL(15,2),
    tax DECIMAL(15,2),
    grand_total DECIMAL(15,2),
    description TEXT,
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_sales_orders_zoho_id ON sales_orders(zoho_id);
CREATE INDEX IF NOT EXISTS idx_sales_orders_sync_status ON sales_orders(sync_status);

-- Purchase Orders Table
CREATE TABLE IF NOT EXISTS purchase_orders (
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
    purchase_order_name VARCHAR(255) NOT NULL,
    vendor_id VARCHAR(100),
    vendor_name VARCHAR(255),
    subject VARCHAR(500),
    status VARCHAR(100),
    sub_total DECIMAL(15,2),
    discount DECIMAL(15,2),
    tax DECIMAL(15,2),
    grand_total DECIMAL(15,2),
    description TEXT,
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_purchase_orders_zoho_id ON purchase_orders(zoho_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_sync_status ON purchase_orders(sync_status);

-- Invoices Table
CREATE TABLE IF NOT EXISTS invoices (
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
    invoice_name VARCHAR(255) NOT NULL,
    account_id VARCHAR(100),
    account_name VARCHAR(255),
    contact_id VARCHAR(100),
    contact_name VARCHAR(255),
    deal_id VARCHAR(100),
    deal_name VARCHAR(255),
    sales_order_id VARCHAR(100),
    subject VARCHAR(500),
    invoice_date DATE,
    due_date DATE,
    status VARCHAR(100),
    sub_total DECIMAL(15,2),
    discount DECIMAL(15,2),
    tax DECIMAL(15,2),
    grand_total DECIMAL(15,2),
    balance_due DECIMAL(15,2),
    description TEXT,
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_invoices_zoho_id ON invoices(zoho_id);
CREATE INDEX IF NOT EXISTS idx_invoices_sync_status ON invoices(sync_status);
CREATE INDEX IF NOT EXISTS idx_invoices_account_id ON invoices(account_id);

-- Campaigns Table
CREATE TABLE IF NOT EXISTS campaigns (
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
    campaign_name VARCHAR(255) NOT NULL,
    campaign_type VARCHAR(100),
    status VARCHAR(100),
    start_date DATE,
    end_date DATE,
    expected_revenue DECIMAL(15,2),
    actual_cost DECIMAL(15,2),
    expected_cost DECIMAL(15,2),
    num_leads INTEGER,
    num_contacts INTEGER,
    num_deals INTEGER,
    description TEXT,
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_campaigns_zoho_id ON campaigns(zoho_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_sync_status ON campaigns(sync_status);

-- Vendors Table
CREATE TABLE IF NOT EXISTS vendors (
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
    vendor_name VARCHAR(255) NOT NULL,
    vendor_type VARCHAR(100),
    phone VARCHAR(50),
    email VARCHAR(255),
    website VARCHAR(255),
    description TEXT,
    
    street VARCHAR(500),
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    country VARCHAR(100),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_vendors_zoho_id ON vendors(zoho_id);
CREATE INDEX IF NOT EXISTS idx_vendors_sync_status ON vendors(sync_status);

-- Price Books Table
CREATE TABLE IF NOT EXISTS price_books (
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
    price_book_name VARCHAR(255) NOT NULL,
    description TEXT,
    pricing_model VARCHAR(100),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_price_books_zoho_id ON price_books(zoho_id);
CREATE INDEX IF NOT EXISTS idx_price_books_sync_status ON price_books(sync_status);

-- Cases Table
CREATE TABLE IF NOT EXISTS cases (
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
    case_name VARCHAR(255) NOT NULL,
    account_id VARCHAR(100),
    account_name VARCHAR(255),
    contact_id VARCHAR(100),
    contact_name VARCHAR(255),
    case_number VARCHAR(100),
    status VARCHAR(100),
    priority VARCHAR(50),
    case_origin VARCHAR(100),
    case_type VARCHAR(100),
    subject VARCHAR(500),
    description TEXT,
    resolution TEXT,
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_cases_zoho_id ON cases(zoho_id);
CREATE INDEX IF NOT EXISTS idx_cases_sync_status ON cases(sync_status);

-- Solutions Table
CREATE TABLE IF NOT EXISTS solutions (
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
    solution_title VARCHAR(255) NOT NULL,
    question TEXT,
    answer TEXT,
    status VARCHAR(100),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_solutions_zoho_id ON solutions(zoho_id);
CREATE INDEX IF NOT EXISTS idx_solutions_sync_status ON solutions(sync_status);

-- Documents Table
CREATE TABLE IF NOT EXISTS documents (
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
    document_name VARCHAR(255) NOT NULL,
    document_type VARCHAR(100),
    file_name VARCHAR(255),
    file_size BIGINT,
    file_url TEXT,
    description TEXT,
    
    related_to_module VARCHAR(100),
    related_to_id VARCHAR(100),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_documents_zoho_id ON documents(zoho_id);
CREATE INDEX IF NOT EXISTS idx_documents_sync_status ON documents(sync_status);

-- Notes Table
CREATE TABLE IF NOT EXISTS notes (
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
    note_title VARCHAR(500),
    note_content TEXT,
    
    related_to_module VARCHAR(100),
    related_to_id VARCHAR(100),
    related_to_name VARCHAR(255),
    
    custom_fields JSONB DEFAULT '{}',
    
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_notes_zoho_id ON notes(zoho_id);
CREATE INDEX IF NOT EXISTS idx_notes_sync_status ON notes(sync_status);
CREATE INDEX IF NOT EXISTS idx_notes_related_to ON notes(related_to_module, related_to_id);

-- ============================================================================
-- CUSTOM MODULES
-- ============================================================================

-- Project Leads Table (Custom Module)
CREATE TABLE IF NOT EXISTS project_leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE,
    sync_status VARCHAR(20) DEFAULT 'pending',
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMP WITH TIME ZONE,
    
    -- Core Project Lead Fields
    owner_id VARCHAR(100),
    owner_name VARCHAR(255),
    project_lead_name VARCHAR(255) NOT NULL,
    
    -- Project Information
    project_name VARCHAR(255),
    project_type VARCHAR(100),
    project_status VARCHAR(100),
    project_priority VARCHAR(50),
    
    -- Dates
    start_date DATE,
    end_date DATE,
    expected_completion_date DATE,
    
    -- Financial
    budget DECIMAL(15,2),
    estimated_revenue DECIMAL(15,2),
    actual_cost DECIMAL(15,2),
    
    -- Lead Information
    lead_source VARCHAR(100),
    lead_status VARCHAR(100),
    lead_rating VARCHAR(50),
    
    -- Contact Information
    contact_id VARCHAR(100),
    contact_name VARCHAR(255),
    contact_email VARCHAR(255),
    contact_phone VARCHAR(50),
    
    -- Account Information
    account_id VARCHAR(100),
    account_name VARCHAR(255),
    
    -- Deal Association
    deal_id VARCHAR(100),
    deal_name VARCHAR(255),
    
    -- Description
    description TEXT,
    project_details TEXT,
    next_steps TEXT,
    
    -- Custom Fields (JSONB for flexibility)
    custom_fields JSONB DEFAULT '{}',
    
    -- Sync Metadata
    zoho_created_time TIMESTAMP WITH TIME ZONE,
    zoho_modified_time TIMESTAMP WITH TIME ZONE,
    zoho_created_by VARCHAR(100),
    zoho_modified_by VARCHAR(100)
);

-- Indexes for Project Leads
CREATE INDEX IF NOT EXISTS idx_project_leads_zoho_id ON project_leads(zoho_id);
CREATE INDEX IF NOT EXISTS idx_project_leads_sync_status ON project_leads(sync_status);
CREATE INDEX IF NOT EXISTS idx_project_leads_project_name ON project_leads(project_name);
CREATE INDEX IF NOT EXISTS idx_project_leads_lead_status ON project_leads(lead_status);
CREATE INDEX IF NOT EXISTS idx_project_leads_account_id ON project_leads(account_id);
CREATE INDEX IF NOT EXISTS idx_project_leads_deal_id ON project_leads(deal_id);
CREATE INDEX IF NOT EXISTS idx_project_leads_contact_id ON project_leads(contact_id);

-- ============================================================================
-- DYNAMIC TABLE CREATION FUNCTION
-- ============================================================================

CREATE OR REPLACE FUNCTION create_zoho_module_table(module_name VARCHAR)
RETURNS VOID AS $$
DECLARE
    table_name VARCHAR;
    create_sql TEXT;
BEGIN
    table_name := lower(regexp_replace(module_name, '[^a-zA-Z0-9_]', '_', 'g'));
    
    create_sql := format('
        CREATE TABLE IF NOT EXISTS %I (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            zoho_id VARCHAR(100) UNIQUE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP WITH TIME ZONE,
            sync_status VARCHAR(20) DEFAULT ''pending'',
            sync_version INTEGER DEFAULT 1,
            last_sync_at TIMESTAMP WITH TIME ZONE,
            
            owner_id VARCHAR(100),
            owner_name VARCHAR(255),
            name VARCHAR(255),
            
            custom_fields JSONB DEFAULT ''{}'',
            
            zoho_created_time TIMESTAMP WITH TIME ZONE,
            zoho_modified_time TIMESTAMP WITH TIME ZONE,
            zoho_created_by VARCHAR(100),
            zoho_modified_by VARCHAR(100)
        );
        
        CREATE INDEX IF NOT EXISTS idx_%s_zoho_id ON %I(zoho_id);
        CREATE INDEX IF NOT EXISTS idx_%s_sync_status ON %I(sync_status);
    ', table_name, table_name, table_name, table_name, table_name, table_name);
    
    EXECUTE create_sql;
    
    -- Register in modules metadata
    INSERT INTO modules_metadata (module_name, api_name, singular_label, plural_label)
    VALUES (module_name, table_name, module_name, module_name || 's')
    ON CONFLICT (module_name) DO UPDATE SET
        updated_at = CURRENT_TIMESTAMP;
        
    RAISE NOTICE 'Created table for module: %', module_name;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- UPDATE MODULES METADATA
-- ============================================================================

INSERT INTO modules_metadata (module_name, api_name, singular_label, plural_label, fields, custom_fields)
VALUES 
    ('Calls', 'calls', 'Call', 'Calls', '[]'::jsonb, '[]'::jsonb),
    ('Products', 'products', 'Product', 'Products', '[]'::jsonb, '[]'::jsonb),
    ('Quotes', 'quotes', 'Quote', 'Quotes', '[]'::jsonb, '[]'::jsonb),
    ('Sales_Orders', 'sales_orders', 'Sales Order', 'Sales Orders', '[]'::jsonb, '[]'::jsonb),
    ('Purchase_Orders', 'purchase_orders', 'Purchase Order', 'Purchase Orders', '[]'::jsonb, '[]'::jsonb),
    ('Invoices', 'invoices', 'Invoice', 'Invoices', '[]'::jsonb, '[]'::jsonb),
    ('Campaigns', 'campaigns', 'Campaign', 'Campaigns', '[]'::jsonb, '[]'::jsonb),
    ('Vendors', 'vendors', 'Vendor', 'Vendors', '[]'::jsonb, '[]'::jsonb),
    ('Price_Books', 'price_books', 'Price Book', 'Price Books', '[]'::jsonb, '[]'::jsonb),
    ('Cases', 'cases', 'Case', 'Cases', '[]'::jsonb, '[]'::jsonb),
    ('Solutions', 'solutions', 'Solution', 'Solutions', '[]'::jsonb, '[]'::jsonb),
    ('Documents', 'documents', 'Document', 'Documents', '[]'::jsonb, '[]'::jsonb),
    ('Notes', 'notes', 'Note', 'Notes', '[]'::jsonb, '[]'::jsonb),
    ('Project_Leads', 'project_leads', 'Project Lead', 'Project Leads', '[]'::jsonb, '[]'::jsonb)
ON CONFLICT (module_name) DO UPDATE SET
    updated_at = CURRENT_TIMESTAMP;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

SELECT 'Migration Complete' as status,
       (SELECT COUNT(*) FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('calls', 'products', 'quotes', 'sales_orders', 
                           'purchase_orders', 'invoices', 'campaigns', 
                           'vendors', 'price_books', 'cases', 'solutions', 
                           'documents', 'notes', 'project_leads')) as new_tables_created,
       (SELECT COUNT(*) FROM modules_metadata) as modules_registered;
