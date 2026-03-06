# Zoho CRM Module Configuration
# All standard modules + custom modules mapping

# Standard Zoho CRM Modules (20 total)
STANDARD_MODULES = {
    # Core Sales Modules
    "Leads": {
        "table": "leads",
        "api_name": "Leads",
        "description": "Potential customers",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "company",
            "lead_source",
            "lead_status",
        ],
    },
    "Contacts": {
        "table": "contacts",
        "api_name": "Contacts",
        "description": "Contact persons",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "account_id",
            "title",
        ],
    },
    "Accounts": {
        "table": "accounts",
        "api_name": "Accounts",
        "description": "Companies/Organizations",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "account_name",
            "website",
            "phone",
            "industry",
            "account_type",
        ],
    },
    "Deals": {
        "table": "deals",
        "api_name": "Deals",
        "description": "Sales opportunities",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "deal_name",
            "amount",
            "stage",
            "probability",
            "expected_revenue",
            "closing_date",
        ],
    },
    "Tasks": {
        "table": "tasks",
        "api_name": "Tasks",
        "description": "Activities/Tasks",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "subject",
            "status",
            "priority",
            "due_date",
            "related_to",
            "assigned_to",
        ],
    },
    "Events": {
        "table": "events",
        "api_name": "Events",
        "description": "Meetings/Events",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "event_title",
            "start_datetime",
            "end_datetime",
            "location",
            "related_to",
        ],
    },
    "Calls": {
        "table": "calls",
        "api_name": "Calls",
        "description": "Phone calls",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "call_type",
            "call_duration",
            "call_start_time",
            "related_to",
            "call_result",
        ],
    },
    "Notes": {
        "table": "notes",
        "api_name": "Notes",
        "description": "Notes/Attachments",
        "has_sync_status": True,
        "fields": ["zoho_id", "note_title", "note_content", "related_to", "created_by"],
    },
    # Inventory & Products
    "Products": {
        "table": "products",
        "api_name": "Products",
        "description": "Products/Services",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "product_name",
            "product_code",
            "unit_price",
            "quantity",
            "description",
        ],
    },
    "Vendors": {
        "table": "vendors",
        "api_name": "Vendors",
        "description": "Suppliers/Vendors",
        "has_sync_status": True,
        "fields": ["zoho_id", "vendor_name", "email", "phone", "website", "category"],
    },
    # Sales Documents
    "Quotes": {
        "table": "quotes",
        "api_name": "Quotes",
        "description": "Price quotes",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "quote_name",
            "account_id",
            "contact_id",
            "grand_total",
            "valid_until",
        ],
    },
    "Sales_Orders": {
        "table": "sales_orders",
        "api_name": "Sales_Orders",
        "description": "Sales orders",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "sales_order_name",
            "account_id",
            "contact_id",
            "grand_total",
            "order_date",
        ],
    },
    "Purchase_Orders": {
        "table": "purchase_orders",
        "api_name": "Purchase_Orders",
        "description": "Purchase orders",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "purchase_order_name",
            "vendor_id",
            "grand_total",
            "order_date",
        ],
    },
    "Invoices": {
        "table": "invoices",
        "api_name": "Invoices",
        "description": "Customer invoices",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "invoice_number",
            "account_id",
            "grand_total",
            "invoice_date",
            "status",
        ],
    },
    # Marketing & Support
    "Campaigns": {
        "table": "campaigns",
        "api_name": "Campaigns",
        "description": "Marketing campaigns",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "campaign_name",
            "campaign_type",
            "start_date",
            "end_date",
            "status",
        ],
    },
    "Cases": {
        "table": "cases",
        "api_name": "Cases",
        "description": "Support cases",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "case_number",
            "subject",
            "priority",
            "status",
            "account_id",
            "contact_id",
        ],
    },
    "Solutions": {
        "table": "solutions",
        "api_name": "Solutions",
        "description": "Knowledge base solutions",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "solution_title",
            "solution_number",
            "status",
            "published",
        ],
    },
    # Additional
    "Price_Books": {
        "table": "price_books",
        "api_name": "Price_Books",
        "description": "Product pricing",
        "has_sync_status": True,
        "fields": ["zoho_id", "price_book_name", "description", "active"],
    },
    # SalesIQ Integration
    "Visits": {
        "table": "visits",
        "api_name": "Visits",
        "description": "Website visitor tracking (SalesIQ)",
        "has_sync_status": False,
        "fields": ["zoho_id", "visited_page", "ip_address", "browser", "operating_system",
                    "visit_source", "time_spent", "portal_name"],
    },
}

