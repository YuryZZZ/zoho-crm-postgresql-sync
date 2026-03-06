# Zoho CRM ↔ PostgreSQL Digital Twin

Full-featured bidirectional sync between Zoho CRM (EU) and PostgreSQL, with a 9-tab web dashboard, AI chat assistant (Gemini 2.5 Pro), data enrichment, and bulk upload capabilities — deployed on Google Cloud Run.

## Features

- **21 CRM modules** synced automatically every 60 minutes + email tracking + visits
- **369,600+ records** across 76 tables in PostgreSQL
- **Bidirectional sync** — pull from Zoho AND push modifications back
- **AI Chat** — ask questions about your CRM data (Gemini 2.5 Pro with SQL function calling)
- **Bulk upload** — CSV/Excel import with background processing, handles millions of rows
- **Data enrichment** — fuzzy deduplication, cross-module matching, data validation
- **54 API endpoints** — REST API for everything

## Dashboard Tabs

| Tab | Description |
|-----|-------------|
| **Dashboard** | Overview cards, module counts, sync status |
| **Data Browser** | Browse any table with search, sort, pagination, export |
| **Create Record** | Form-based record creation for any module |
| **Upload Data** | CSV/Excel import with column mapping and background processing |
| **Enrich & Deduplicate** | Fuzzy dedup, cross-module matching, data quality analysis |
| **SQL Query** | Read-only SQL console with quick query templates |
| **Table Manager** | Create, alter, drop, truncate database tables |
| **Sync Control** | Pull/push sync, per-module sync, auto-sync settings, history |
| **AI Chat** | Natural language queries via Gemini 2.5 Pro |

## Architecture

```
┌──────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│  Zoho CRM    │◄───►│  Cloud Run          │◄───►│  Cloud SQL       │
│  (EU Region) │     │  (unified_app.py)   │     │  PostgreSQL 16   │
│              │     │                     │     │                  │
│  21 modules  │     │  Flask + Gunicorn   │     │  369,600+ records│
│  + emails    │     │  Auto-sync thread   │     │  76 tables       │
│  + visits    │     │  AI Chat (Gemini)   │     │                  │
└──────────────┘     └─────────────────────┘     └──────────────────┘
```

## Quick Start

### Prerequisites
- Google Cloud account with billing enabled
- Zoho CRM account (EU region) with API access
- Python 3.11+

### Deploy

```bash
# Clone the repo
git clone https://github.com/YuryZZZ/zoho-crm-postgresql-sync.git
cd zoho-crm-postgresql-sync

# Set up GCP secrets (one-time)
gcloud secrets create postgres-password --data-file=- <<< "your-db-password"
gcloud secrets create zoho-client-id --data-file=- <<< "your-client-id"
gcloud secrets create zoho-client-secret --data-file=- <<< "your-client-secret"
gcloud secrets create zoho-crm-refresh-token --data-file=- <<< "your-refresh-token"

# Deploy to Cloud Run via Cloud Build
gcloud builds submit --config=web_dashboard/cloudbuild.yaml --project=YOUR_PROJECT_ID
```

### Local Development

```bash
cd web_dashboard
pip install -r requirements.txt

# Set environment variables
export DB_HOST=your-db-ip
export DB_NAME=zoho_crm_digital_twin
export DB_USER=zoho_admin
export DB_PASSWORD=your-password
export ZOHO_API_BASE=https://www.zohoapis.eu
export ZOHO_TOKEN_URL=https://accounts.zoho.eu/oauth/v2/token
export AUTO_SYNC_ENABLED=false

python unified_app.py
```

## Project Structure

```
zoho-crm-postgresql-sync/
├── module_config.py                    # 21 module definitions + sync order
├── sql/
│   └── zoho_crm_digital_twin_schema.sql  # Full DB schema
├── web_dashboard/
│   ├── unified_app.py                  # Main app (5100 lines, 54 endpoints)
│   ├── templates/
│   │   └── unified_index.html          # Single-page dashboard UI
│   ├── Dockerfile                      # Python 3.11 + gunicorn
│   ├── cloudbuild.yaml                 # GCP Cloud Build pipeline
│   └── requirements.txt               # Python dependencies
├── QUICKSTART.md                       # Full technical reference for LLMs
├── API_REFERENCE.md                    # All 54 API endpoints documented
└── README.md                           # This file
```

