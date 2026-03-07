# API Usage Examples

> Complete curl examples for all API endpoints

---

## Base URL

```
https://zoho-crm-dashboard-30591337479.europe-west1.run.app
```

---

## Core API

### 1. Dashboard Stats

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/dashboard" | python -m json.tool
```

### 2. Table Data (paginated, search, sort)

```bash
# Basic
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/table/contacts?page=1&per_page=10"

# With search
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/table/contacts?search=john&per_page=50"

# With sorting
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/table/contacts?sort_by=created_at&sort_dir=desc"
```

### 3. SQL Query

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/query" \
  -X POST -H "Content-Type: application/json" \
  -d '{"sql": "SELECT account_name, COUNT(*) as cnt FROM accounts GROUP BY account_name HAVING COUNT(*) > 1 LIMIT 20"}'
```

### 4. Create Record

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/record/leads" \
  -X POST -H "Content-Type: application/json" \
  -d '{"first_name": "John", "last_name": "Doe", "email": "john@example.com", "company": "Acme Corp"}'
```

### 5. Update Record

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/record/leads/UUID_HERE" \
  -X PUT -H "Content-Type: application/json" \
  -d '{"email": "new@example.com"}'
```

### 6. Export Table as CSV

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/export/accounts" -o accounts.csv
```

---

## Sync Control

### 7. Pull All Modules from Zoho

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/pull" -X POST -d '{}'
```

### 8. Push Modified Records to Zoho

```bash
# Preview what will be pushed
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/push-preview" -X POST -d '{}'

# Push all modified
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/push" -X POST -d '{}'

# Push single module
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/push-module/Leads" -X POST -d '{}'
```

### 9. Sync Status & History

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/status"
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/history?limit=10"
```

### 10. Reset Stuck Sync

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/sync/reset" -X POST -d '{}'
```

---

## Enrichment & Deduplication

### 11. Fuzzy Duplicates

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrich/fuzzy-duplicates/accounts?field=name&threshold=0.6"
```

### 12. Smart Dedup (Normalized Company Names)

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrich/normalized-duplicates/accounts?per_page=20"
```

### 13. Custom Dedup (Field-Configurable)

```bash
# Exact dedup on email
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrich/custom-dedup" \
  -X POST -H "Content-Type: application/json" \
  -d '{"table": "contacts", "fields": ["email"], "mode": "exact"}'

# Normalized dedup on company name
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrich/custom-dedup" \
  -X POST -H "Content-Type: application/json" \
  -d '{"table": "accounts", "fields": ["account_name"], "mode": "normalized"}'

# Cross-module dedup
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrich/custom-dedup" \
  -X POST -H "Content-Type: application/json" \
  -d '{"table": "accounts", "fields": ["account_name"], "mode": "fuzzy", "cross_table": "leads", "cross_fields": ["company"], "threshold": 0.5}'
```

### 14. Cross-Module Duplicates

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrich/cross-module-duplicates?field=email"
```

### 15. Merge Duplicates

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrich/merge" \
  -X POST -H "Content-Type: application/json" \
  -d '{"primary_id": "uuid-keep", "secondary_ids": ["uuid-merge1", "uuid-merge2"], "table": "contacts"}'
```

---

## Enrichment Tables

### 16. Register Enrichment Table

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrichment/tables" \
  -X POST -H "Content-Type: application/json" \
  -d '{"table_name": "purchased_leads_q1", "source": "Data vendor X", "target_module": "leads", "match_fields": ["email", "company"]}'
```

### 17. List Enrichment Tables

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrichment/tables"
```

### 18. Dedup Check (against CRM)

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrichment/dedup-check" \
  -X POST -H "Content-Type: application/json" \
  -d '{"table_name": "purchased_leads_q1"}'
```

### 19. Push Unique Records to CRM

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrichment/sync-to-crm" \
  -X POST -H "Content-Type: application/json" \
  -d '{"table_name": "purchased_leads_q1"}'
```

### 20. Enrichment Summary

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/enrichment/summary/purchased_leads_q1"
```

---

## Companies House API

### 21. Search UK Companies

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/companies-house/search?q=red+square+group&limit=5"
```

Response:
```json
{
  "companies": [
    {
      "company_number": "11099300",
      "title": "RED SQUARE GROUP LTD",
      "company_status": "active",
      "company_type": "ltd",
      "date_of_creation": "2017-12-06",
      "address": "4th Floor 18 St. Cross Street, London, England, EC1N 8UN"
    }
  ],
  "total": 5
}
```

### 22. Company Profile

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/companies-house/company/11099300"
```

### 23. Company Officers

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/companies-house/officers/11099300"
```

