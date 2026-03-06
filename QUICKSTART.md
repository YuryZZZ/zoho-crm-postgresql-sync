# Zoho CRM → PostgreSQL Digital Twin — Quick Start

> **For LLMs and developers**: This is the complete reference for the Zoho CRM sync platform.

## What This Project Does

A production **Flask web dashboard** deployed on **Google Cloud Run** that:
1. **Syncs** 21 Zoho CRM modules (+ email tracking + visits) into a PostgreSQL database every 60 minutes
2. **Provides a web UI** with 9 tabs: Dashboard, Data Browser, Create Record, Upload Data, Enrich & Deduplicate, SQL Query, Table Manager, Sync Control, AI Chat
3. **Supports bidirectional sync** — push modified records back to Zoho CRM
4. **AI-powered chat** — ask questions about your CRM data using Gemini 2.5 Pro with SQL function calling

## Architecture

```
Zoho CRM (EU) ←→ Flask App (Cloud Run) ←→ PostgreSQL (Cloud SQL)
                        ↓                         ↓
                  Gemini 2.5 Pro          369,600+ records
                  (AI Chat/SQL)           21 CRM modules
                                          + email_tracking
                                          + visits
```

## Key Files

| File | Description |
|------|-------------|
| `web_dashboard/unified_app.py` | **Main application** (~5100 lines) — all endpoints, sync engine, AI chat |
| `web_dashboard/templates/unified_index.html` | **Single-page UI** — 9 tabs, all frontend |
| `web_dashboard/Dockerfile` | Container config (Python 3.11, gunicorn) |
| `web_dashboard/cloudbuild.yaml` | CI/CD pipeline — build, push, deploy to Cloud Run |
| `web_dashboard/requirements.txt` | Python dependencies |
| `module_config.py` | 21 Zoho CRM module definitions, table mappings, sync order |
| `sql/zoho_crm_digital_twin_schema.sql` | Full PostgreSQL schema |

## GCP Infrastructure

| Resource | Value |
|----------|-------|
| **Project** | `leadenrich-a2b9d` |
| **Cloud Run** | `zoho-crm-dashboard` (europe-west1) |
| **Cloud SQL** | `zoho-crm-postgres` (PostgreSQL 16) |
| **DB IP** | `35.189.239.211` |
| **DB Name** | `zoho_crm_digital_twin` |
| **DB User** | `zoho_admin` |
| **Execution** | gen2, 4GB RAM, 2 CPU, min 1 instance |

## Zoho Configuration

| Setting | Value |
|---------|-------|
| **Region** | EU (`zohoapis.eu`) |
| **Auth** | OAuth2 Self-Client |
| **Client ID** | `1000.2N4K7YII5U4CZU3X8P8KI296E5WT4L` |
| **Token URL** | `https://accounts.zoho.eu/oauth/v2/token` |
| **API Base** | `https://www.zohoapis.eu` |
| **Scopes** | modules.ALL, settings.ALL, users.ALL, org.ALL, bulk.ALL, coql.READ, files.CREATE, files.READ |

## Secrets (GCP Secret Manager)

| Secret Name | Usage |
|-------------|-------|
| `postgres-password` | DB password |
| `zoho-client-id` | OAuth client ID |
| `zoho-client-secret` | OAuth client secret |
| `zoho-crm-refresh-token` | OAuth refresh token |

## 21 Synced Modules

Leads, Contacts, Accounts, Deals, Tasks, Events, Calls, Notes, Products, Vendors, Quotes, Sales_Orders, Purchase_Orders, Invoices, Campaigns, Cases, Solutions, Price_Books, Visits, Client_Leads, Projects_Tender, Projects_Contracts

**Plus related lists**: `email_tracking` (COQL import from Leads+Contacts), `visits` (related list from Contacts)

## Deployment

```bash
# From the zoho-crm-sync/ root directory:
gcloud builds submit --config=web_dashboard/cloudbuild.yaml --project=leadenrich-a2b9d
```

The `cloudbuild.yaml` does:
1. Copies `module_config.py` into `web_dashboard/` build context
2. Builds Docker image
3. Pushes to Container Registry
4. Deploys to Cloud Run with env vars and secrets

## Auto-Sync

- **Enabled by default** (`AUTO_SYNC_ENABLED=true`)
- **Interval**: 60 minutes
- **How**: Background thread with `fcntl` file lock (single-worker safe)
- **Startup delay**: 60 seconds
- **Cycle**: Pull all 21 modules incrementally → import emails (COQL) → import visits
- **Lock timeout**: 30 minutes auto-reset for stale locks

## API Endpoints (54 total)

### Core
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Web dashboard |
| GET | `/healthz`, `/health` | Health check |
| GET | `/api/dashboard` | Dashboard stats + module counts |

### Data Browser
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/table/<table_name>` | Browse table (paginated, search, sort) |
| POST | `/api/record/<table_name>` | Create record |
| GET | `/api/record/<table_name>/<id>` | Get single record |
| PUT | `/api/record/<table_name>/<id>` | Update record (sets sync_status=modified) |
| DELETE | `/api/record/<table_name>/<id>` | Delete record |
| POST | `/api/bulk/<table_name>` | Bulk operations (delete, update) |
| GET | `/api/record/<table_name>/<id>/history` | Change history |
| GET | `/api/changes/recent` | Recent changes across all tables |
| GET | `/api/export/<table_name>` | Export table as CSV |

### Sync Control
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/sync/pull` | Pull all modules from Zoho |
| POST | `/api/sync/bulk-pull` | Pull with bulk API |
| POST | `/api/sync/push` | Push modified records to Zoho |
| POST | `/api/sync/push-preview` | Preview pending push records |
| POST | `/api/sync/push-module/<name>` | Push single module |
| POST | `/api/sync/full` | Full sync (pull + push) |
| GET | `/api/sync/status` | Current sync status |
| POST | `/api/sync/reset` | Reset stuck sync lock |
| GET/POST | `/api/sync/auto` | Get/set auto-sync settings |
| GET | `/api/sync/history` | Sync history log |
| POST | `/api/sync/import-visits` | Full visits import |
| POST | `/api/sync/import-emails` | Full email import |
| POST | `/api/sync/module/<name>` | Sync single module |