## Synced Modules (21)

**Core Sales:** Leads, Contacts, Accounts, Deals
**Activities:** Tasks, Events, Calls, Notes
**Inventory:** Products, Vendors, Price_Books
**Sales Docs:** Quotes, Sales_Orders, Purchase_Orders, Invoices
**Marketing:** Campaigns
**Support:** Cases, Solutions
**SalesIQ:** Visits
**Custom:** Client_Leads, Projects_Tender, Projects_Contracts

**Plus:** Email tracking (COQL import) and Visits related list

## API Highlights

| Category | Endpoints | Key Route |
|----------|-----------|-----------|
| Dashboard | 3 | `GET /api/dashboard` |
| Data CRUD | 9 | `GET/POST/PUT/DELETE /api/record/<table>/<id>` |
| Sync Control | 13 | `POST /api/sync/pull`, `/push`, `/module/<name>` |
| SQL Query | 1 | `POST /api/query` |
| Table Mgmt | 5 | `GET /api/tables`, `POST /api/tables/create` |
| Upload | 5 | `POST /api/upload/import` (background) |
| Enrichment | 11 | `GET /api/enrich/fuzzy-duplicates/<table>` |
| Zoho Proxy | 5 | `GET /api/zoho/test`, `/modules`, `/fields/<mod>` |
| AI Chat | 3 | `POST /api/chat` (Gemini 2.5 Pro) |

Full API docs: [API_REFERENCE.md](API_REFERENCE.md)

## Tech Stack

- **Backend:** Python 3.11, Flask, psycopg2, pandas
- **Database:** PostgreSQL 16 (Cloud SQL) with pg_trgm, uuid-ossp
- **AI:** Gemini 2.5 Pro via Vertex AI (google-genai SDK)
- **Hosting:** Google Cloud Run (gen2, 4GB RAM, 2 CPU)
- **CI/CD:** Google Cloud Build
- **Zoho API:** OAuth2 Self-Client, REST API v2, COQL

## Key Technical Details

- **Auto-sync**: Background thread with file lock, 60-min interval, 30-min stale lock reset
- **Bulk uploads**: Chunked CSV streaming (5000 rows/chunk) + `execute_values` bulk INSERT
- **Fuzzy dedup**: pg_trgm GIN indexes + LATERAL join pattern (122K records in ~20s)
- **AI Chat**: 4 function-calling tools (execute_sql, list_tables, describe_table, create_table)
- **Gunicorn**: 1 worker, 16 threads, 900s timeout, min-instances=1

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DB_HOST` | PostgreSQL host IP |
| `DB_NAME` | Database name |
| `DB_USER` | Database user |
| `DB_PASSWORD` | From Secret Manager |
| `ZOHO_API_BASE` | Zoho API base URL |
| `ZOHO_TOKEN_URL` | Zoho OAuth token URL |
| `ZOHO_CLIENT_ID` | From Secret Manager |
| `ZOHO_CLIENT_SECRET` | From Secret Manager |
| `ZOHO_REFRESH_TOKEN` | From Secret Manager |
| `AUTO_SYNC_ENABLED` | Enable auto-sync (true/false) |
| `AUTO_SYNC_INTERVAL_MINUTES` | Sync interval |

## Troubleshooting

- **Zoho connected: false** → Check refresh token expiry, verify OAuth scopes
- **Sync stuck** → `POST /api/sync/reset` or wait for 30-min auto-reset
- **Upload timeout** → Uploads run in background; check `GET /api/upload/status/<job_id>`
- **AI chat unavailable** → Ensure `google-genai` installed and Vertex AI API enabled
- **View logs**: `gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=zoho-crm-dashboard" --limit=50`

## License

MIT

---

**Status**: Production | **Records**: 369,600+ | **Last Deploy**: 2026-03-06
