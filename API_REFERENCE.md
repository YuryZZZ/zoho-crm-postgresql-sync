# API Reference -- Zoho CRM Dashboard

Base URL: `https://zoho-crm-dashboard-30591337479.europe-west1.run.app`

**Total endpoints: 74**

## Dashboard & Health

### `GET /`
Returns the web dashboard HTML page.

### `GET /healthz` / `GET /health`
Health check endpoint.
**Response:** `{"status": "healthy"}`

### `GET /api/dashboard`
Dashboard stats: total records, module counts, Zoho connection status, sync state.
**Response:**
```json
{
  "total_records": 654333,
  "total_tables": 87,
  "zoho_connected": true,
  "auto_sync_enabled": true,
  "modules": [{"module": "Leads", "table": "leads", "count": 9194}, ...]
}
```

---

## Data Browser

### `GET /api/table/<table_name>`
Paginated table browser with search, sort, and filtering.
**Query params:** `page` (default 1), `per_page` (default 50), `search`, `sort_by`, `sort_dir` (asc/desc), `filters` (JSON)

### `POST /api/record/<table_name>`
Create a new record.
**Body:** `{"field1": "value1", "field2": "value2"}`

### `GET /api/record/<table_name>/<record_id>`
Get a single record by UUID or zoho_id.

### `PUT /api/record/<table_name>/<record_id>`
Update a record. Automatically sets `sync_status=modified` for push-back to Zoho.
**Body:** `{"field1": "new_value"}`

### `DELETE /api/record/<table_name>/<record_id>`
Soft-delete a record (sets `deleted_at`).

### `POST /api/bulk/<table_name>`
Bulk operations on multiple records.
**Body:** `{"action": "delete"|"update", "ids": [...], "updates": {...}}`

### `GET /api/record/<table_name>/<record_id>/history`
View change history for a record (from `change_log` table).

### `GET /api/changes/recent`
Recent changes across all tables. **Query:** `limit` (default 50)

### `GET /api/export/<table_name>`
Export table as CSV file download.

---

## Sync Control

### `POST /api/sync/pull`
Pull all 21 modules from Zoho CRM (incremental, uses Modified_Time).

### `POST /api/sync/bulk-pull`
Pull using Zoho Bulk Read API (for large datasets).

### `POST /api/sync/push`
Push all records with `sync_status=modified` back to Zoho CRM.

### `POST /api/sync/push-preview`
Preview which records would be pushed (count per module).
**Response:** `{"modules": {"Leads": 5, "Contacts": 2}}`

### `POST /api/sync/push-module/<module_name>`
Push only a specific module's modified records.

### `POST /api/sync/full`
Full sync cycle: pull all -> push modified.

### `GET /api/sync/status`
Current sync state: running/idle, last sync time, progress.

### `POST /api/sync/reset`
Force-reset a stuck sync lock (30-min auto-reset built in).

### `GET /api/sync/auto`
Get auto-sync settings.
**Response:** `{"enabled": true, "interval_minutes": 60, "running": true}`

### `POST /api/sync/auto`
Update auto-sync settings.
**Body:** `{"enabled": true, "interval_minutes": 60}`

### `GET /api/sync/history`
Sync operation history log.
**Query:** `limit` (default 50)

### `POST /api/sync/import-emails`
Full email tracking import via COQL (scans all Leads + Contacts -- slow, ~2hrs for 131K records).

### `POST /api/sync/import-visits`
Full visits import from Contacts related list.

### `POST /api/sync/module/<module_name>`
Sync a single module (e.g., `/api/sync/module/Leads`).

---

## SQL Query

### `POST /api/query`
Execute read-only SQL queries.
**Body:** `{"sql": "SELECT * FROM leads LIMIT 10"}`
**Allowed:** SELECT, WITH, EXPLAIN
**Blocked:** INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE

---

## Table Manager

### `GET /api/tables`
List all tables with row counts, column counts.

### `POST /api/tables/create`
Create a new table.
**Body:** `{"name": "my_table", "columns": [{"name": "col1", "type": "VARCHAR(255)"}, ...]}`

### `POST /api/tables/<table_name>/columns`
Add a column to an existing table.
**Body:** `{"name": "new_col", "type": "TEXT"}`

### `POST /api/tables/<table_name>/drop`
Drop a table.

### `POST /api/tables/<table_name>/truncate`
Truncate (empty) a table.

### `GET /api/stats/overview`
Database statistics: total records, tables, sizes.

---

## Upload Data

### `POST /api/upload/preview`
Preview CSV/Excel file -- first 100 rows + detected columns.
**Body:** multipart/form-data with `file`
**Response:** `{"columns": [...], "preview": [...], "total_rows": 10000}`

### `POST /api/upload/import`
Start background upload import. Returns immediately with job_id.
**Body:** multipart/form-data with `file`, `table_name`, `mapping` (JSON), optional `create_new=true`, `new_table_name`
**Response:** `{"success": true, "background": true, "job_id": "abc12345"}`