### SQL Query
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/query` | Execute read-only SQL (SELECT/WITH/EXPLAIN) |

### Table Manager
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tables` | List all tables with row counts |
| POST | `/api/tables/create` | Create new table |
| POST | `/api/tables/<name>/columns` | Add column to table |
| POST | `/api/tables/<name>/drop` | Drop table |
| POST | `/api/tables/<name>/truncate` | Truncate table |
| GET | `/api/stats/overview` | Statistics overview |

### Upload Data
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload/preview` | Preview CSV/Excel first 100 rows |
| POST | `/api/upload/import` | Start background import (returns job_id) |
| GET | `/api/upload/status/<job_id>` | Check upload job progress |
| GET | `/api/upload/jobs` | List all upload jobs |
| POST | `/api/upload/create-table` | Create table from upload schema |

### Enrich & Deduplicate
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/enrich/duplicates/<table>` | Find exact duplicates |
| GET | `/api/enrich/fuzzy-duplicates/<table>` | Fuzzy duplicate detection (pg_trgm) |
| GET | `/api/enrich/cross-module-duplicates` | Cross-module dedup (leads↔contacts↔accounts) |
| GET | `/api/enrich/completeness/<table>` | Field completeness analysis |
| GET | `/api/enrich/validate/<table>` | Data validation |
| GET | `/api/enrich/duplicates/<table>/detail` | Detailed duplicate groups |
| POST | `/api/enrich/convert` | Convert lead to contact |
| POST | `/api/enrich/merge` | Merge duplicate records |
| POST | `/api/enrich/bulk-update` | Bulk update records |

### Zoho API
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/zoho/modules` | List Zoho modules |
| GET | `/api/zoho/fields/<module>` | Get module fields |
| GET | `/api/zoho/test` | Test Zoho connection |
| GET | `/api/conflicts` | List sync conflicts |
| POST | `/api/conflicts/<id>/resolve` | Resolve conflict |

### AI Chat (Gemini 2.5 Pro)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat` | Send message (with function calling) |
| POST | `/api/chat/reset` | Reset chat session |
| GET | `/api/chat/status` | Check AI availability |

## Technical Details

### Database Schema Pattern
Every CRM table follows this pattern:
```sql
CREATE TABLE <module> (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    zoho_id VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    sync_status VARCHAR(20) DEFAULT 'pending',  -- pending/synced/modified/conflict/error
    sync_version INTEGER DEFAULT 1,
    last_sync_at TIMESTAMPTZ,
    -- Module-specific fields...
    custom_fields JSONB DEFAULT '{}',
    zoho_created_time TIMESTAMPTZ,
    zoho_modified_time TIMESTAMPTZ
);
```

### Sync Engine
- **Incremental pull**: Uses `Modified_Time` from Zoho API, only fetches changed records
- **Push to Zoho**: `pg_record_to_zoho()` maps DB fields → Zoho API fields, only standard mapped fields (not custom_fields blob)
- **Conflict detection**: Compares local vs remote `modified_time` before push
- **Email import**: COQL-based (`POST /crm/v2/coql`), cursor pagination on `Created_Time`/`Modified_Time`

### Upload System
- **Background processing**: Uploads return immediately with `job_id`, processing in thread
- **Chunked CSV streaming**: `pd.read_csv(chunksize=5000)`, never loads entire file to RAM
- **Bulk INSERT**: `psycopg2.extras.execute_values()` with page_size=2000 (50-100x faster)
- **New table creation**: Can create tables on-the-fly from CSV column detection

### Fuzzy Deduplication
- Uses `pg_trgm` extension with GIN indexes on `LOWER(TRIM(field))` expressions
- Exact dedup: `GROUP BY` normalized name (instant at any scale)
- Fuzzy dedup: LATERAL join with 500 samples × GIN index lookups (O(500 × index_scan), not O(N²))
- Handles 122K contacts in ~20 seconds

### AI Chat
- **Model**: Gemini 2.5 Pro via Vertex AI (ADC authentication)
- **Function calling**: 4 tools (execute_sql, list_tables, describe_table, create_table)
- **Session management**: In-memory per session_id
- **System prompt**: Includes full database schema context

### Gunicorn Config
- 1 worker, 16 threads, 900s timeout
- `min-instances=1` on Cloud Run (keeps background sync thread alive)
- gen2 execution environment (no 32MB body limit)

## Environment Variables

```
DB_HOST=35.189.239.211
DB_NAME=zoho_crm_digital_twin
DB_USER=zoho_admin
DB_PASSWORD=(from Secret Manager)
ZOHO_REGION=eu
ZOHO_API_BASE=https://www.zohoapis.eu
ZOHO_TOKEN_URL=https://accounts.zoho.eu/oauth/v2/token
ZOHO_CLIENT_ID=(from Secret Manager)
ZOHO_CLIENT_SECRET=(from Secret Manager)
ZOHO_REFRESH_TOKEN=(from Secret Manager)
AUTO_SYNC_ENABLED=true
AUTO_SYNC_INTERVAL_MINUTES=60
```
