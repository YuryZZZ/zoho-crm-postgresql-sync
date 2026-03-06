# API Usage Examples

> Complete examples for all API endpoints

---

## Base URL

```
https://zoho-crm-dashboard-699552818896.europe-west1.run.app
```

---

## Core API

### 1. Get Database Statistics

```bash
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/stats"
```

Response:
```json
{
  "pending_total": 0,
  "tables": [
    {"table": "contacts", "count": 122742, "pending": 0},
    {"table": "accounts", "count": 36898, "pending": 0},
    {"table": "calls", "count": 65757, "pending": 0}
  ],
  "total_records": 506840,
  "total_tables": 70
}
```

---

### 2. Get Table Data

```bash
# Basic request
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/table/contacts?page=1&per_page=10"

# With search
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/table/contacts?search=john&page=1&per_page=50"

# With sorting
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/table/contacts?sort=created_time:desc&page=1"
```

Response:
```json
{
  "columns": ["id", "zoho_id", "first_name", "last_name", "email", "phone"],
  "data": [
    {"id": 1, "zoho_id": "123456", "first_name": "John", "last_name": "Doe", "email": "john@example.com"}
  ],
  "page": 1,
  "per_page": 10,
  "total": 122742,
  "total_pages": 12275
}
```

---

### 3. Get Sync Counts

```bash
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/counts"
```

Response:
```json
{
  "total": 506840,
  "synced": 505845,
  "pending": 0,
  "modified": 0,
  "enriched": 0,
  "new": 0,
  "error": 0,
  "unsynced": 0
}
```

---

## Dynamic Tables API

### 4. Create Custom Table

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/tables/create" \
  -H "Content-Type: application/json" \
  -d '{
    "table_name": "company_enrichment_data",
    "columns": [
      {"name": "company_name", "type": "string", "nullable": false, "indexed": true},
      {"name": "industry", "type": "string", "nullable": true},
      {"name": "company_size", "type": "integer", "nullable": true},
      {"name": "annual_revenue", "type": "decimal", "nullable": true},
      {"name": "website", "type": "url", "nullable": true}
    ],
    "description": "External company data for enrichment",
    "tags": ["enrichment", "companies", "external"]
  }'
```

Response:
```json
{
  "success": true,
  "table_name": "company_enrichment_data",
  "display_name": "company_enrichment_data",
  "columns_created": 5,
  "message": "Table \"company_enrichment_data\" created successfully with 5 columns"
}
```

---

### 5. List Custom Tables

```bash
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/tables/custom"
```

Response:
```json
{
  "tables": [
    {
      "table_name": "company_enrichment_data",
      "display_name": "Company Enrichment Data",
      "description": "External company data",
      "record_count": 1000,
      "column_count": 10,
      "tags": ["enrichment"],
      "created_at": "2026-02-23T10:00:00"
    }
  ]
}
```

---

### 6. Get Table Schema

```bash
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/tables/schema/contacts"
```

Response:
```json
{
  "table_name": "contacts",
  "columns": [
    {"column_name": "id", "data_type": "integer", "is_nullable": "NO", "column_default": "nextval('contacts_id_seq'::regclass)"},
    {"column_name": "zoho_id", "data_type": "character varying", "is_nullable": "YES"},
    {"column_name": "first_name", "data_type": "text", "is_nullable": "YES"},
    {"column_name": "last_name", "data_type": "text", "is_nullable": "YES"},
    {"column_name": "email", "data_type": "text", "is_nullable": "YES"}
  ]
}
```

---

### 7. Create Relationship

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/tables/relationships" \
  -H "Content-Type: application/json" \
  -d '{
    "source_table": "contacts",
    "source_column": "account_name",
    "target_table": "company_enrichment_data",
    "target_column": "company_name",
    "relationship_type": "one_to_many",
    "description": "Link contacts to their company data"
  }'
```