# Custom Modules (dynamically loaded from database)
CUSTOM_MODULES = {
    "Client_Leads": {
        "table": "client_leads",
        "api_name": "Client_Leads",
        "description": "Client leads custom module",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "client_name",
            "lead_source",
            "status",
            "value",
        ],
    },
    "Projects_Tender": {
        "table": "projects_tender",
        "api_name": "Projects_Tender",
        "description": "Tender projects",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "tender_name",
            "tender_value",
            "submission_date",
            "status",
        ],
    },
    "Projects_Contracts": {
        "table": "projects_contracts",
        "api_name": "Projects_Contracts",
        "description": "Project contracts",
        "has_sync_status": True,
        "fields": [
            "zoho_id",
            "contract_name",
            "contract_value",
            "start_date",
            "end_date",
            "status",
        ],
    },
}

# Dependency order for syncing (FK constraints)
SYNC_DEPENDENCY_ORDER = [
    "Accounts",  # No dependencies
    "Vendors",  # No dependencies
    "Contacts",  # Depends on Accounts
    "Leads",  # No dependencies
    "Products",  # No dependencies
    "Price_Books",  # Depends on Products
    "Campaigns",  # No dependencies
    "Deals",  # Depends on Accounts, Contacts, Campaigns
    "Quotes",  # Depends on Accounts, Contacts, Deals
    "Sales_Orders",  # Depends on Accounts, Contacts, Deals
    "Purchase_Orders",  # Depends on Vendors
    "Invoices",  # Depends on Accounts, Contacts, Sales_Orders
    "Cases",  # Depends on Accounts, Contacts
    "Solutions",  # No dependencies
    "Tasks",  # Depends on all modules
    "Events",  # Depends on all modules
    "Calls",  # Depends on all modules
    "Notes",  # Depends on all modules
    "Visits",  # SalesIQ - depends on Leads/Contacts
    "Client_Leads",  # Custom
    "Projects_Tender",  # Custom
    "Projects_Contracts",  # Custom
]


# Module to table mapping (for quick lookup)
def get_all_modules():
    """Get all modules (standard + custom)"""
    all_modules = {**STANDARD_MODULES}
    all_modules.update(CUSTOM_MODULES)
    return all_modules


def get_module_table_map():
    """Get module to table mapping"""
    return {name: config["table"] for name, config in get_all_modules().items()}


def get_table_module_map():
    """Get table to module mapping (reverse)"""
    module_table = get_module_table_map()
    return {v: k for k, v in module_table.items()}


def get_table_for_module(module_name):
    """Get table name for a module"""
    all_modules = get_all_modules()
    if module_name in all_modules:
        return all_modules[module_name]["table"]
    return None


def get_module_for_table(table_name):
    """Get module name for a table"""
    table_module = get_table_module_map()
    return table_module.get(table_name)


# Module list for bulk sync
ALL_MODULE_NAMES = list(get_all_modules().keys())

if __name__ == "__main__":
    print(f"Total modules configured: {len(get_all_modules())}")
    print(f"Standard modules: {len(STANDARD_MODULES)}")
    print(f"Custom modules: {len(CUSTOM_MODULES)}")
    print("\nAll modules:")
    for name, config in get_all_modules().items():
        print(f"  {name} -> {config['table']}")