### `GET /api/upload/status/<job_id>`
Check upload job progress.
**Response:** `{"status": "running"|"completed"|"failed", "rows_imported": 5000, "total_rows": 10000, "progress_pct": 50}`

### `GET /api/upload/jobs`
List all upload jobs (current session).

### `POST /api/upload/create-table`
Create a table from detected upload schema.
**Body:** `{"name": "new_table", "columns": [...]}`

---

## Enrich & Deduplicate

### `GET /api/enrich/duplicates/<table_name>`
Find exact duplicates by email, phone, or name.
**Query:** `field` (email/phone/name), `page`, `per_page`

### `GET /api/enrich/fuzzy-duplicates/<table_name>`
Fuzzy duplicate detection using pg_trgm trigram similarity.
**Query:** `field` (email/phone/name), `threshold` (0.0-1.0, default 0.6), `page`, `per_page`
**Technique:** GIN indexes on LOWER(TRIM(field)), LATERAL join with 500 sample values

### `GET /api/enrich/normalized-duplicates/<table_name>`
Smart dedup using 12-stage company name normalizer.
Finds duplicates that fuzzy matching misses: "ABC Ltd." = "A.B.C. Limited" = "ABC GROUP LTD"
**Query:** `page`, `per_page`

### `GET /api/enrich/cross-module-duplicates`
Find duplicates across leads, contacts, accounts.
**Query:** `field` (email/phone/name)

### `GET /api/enrich/completeness/<table_name>`
Field completeness analysis (% filled per column).

### `GET /api/enrich/validate/<table_name>`
Data validation: email format, phone format, required fields.

### `GET /api/enrich/duplicates/<table_name>/detail`
Detailed duplicate group view with all fields.

### `POST /api/enrich/convert`
Convert a lead to a contact.
**Body:** `{"lead_id": "uuid-here"}`

### `POST /api/enrich/merge`
Merge duplicate records (keep primary, merge fields from secondary).
**Body:** `{"primary_id": "uuid1", "secondary_ids": ["uuid2", "uuid3"], "table": "leads"}`

### `POST /api/enrich/bulk-update`
Bulk update multiple records.
**Body:** `{"table": "leads", "ids": [...], "updates": {"field": "value"}}`

---

## Custom Dedup

### `POST /api/enrich/custom-dedup`
Field-configurable deduplication with multiple modes.
**Body:**
```json
{
  "table": "accounts",
  "fields": ["account_name", "website"],
  "mode": "normalized",
  "cross_table": "leads",
  "cross_fields": ["company"],
  "threshold": 0.6,
  "limit": 500
}
```
**Modes:** `exact` (GROUP BY normalized), `normalized` (12-stage normalizer), `fuzzy` (pg_trgm similarity)
**Response:**
```json
{
  "mode": "normalized",
  "table": "accounts",
  "fields": ["account_name"],
  "total_groups": 45,
  "total_duplicate_records": 120,
  "groups": [{"normalized_key": "abc", "count": 3, "records": [...]}]
}
```

---

## Enrichment Tables

### `GET /api/enrichment/tables`
List all registered enrichment tables.
**Response:** `{"tables": [...], "total": 3}`

### `POST /api/enrichment/tables`
Register a new enrichment table.
**Body:** `{"table_name": "purchased_leads", "source": "Data vendor X", "target_module": "leads", "match_fields": ["email", "company"]}`

### `GET /api/enrichment/summary/<table_name>`
Get enrichment summary: total records, checked count, unique/duplicate/error counts.

### `POST /api/enrichment/dedup-check`
Run dedup check against CRM target module.
**Body:** `{"table_name": "purchased_leads"}`
**Response:** `{"checked": 500, "unique": 350, "duplicate": 150}`

### `POST /api/enrichment/sync-to-crm`
Push unique (non-duplicate) records to CRM table.
**Body:** `{"table_name": "purchased_leads"}`
**Response:** `{"pushed": 350, "skipped_duplicates": 150}`

---

## Companies House API (UK)

All endpoints require `COMPANIES_HOUSE_API_KEY` configured in env or Secret Manager. Free API -- 600 calls/5 min rate limit.

### `GET /api/companies-house/search`
Search UK companies by name.
**Query:** `q` (search term), `limit` (max results, default 20)
**Response:**
```json
{
  "companies": [
    {
      "company_number": "11099300",
      "title": "RED SQUARE GROUP LTD",
      "company_status": "active",
      "company_type": "ltd",
      "date_of_creation": "2017-12-06",
      "address": "4th Floor 18 St. Cross Street, London, EC1N 8UN",
      "sic_codes": ["41202"]
    }
  ],
  "total": 15
}
```

### `GET /api/companies-house/company/<company_number>`
Full company profile from Companies House.

### `GET /api/companies-house/officers/<company_number>`
List company officers (directors, secretaries).
**Response:**
```json
{
  "officers": [
    {"name": "ZEMSKIKH, Yury", "officer_role": "director", "appointed_on": "2021-03-01", "nationality": "British"}
  ],
  "active": 1,
  "total": 2
}
```