Response:
```json
{
  "success": true,
  "relationship": {
    "source": "contacts.account_name",
    "target": "company_enrichment_data.company_name",
    "type": "one_to_many"
  },
  "message": "Relationship created: contacts.account_name -> company_enrichment_data.company_name"
}
```

---

### 8. Enrich Data from Table

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/tables/enrich" \
  -H "Content-Type: application/json" \
  -d '{
    "source_table": "contacts",
    "enrichment_table": "company_enrichment_data",
    "match_columns": {
      "account_name": "company_name"
    },
    "enrich_columns": {
      "industry": "industry",
      "company_size": "company_size"
    },
    "confidence_threshold": 80.0
  }'
```

Response:
```json
{
  "success": true,
  "results": {
    "matched": 5000,
    "enriched": 4800,
    "errors": []
  },
  "message": "Enriched 4800 records from company_enrichment_data"
}
```

---

## Staging Workflow API

### 9. Create Staging Table

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/staging/create" \
  -H "Content-Type: application/json" \
  -d '{
    "module": "contacts",
    "custom_fields": [
      {"name": "enriched_industry", "type": "TEXT"},
      {"name": "data_quality_score", "type": "INTEGER"}
    ]
  }'
```

Response:
```json
{
  "success": true,
  "staging_table": "staging_contacts_20240223103000",
  "source_table": "contacts",
  "records_copied": 122742,
  "message": "Created staging table staging_contacts_20240223103000 with 122742 records"
}
```

---

### 10. Get Staging Statistics

```bash
# All staging tables
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/staging/stats"

# Specific table
curl -X GET "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/staging/stats?table=staging_contacts_20240223103000"
```

Response:
```json
{
  "success": true,
  "staging_tables": {
    "staging_contacts_20240223103000": {
      "draft": 100,
      "pending_validation": 50,
      "validated": 200,
      "approved": 25
    }
  }
}
```

---

### 11. Validate Records

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/staging/validate" \
  -H "Content-Type: application/json" \
  -d '{
    "staging_table": "staging_contacts_20240223103000",
    "record_ids": [1, 2, 3, 4, 5]
  }'
```

Response:
```json
{
  "results": [
    {
      "success": true,
      "valid": true,
      "errors": [],
      "status": "validated"
    },
    {
      "success": true,
      "valid": false,
      "errors": [
        {"field": "email", "error": "Invalid email format"}
      ],
      "status": "pending_validation"
    }
  ]
}
```

---

### 12. Approve for Sync

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/staging/approve" \
  -H "Content-Type: application/json" \
  -d '{
    "staging_table": "staging_contacts_20240223103000",
    "record_ids": [1, 3, 5],
    "approved_by": "admin@company.com"
  }'
```

Response:
```json
{
  "success": true,
  "approved_count": 3,
  "message": "3 records approved for sync"
}
```

---

## AI Chat API

### 13. Chat with AI

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "How many contacts dont have email addresses?",
    "current_table": "contacts",
    "history": []
  }'
```

Response:
```json
{
  "success": true,
  "message": "I found 1,234 contacts without email addresses. Here's the SQL query to find them:\n\n```sql\nSELECT COUNT(*) FROM contacts WHERE email IS NULL OR email = '';\n```",
  "intent": "data_analysis"
}
```

---

### 14. Generate SQL

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/chat/sql" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Find duplicate contacts by email address",
    "table": "contacts"
  }'
```

Response:
```json
{
  "success": true,
  "sql": "SELECT email, COUNT(*) as count FROM contacts WHERE email IS NOT NULL AND email != '' GROUP BY email HAVING COUNT(*) > 1"
}
```

---

### 15. Analyze Data

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/chat/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "table": "accounts",
    "question": "What industries have the most accounts?"
  }'
