# Zoho CRM <-> PostgreSQL Digital Twin — Project Rules

## Quick Context
- **Main app**: `web_dashboard/unified_app.py` (5099 lines, 55 Flask routes)
- **UI**: `web_dashboard/templates/unified_index.html` (2016 lines, single-page, 9 tabs)
- **Config**: `module_config.py` (22 modules incl Visits)
- **Live**: https://zoho-crm-dashboard-30591337479.europe-west1.run.app
- **Repo**: https://github.com/YuryZZZ/zoho-crm-postgresql-sync
- **GCP Project**: `leadenrich-a2b9d` (NOT legalai-480809)

## Deployment
```bash
# ALWAYS deploy from zoho-crm-sync/ root:
gcloud builds submit --config=web_dashboard/cloudbuild.yaml --project=leadenrich-a2b9d
```

## Development Rules
- **DO NOT** use legalai-480809 project for anything Zoho-related
- **DO NOT** run locally — everything runs on Cloud Run / Cloud SQL
- **DO NOT** create new Python files — all backend goes in `unified_app.py`
- **DO NOT** create new HTML files — all UI goes in `unified_index.html`
- **DO** use `execute_values` for bulk inserts (never row-by-row)
- **DO** use plain dicts for Gemini chat content (never genai_types objects)
- **DO** use LATERAL joins for fuzzy dedup (never self-joins)
- **DO** put GIN indexes on expressions `LOWER(TRIM(field))`, not raw columns

## DB Connection
- Host: `35.189.239.211` (set via DB_HOST env var, not hardcoded default)
- Database: `zoho_crm_digital_twin`
- User: `zoho_admin`
- Password: from Secret Manager `postgres-password`

## Zoho API
- Region: EU — always use `zohoapis.eu` (not `.com`)
- Token URL: `https://accounts.zoho.eu/oauth/v2/token`
- API Base: `https://www.zohoapis.eu`
- Client ID: `1000.2N4K7YII5U4CZU3X8P8KI296E5WT4L`

## Testing After Changes
```bash
# Health check
curl https://zoho-crm-dashboard-30591337479.europe-west1.run.app/healthz

# Dashboard stats
curl https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/dashboard

# AI chat status
curl https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/chat/status

# Sync status
curl https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/status
```

## Code Patterns
- Every new endpoint: add `@app.route()` in unified_app.py before the `# Run` section
- Every new tab: add tab button + panel div in unified_index.html
- Background jobs: use `threading.Thread(daemon=True)` with job_id tracking dict
- DB queries: always use `get_db()` context, `RealDictCursor`, and proper error handling
- Zoho API calls: always use `_get_zoho_headers()` which auto-refreshes tokens