### `GET /api/companies-house/psc/<company_number>`
Persons with Significant Control (shareholders with 25%+ ownership).

### `GET /api/companies-house/filing-history/<company_number>`
Company filing history (annual accounts, confirmation statements, etc.).

### `GET /api/companies-house/snapshot/<company_number>`
Comprehensive snapshot: company profile + officers + PSC + charges + insolvency status in a single call.
**Response:** `{"profile": {...}, "officers": [...], "pscs": [...], "charges": [...], "company_number": "11099300"}`

### `POST /api/companies-house/enrich-account/<account_id>`
Auto-enrich a CRM account by:
1. Looking up account name in PostgreSQL
2. Searching Companies House for matching company
3. Matching via 12-stage company name normalizer
4. Writing officers, address, status, SIC codes to `companies_house_data` JSONB column
**Response:**
```json
{
  "status": "enriched",
  "matched_name": "RED SQUARE GROUP LTD",
  "match_score": 95,
  "company_number": "11099300",
  "data": {"company_status": "active", "officers": [...], "sic_codes": ["41202"]}
}
```

---

## Apify Social Media Enrichment

All endpoints require `APIFY_API_TOKEN` configured in env or Secret Manager.

### Available Actors

| Key | Actor ID | Cost/100 |
|-----|----------|----------|
| `linkedin_company` | anchor/linkedin-company-scraper | $3.00 |
| `linkedin_people` | anchor/linkedin-people-scraper | $3.00 |
| `instagram_scraper` | apify/instagram-scraper | $1.00 |
| `facebook_pages` | apify/facebook-pages-scraper | $0.50 |
| `website_contact` | apify/contact-information-scraper | $0.30 |
| `google_maps` | apify/google-maps-scraper | $1.50 |

### `GET /api/apify/actors`
List available Apify actors and whether API token is configured.
**Response:**
```json
{
  "actors": [
    {"key": "linkedin_company", "name": "LinkedIn Company Scraper", "actor_id": "anchor/linkedin-company-scraper", "cost_per_100": 3.0}
  ],
  "configured": true
}
```

### `POST /api/apify/run`
Run an Apify actor with custom input.
**Body:**
```json
{
  "actor_key": "website_contact",
  "company": {"name": "Red Square Group", "website": "https://redsquaregroup.com"}
}
```
**Response:** `{"items": [...], "count": 5}`

### `POST /api/apify/enrich-account/<account_id>`
Enrich a CRM account using selected Apify actors. Extracts emails, phones, social links and stores in `apify_enrichment` JSONB column.
**Body:** `{"actors": ["website_contact", "linkedin_company"]}`
**Response:**
```json
{
  "status": "enriched",
  "actors_run": ["website_contact", "linkedin_company"],
  "emails_found": ["info@company.com"],
  "phones_found": ["+44 20 1234 5678"],
  "social_links": {"linkedin": "https://linkedin.com/company/example"},
  "total_items": 8
}
```

### `POST /api/apify/cost-estimate`
Estimate cost for enriching N companies with selected actors.
**Body:** `{"company_count": 500, "actors": ["website_contact", "linkedin_company"]}`
**Response:**
```json
{
  "company_count": 500,
  "total_cost_usd": 16.5,
  "breakdown": {
    "website_contact": {"cost_usd": 1.5, "name": "Website Contact Scraper"},
    "linkedin_company": {"cost_usd": 15.0, "name": "LinkedIn Company Scraper"}
  }
}
```

---

## Zoho API Proxy

### `GET /api/zoho/modules`
List all available Zoho CRM modules.

### `GET /api/zoho/fields/<module_name>`
Get field definitions for a Zoho module.

### `GET /api/zoho/test`
Test Zoho API connectivity and token validity.

### `GET /api/conflicts`
List sync conflicts (local and remote both modified).

### `POST /api/conflicts/<conflict_id>/resolve`
Resolve a conflict.
**Body:** `{"resolution": "keep_local"|"keep_remote"|"merge", "merged_data": {...}}`

---

## AI Chat (Gemini 2.5 Pro)

### `POST /api/chat`
Send a message to the AI assistant.
**Body:** `{"message": "How many leads do we have?", "session_id": "default"}`
**Response:** `{"response": "You have 9,194 leads...", "session_id": "default", "tools_used": ["execute_sql"]}`

**Available AI tools:**
- `execute_sql` -- Run SELECT queries on the database
- `list_tables` -- List all database tables
- `describe_table` -- Get table schema and sample data
- `create_table` -- Create new tables

### `POST /api/chat/reset`
Reset a chat session.
**Body:** `{"session_id": "default"}`

### `GET /api/chat/status`
Check Gemini AI availability.
**Response:** `{"available": true, "model": "gemini-2.5-pro", "sessions": 1, "tools": [...]}`
