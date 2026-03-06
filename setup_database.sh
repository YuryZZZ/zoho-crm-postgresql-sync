#!/bin/bash
# Setup script for Zoho CRM Dashboard - Full Implementation
# Run this after code deployment to set up database schemas

echo "========================================"
echo "Zoho CRM Dashboard - Database Setup"
echo "========================================"

# Database connection (update these values)
DB_HOST="34.78.66.32"
DB_PORT="5432"
DB_NAME="zoho_crm_digital_twin"
DB_USER="zoho_admin"
DB_PASSWORD="${DB_PASSWORD:-SecurePostgresPass123!}"

echo ""
echo "Step 1: Creating reference_data schema..."
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f sql/create_reference_schema.sql

echo ""
echo "Step 2: Creating upload_jobs table..."
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f sql/create_upload_jobs_table.sql

echo ""
echo "Step 3: Verifying tables..."
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c "
SELECT schemaname, tablename 
FROM pg_tables 
WHERE schemaname = 'reference_data' 
   OR tablename = 'upload_jobs'
ORDER BY schemaname, tablename;
"

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Configured modules:"
python3 -c "from module_config import get_all_modules; modules = get_all_modules(); print(f'  Total: {len(modules)} modules'); [print(f'    - {name}') for name in modules.keys()]"
echo ""
echo "Next steps:"
echo "  1. Deploy to Cloud Run: cd web_dashboard && ./deploy.sh"
echo "  2. Access dashboard at: https://zoho-crm-dashboard-699552818896.europe-west1.run.app"
echo "  3. Test sync with: python bulk_sync_final.py"