```

Response:
```json
{
  "success": true,
  "analysis": "Based on the analysis of 36,898 accounts:\n\nTop Industries:\n1. Construction - 12,456 (33.7%)\n2. Real Estate - 8,234 (22.3%)\n3. Manufacturing - 5,678 (15.4%)\n\nRecommendations:\n- Focus enrichment efforts on Construction industry\n- 45% of Manufacturing accounts are missing industry data",
  "table": "accounts"
}
```

---

### 16. Get Enrichment Suggestion

```bash
curl -X POST "https://zoho-crm-dashboard-699552818896.europe-west1.run.app/api/chat/suggest-enrichment" \
  -H "Content-Type: application/json" \
  -d '{
    "source_table": "contacts",
    "goal": "Add company size and industry data to contacts"
  }'
```

Response:
```json
{
  "success": true,
  "suggestion": "Recommended enrichment strategy:\n\n1. Create custom table:\n```sql\nCREATE TABLE company_data (\n  company_name VARCHAR(255),\n  industry VARCHAR(100),\n  company_size INTEGER\n);\n```\n\n2. Upload company data via Excel\n\n3. Create relationship:\n   contacts.account_name → company_data.company_name\n\n4. Enrich contacts with industry and company_size",
  "source_table": "contacts"
}
```

---

## JavaScript Usage Examples

### Fetch Table Data

```javascript
async function loadContacts() {
  const response = await fetch('/api/table/contacts?page=1&per_page=50');
  const data = await response.json();
  
  console.log(`Total: ${data.total} records`);
  console.log(`Columns: ${data.columns.join(', ')}`);
  
  data.data.forEach(record => {
    console.log(`${record.first_name} ${record.last_name} - ${record.email}`);
  });
}
```

---

### Create Custom Table

```javascript
async function createEnrichmentTable() {
  const response = await fetch('/api/tables/create', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      table_name: 'company_data',
      columns: [
        {name: 'company_name', type: 'string', nullable: false, indexed: true},
        {name: 'industry', type: 'string'},
        {name: 'revenue', type: 'decimal'}
      ],
      description: 'Company enrichment data',
      tags: ['enrichment']
    })
  });
  
  const result = await response.json();
  if (result.success) {
    console.log('Table created:', result.table_name);
  }
}
```

---

### Use AI Chat

```javascript
async function askAI(question) {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      message: question,
      current_table: 'contacts'
    })
  });
  
  const result = await response.json();
  if (result.success) {
    displayMessage(result.message);
  }
}

// Usage
askAI("How many contacts don't have emails?");
```

---

## Python Usage Examples

### Using requests library

```python
import requests

BASE_URL = "https://zoho-crm-dashboard-699552818896.europe-west1.run.app"

# Get table data
def get_table_data(table_name, page=1, per_page=50):
    response = requests.get(
        f"{BASE_URL}/api/table/{table_name}",
        params={"page": page, "per_page": per_page}
    )
    return response.json()

# Create custom table
def create_custom_table(name, columns):
    response = requests.post(
        f"{BASE_URL}/api/tables/create",
        json={
            "table_name": name,
            "columns": columns,
            "description": f"Custom table: {name}"
        }
    )
    return response.json()

# Chat with AI
def chat_with_ai(message, current_table=None):
    response = requests.post(
        f"{BASE_URL}/api/chat",
        json={
            "message": message,
            "current_table": current_table
        }
    )
    return response.json()

# Usage
contacts = get_table_data("contacts", page=1, per_page=10)
print(f"Found {contacts['total']} contacts")

result = chat_with_ai("Analyze contacts by industry", "contacts")
print(result["message"])
```

---

## Error Handling

### Common Error Responses

**400 Bad Request**
```json
{
  "error": "Table name is required"
}
```

**500 Server Error**
```json
{
  "success": false,
  "error": "Database connection failed"
}
```

### Error Handling in JavaScript

```javascript
async function safeApiCall() {
  try {
    const response = await fetch('/api/tables/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})  // Missing required field
    });
    
    if (!response.ok) {
      const error = await response.json();
      console.error('API Error:', error.error);
      return null;
    }
    
    return await response.json();
  } catch (error) {
    console.error('Network Error:', error);
    return null;
  }
}
```

---

**End of API Examples**