### 24. Persons with Significant Control

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/companies-house/psc/11099300"
```

### 25. Full Company Snapshot

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/companies-house/snapshot/11099300"
```

### 26. Filing History

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/companies-house/filing-history/11099300"
```

### 27. Auto-Enrich CRM Account via Companies House

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/companies-house/enrich-account/ACCOUNT_UUID" \
  -X POST -H "Content-Type: application/json" -d '{}'
```

Response:
```json
{
  "status": "enriched",
  "matched_name": "RED SQUARE GROUP LTD",
  "match_score": 95,
  "company_number": "11099300",
  "data": {
    "company_status": "active",
    "sic_codes": ["41202"],
    "officers": [{"name": "ZEMSKIKH, Yury", "officer_role": "director"}]
  }
}
```

---

## Apify Social Media

### 28. List Available Actors

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/apify/actors"
```

### 29. Run Actor

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/apify/run" \
  -X POST -H "Content-Type: application/json" \
  -d '{"actor_key": "website_contact", "company": {"name": "Red Square Group", "website": "https://redsquaregroup.com"}}'
```

### 30. Enrich Account with Multiple Actors

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/apify/enrich-account/ACCOUNT_UUID" \
  -X POST -H "Content-Type: application/json" \
  -d '{"actors": ["website_contact", "linkedin_company", "instagram_scraper"]}'
```

Response:
```json
{
  "status": "enriched",
  "actors_run": ["website_contact", "linkedin_company", "instagram_scraper"],
  "emails_found": ["info@company.com", "sales@company.com"],
  "phones_found": ["+44 20 1234 5678"],
  "social_links": {"linkedin": "https://linkedin.com/company/example"},
  "total_items": 12
}
```

### 31. Cost Estimate

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/apify/cost-estimate" \
  -X POST -H "Content-Type: application/json" \
  -d '{"company_count": 500, "actors": ["website_contact", "linkedin_company", "instagram_scraper", "facebook_pages", "google_maps"]}'
```

Response:
```json
{
  "company_count": 500,
  "total_cost_usd": 31.5,
  "breakdown": {
    "website_contact": {"cost_usd": 1.5, "name": "Website Contact Scraper"},
    "linkedin_company": {"cost_usd": 15.0, "name": "LinkedIn Company Scraper"},
    "instagram_scraper": {"cost_usd": 5.0, "name": "Instagram Scraper"},
    "facebook_pages": {"cost_usd": 2.5, "name": "Facebook Pages Scraper"},
    "google_maps": {"cost_usd": 7.5, "name": "Google Maps Scraper"}
  }
}
```

---

## AI Chat

### 32. Chat with Gemini

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/chat" \
  -X POST -H "Content-Type: application/json" \
  -d '{"message": "How many contacts dont have email addresses?", "session_id": "default"}'
```

### 33. Reset Chat

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/chat/reset" \
  -X POST -H "Content-Type: application/json" \
  -d '{"session_id": "default"}'
```

### 34. Check AI Status

```bash
curl -s "https://zoho-crm-dashboard-30591337479.europe-west1.run.app/api/chat/status"
```

---

## Python Usage

```python
import requests

BASE = "https://zoho-crm-dashboard-30591337479.europe-west1.run.app"

# Search UK company
ch = requests.get(f"{BASE}/api/companies-house/search", params={"q": "Acme Corp", "limit": 5}).json()
print(f"Found {ch['total']} companies")

# Cost estimate for enrichment
cost = requests.post(f"{BASE}/api/apify/cost-estimate", json={
    "company_count": 100,
    "actors": ["website_contact", "linkedin_company"]
}).json()
print(f"Cost for 100 companies: ${cost['total_cost_usd']}")

# Custom dedup
dupes = requests.post(f"{BASE}/api/enrich/custom-dedup", json={
    "table": "accounts",
    "fields": ["account_name"],
    "mode": "normalized"
}).json()
print(f"Found {dupes['total_groups']} duplicate groups")

# SQL query
data = requests.post(f"{BASE}/api/query", json={
    "sql": "SELECT COUNT(*) as total FROM accounts WHERE website IS NOT NULL"
}).json()
print(f"Accounts with website: {data['data'][0]['total']}")
```

---

## Error Handling

All endpoints return JSON errors with HTTP status codes:

```json
{"error": "Table name is required"}           // 400
{"error": "Record not found"}                  // 404
{"error": "COMPANIES_HOUSE_API_KEY not configured"}  // 500
{"error": "Apify API error: Invalid token"}    // 500
```

---

**End of API Examples** | **74 endpoints** | **Last updated: 2026-03-07**
