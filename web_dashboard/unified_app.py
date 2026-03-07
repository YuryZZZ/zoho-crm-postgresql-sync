#!/usr/bin/env python3
"""
Zoho CRM <-> PostgreSQL Unified Dashboard
Full-featured web app: sync, browse, create, upload, enrich data
"""

import io
import json
import hashlib
import logging
import os
import re
import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import psycopg2
import psycopg2.extras
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from dotenv import load_dotenv

load_dotenv()

# Gemini AI
try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("unified_app")

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "zoho-crm-dashboard-2026")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB max upload

# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------

def get_db_password():
    pw = os.environ.get("DB_PASSWORD", "")
    if pw and not pw.startswith("projects/"):
        return pw
    if pw and pw.startswith("projects/"):
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            resp = client.access_secret_version(request={"name": pw})
            return resp.payload.data.decode("UTF-8")
        except Exception:
            pass
    return pw or "SecurePostgresPass123!"

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "34.78.66.32"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "database": os.environ.get("DB_NAME", "zoho_crm_digital_twin"),
    "user": os.environ.get("DB_USER", "zoho_admin"),
    "password": get_db_password(),
}

def get_db():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)

# ---------------------------------------------------------------------------
# Module configuration
# ---------------------------------------------------------------------------
# Try importing module_config from same dir (Docker) or parent dir (dev)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from module_config import get_module_table_map, get_table_module_map, SYNC_DEPENDENCY_ORDER
    MODULE_TABLE_MAP = get_module_table_map()
    TABLE_MODULE_MAP = get_table_module_map()
    logger.info(f"Loaded {len(MODULE_TABLE_MAP)} modules from module_config")
except ImportError:
    logger.warning("module_config.py not found, using fallback module list")
    MODULE_TABLE_MAP = {
        "Leads": "leads", "Contacts": "contacts", "Accounts": "accounts",
        "Deals": "deals", "Tasks": "tasks", "Events": "events",
        "Calls": "calls", "Notes": "notes", "Products": "products",
        "Vendors": "vendors", "Price_Books": "price_books",
        "Quotes": "quotes", "Sales_Orders": "sales_orders",
        "Purchase_Orders": "purchase_orders", "Invoices": "invoices",
        "Campaigns": "campaigns", "Cases": "cases", "Solutions": "solutions",
        "Client_Leads": "client_leads", "Projects_Tender": "projects_tender",
        "Projects_Contracts": "projects_contracts",
    }
    TABLE_MODULE_MAP = {v: k for k, v in MODULE_TABLE_MAP.items()}
    SYNC_DEPENDENCY_ORDER = list(MODULE_TABLE_MAP.keys())

# ---------------------------------------------------------------------------
# Zoho CRM API Client (embedded, self-contained)
# ---------------------------------------------------------------------------
class ZohoClient:
    """Lightweight Zoho CRM client for the dashboard."""

    def __init__(self):
        self.config = self._load_config()
        self.access_token = None
        self.token_expires = 0
        self.session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _load_config(self) -> Dict:
        """Load credentials from env vars, Secret Manager, or local JSON files."""
        # 1. Environment variables (preferred for cloud deployment)
        if os.environ.get("ZOHO_CLIENT_ID"):
            logger.info("Loading Zoho credentials from environment variables")
            return {
                "client_id": os.environ.get("ZOHO_CLIENT_ID", ""),
                "client_secret": os.environ.get("ZOHO_CLIENT_SECRET", ""),
                "refresh_token": os.environ.get("ZOHO_REFRESH_TOKEN", ""),
                "region": os.environ.get("ZOHO_REGION", "eu"),
                "api_base": os.environ.get("ZOHO_API_BASE", ""),
                "token_url": os.environ.get("ZOHO_TOKEN_URL", ""),
            }

        # 2. GCP Secret Manager (cloud-native)
        zoho_secret = os.environ.get("ZOHO_CREDENTIALS_SECRET")
        if zoho_secret:
            try:
                from google.cloud import secretmanager
                client = secretmanager.SecretManagerServiceClient()
                resp = client.access_secret_version(request={"name": zoho_secret})
                cfg = json.loads(resp.payload.data.decode("UTF-8"))
                logger.info("Loading Zoho credentials from Secret Manager")
                return {
                    "client_id": cfg.get("client_id", ""),
                    "client_secret": cfg.get("client_secret", ""),
                    "refresh_token": cfg.get("refresh_token", ""),
                    "region": cfg.get("region", "eu"),
                    "api_base": cfg.get("api_base", ""),
                    "token_url": cfg.get("token_url", ""),
                }
            except Exception as e:
                logger.warning(f"Failed to load from Secret Manager: {e}")

        # 3. Try zoho_auth_config.json files
        for p in [
            Path(__file__).parent.parent / "zoho_auth_config.json",
            Path(__file__).parent.parent.parent / "zoho_auth_config.json",
            Path(__file__).parent / "zoho_auth_config.json",
        ]:
            if p.exists():
                with open(p) as f:
                    cfg = json.load(f)
                creds = cfg.get("credentials", {})
                crm = cfg.get("applications", {}).get("zoho_crm_integration", {})
                region = cfg.get("authentication", {}).get("region", "eu").lower()
                logger.info(f"Loading Zoho credentials from {p}")
                return {
                    "client_id": creds.get("client_id", ""),
                    "client_secret": creds.get("client_secret", ""),
                    "refresh_token": crm.get("refresh_token", ""),
                    "region": region,
                }

        # 4. Try .ai/credentials.json files
        for p in [
            Path(__file__).parent.parent / ".ai" / "credentials.json",
            Path(__file__).parent.parent.parent / ".ai" / "credentials.json",
            Path(__file__).parent / ".ai" / "credentials.json",
        ]:
            if p.exists():
                with open(p) as f:
                    cfg = json.load(f)
                api_cfg = cfg.get("bulk_sync_api", cfg)
                logger.info(f"Loading Zoho credentials from {p}")
                return {
                    "client_id": api_cfg.get("client_id", ""),
                    "client_secret": api_cfg.get("client_secret", ""),
                    "refresh_token": api_cfg.get("refresh_token", ""),
                    "region": "eu",
                    "api_base": api_cfg.get("api_base", "https://www.zohoapis.eu"),
                    "token_url": api_cfg.get("token_url", "https://accounts.zoho.eu/oauth/v2/token"),
                }

        logger.warning("No Zoho credentials found")
        return {}

    @property
    def api_base(self):
        if "api_base" in self.config:
            return self.config["api_base"]
        region = self.config.get("region", "eu")
        bases = {"eu": "https://www.zohoapis.eu", "us": "https://www.zohoapis.com",
                 "in": "https://www.zohoapis.in", "au": "https://www.zohoapis.com.au"}
        return bases.get(region, "https://www.zohoapis.eu")

    @property
    def token_url(self):
        if "token_url" in self.config:
            return self.config["token_url"]
        region = self.config.get("region", "eu")
        return f"https://accounts.zoho.{region}/oauth/v2/token"

    def _refresh(self) -> bool:
        if not self.config.get("refresh_token"):
            return False
        try:
            r = self.session.post(self.token_url, data={
                "grant_type": "refresh_token",
                "refresh_token": self.config["refresh_token"],
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
            }, timeout=30)
            r.raise_for_status()
            d = r.json()
            self.access_token = d["access_token"]
            self.token_expires = time.time() + d.get("expires_in", 3600) - 300
            return True
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False

    def _ensure_token(self) -> bool:
        if not self.access_token or time.time() >= self.token_expires:
            return self._refresh()
        return True

    def api(self, method, endpoint, **kw) -> Optional[Dict]:
        if not self._ensure_token():
            return None
        url = f"{self.api_base}/crm/v2/{endpoint.lstrip('/')}"
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}", "Content-Type": "application/json"}
        try:
            r = self.session.request(method, url, headers=headers, timeout=60, **kw)
            r.raise_for_status()
            return r.json() if r.status_code != 204 else {"status": "success"}
        except Exception as e:
            logger.error(f"Zoho API error: {e}")
            return None

    def get_all_records(self, module: str, modified_since: str = None) -> List[Dict]:
        """Fetch records from Zoho CRM. Uses If-Modified-Since header for incremental sync."""
        all_recs = []
        page = 1
        extra_headers = {}
        if modified_since:
            extra_headers["If-Modified-Since"] = modified_since
        while True:
            params = {"page": page, "per_page": 200}
            resp = self._api_with_headers("GET", module, params=params, extra_headers=extra_headers)
            if not resp or "data" not in resp:
                break
            all_recs.extend(resp["data"])
            if not resp.get("info", {}).get("more_records"):
                break
            page += 1
            time.sleep(0.3)
        return all_recs

    def _api_with_headers(self, method, endpoint, extra_headers=None, **kw) -> Optional[Dict]:
        """Like api() but allows extra headers (e.g. If-Modified-Since).
        Returns None on error, empty dict on 204, response JSON on success.
        Raises requests.HTTPError for 4xx/5xx if raise_errors=True in kw."""
        raise_errors = kw.pop("raise_errors", False)
        if not self._ensure_token():
            return None
        url = f"{self.api_base}/crm/v2/{endpoint.lstrip('/')}"
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}", "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        try:
            r = self.session.request(method, url, headers=headers, timeout=60, **kw)
            if r.status_code == 304:
                return None  # Not Modified — no changes since the timestamp
            if r.status_code >= 400:
                body = ""
                try:
                    body = r.text[:300]
                except Exception:
                    pass
                if raise_errors:
                    raise requests.HTTPError(f"{r.status_code}: {body}", response=r)
                logger.error(f"Zoho API {r.status_code} for {endpoint}: {body}")
                return None
            return r.json() if r.status_code != 204 else {"status": "success"}
        except requests.HTTPError:
            raise
        except Exception as e:
            logger.error(f"Zoho API error: {e}")
            return None

    def create_record(self, module: str, data: Dict):
        return self._api_with_headers("POST", module, json={"data": [data]})

    def update_record(self, module: str, record_id: str, data: Dict):
        return self._api_with_headers("PUT", f"{module}/{record_id}", json={"data": [data]})

    def get_modules(self):
        resp = self.api("GET", "settings/modules")
        return resp.get("modules", []) if resp else []

    def get_fields(self, module: str):
        resp = self.api("GET", f"settings/fields?module={module}")
        return resp.get("fields", []) if resp else []

    def test_connection(self) -> bool:
        """Test connection by fetching 1 lead (uses modules.ALL scope)."""
        resp = self.api("GET", "Leads", params={"page": 1, "per_page": 1})
        return resp is not None and "data" in resp

    # ------ COQL (CRM Object Query Language) ------
    def coql_query(self, query: str) -> Optional[Dict]:
        """Execute a COQL query. POST /crm/v2/coql
        Returns: {"data": [...], "info": {"count": N, "more_records": bool}} or None on error.
        Max 200 records per call. Use LIMIT/OFFSET for pagination."""
        if not self._ensure_token():
            return None
        url = f"{self.api_base}/crm/v2/coql"
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}", "Content-Type": "application/json"}
        try:
            r = self.session.post(url, headers=headers, json={"select_query": query}, timeout=60)
            if r.status_code >= 400:
                body = r.text[:300] if r.text else ""
                logger.error(f"COQL error {r.status_code}: {body}")
                return None
            return r.json() if r.status_code != 204 else None
        except Exception as e:
            logger.error(f"COQL request error: {e}")
            return None

    # ------ Related Lists (Visits, Emails) ------
    def get_related_records(self, module: str, record_id: str, related_list: str,
                            page: int = 1, per_page: int = 200):
        """Fetch related list records for a single parent record.
        E.g. GET /crm/v2/Contacts/{id}/Visits_Zoho_Livedesk or /Leads/{id}/Emails
        Returns: list of dicts on success (may be empty), None on API error.
        Handles both 'data' key (standard) and 'email_related_list' key (Emails)."""
        all_recs = []
        pg = page
        while True:
            resp = self._api_with_headers("GET", f"{module}/{record_id}/{related_list}",
                                          params={"page": pg, "per_page": per_page})
            if resp is None:
                # API error (400, 401, network error) — return None to signal failure
                return None if not all_recs else all_recs
            # 204 No Content returns {"status": "success"} — means no records
            if resp.get("status") == "success" and "data" not in resp and "email_related_list" not in resp:
                break
            # Emails endpoint uses 'email_related_list', others use 'data'
            items = resp.get("data") or resp.get("email_related_list")
            if not items:
                break
            all_recs.extend(items)
            if not resp.get("info", {}).get("more_records"):
                break
            pg += 1
            time.sleep(0.15)  # rate limit: ~6-7 req/sec
        return all_recs

    # ------ Bulk Read API (v7) ------
    def bulk_read_create(self, module: str, page: int = 1) -> Optional[str]:
        """Create a bulk read job for a module. Returns job_id."""
        if not self._ensure_token():
            return None
        url = f"{self.api_base}/crm/bulk/v7/read"
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}", "Content-Type": "application/json"}
        body = {
            "query": {
                "module": {"api_name": module},
                "page": page,
            }
        }
        try:
            r = self.session.post(url, headers=headers, json=body, timeout=60)
            r.raise_for_status()
            data = r.json()
            job_id = data.get("data", [{}])[0].get("details", {}).get("id")
            logger.info(f"Bulk read job created for {module}: {job_id}")
            return job_id
        except Exception as e:
            logger.error(f"Bulk read create failed for {module}: {e}")
            return None

    def bulk_read_status(self, job_id: str) -> Optional[Dict]:
        """Check status of a bulk read job."""
        if not self._ensure_token():
            return None
        url = f"{self.api_base}/crm/bulk/v7/read/{job_id}"
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}"}
        try:
            r = self.session.get(url, headers=headers, timeout=60)
            r.raise_for_status()
            data = r.json()
            job = data.get("data", [{}])[0]
            return {
                "state": job.get("state"),
                "result": job.get("result", {}),
            }
        except Exception as e:
            logger.error(f"Bulk read status failed for {job_id}: {e}")
            return None

    def bulk_read_download(self, job_id: str) -> Optional[str]:
        """Download the result CSV of a completed bulk read job. Returns CSV text."""
        if not self._ensure_token():
            return None
        url = f"{self.api_base}/crm/bulk/v7/read/{job_id}/result"
        headers = {"Authorization": f"Zoho-oauthtoken {self.access_token}"}
        try:
            r = self.session.get(url, headers=headers, timeout=120)
            r.raise_for_status()
            # Response can be ZIP or plain CSV
            import zipfile
            if r.content[:4] == b"PK\x03\x04":
                # ZIP file
                buf = io.BytesIO(r.content)
                csv_parts = []
                with zipfile.ZipFile(buf) as zf:
                    for name in zf.namelist():
                        if name.endswith(".csv"):
                            csv_parts.append(zf.read(name).decode("utf-8"))
                csv_text = "\n".join(csv_parts)
            else:
                csv_text = r.content.decode("utf-8")
            return csv_text
        except Exception as e:
            logger.error(f"Bulk read download failed for {job_id}: {e}")
            return None

    def bulk_create_all_jobs(self, modules: List[str]) -> Dict[str, str]:
        """Create bulk read jobs for ALL modules at once (parallel). Returns {module: job_id}."""
        jobs = {}
        for module in modules:
            job_id = self.bulk_read_create(module)
            if job_id:
                jobs[module] = job_id
            time.sleep(0.5)  # small delay between job creation
        logger.info(f"Created {len(jobs)} bulk read jobs")
        return jobs

    def bulk_poll_all(self, jobs: Dict[str, str], max_wait: int = 300) -> Dict[str, str]:
        """Poll all jobs until complete. Returns {module: job_id} for completed jobs."""
        completed = {}
        pending = dict(jobs)
        start = time.time()

        while pending and (time.time() - start) < max_wait:
            for module, job_id in list(pending.items()):
                status = self.bulk_read_status(job_id)
                if not status:
                    continue
                state = status.get("state")
                if state == "COMPLETED":
                    completed[module] = job_id
                    del pending[module]
                    logger.info(f"Bulk job completed: {module}")
                elif state in ("FAILED", "ABORTED", "ERROR"):
                    del pending[module]
                    logger.error(f"Bulk job failed: {module} ({state})")

            if pending:
                elapsed = int(time.time() - start)
                logger.info(f"Bulk poll: {len(completed)} done, {len(pending)} pending ({elapsed}s)")
                time.sleep(10)

        if pending:
            logger.warning(f"Bulk poll timeout: {list(pending.keys())} still pending")
        return completed

    def bulk_download_csv(self, job_id: str) -> List[Dict]:
        """Download bulk job result and parse CSV to list of dicts."""
        csv_text = self.bulk_read_download(job_id)
        if not csv_text:
            return []
        import csv as csv_mod
        reader = csv_mod.DictReader(io.StringIO(csv_text))
        return list(reader)

# Global Zoho client (lazy init)
_zoho_client = None

def get_zoho():
    global _zoho_client
    if _zoho_client is None:
        _zoho_client = ZohoClient()
    return _zoho_client

# ---------------------------------------------------------------------------
# Field mappings (Zoho field -> Postgres column)
# ---------------------------------------------------------------------------
FIELD_MAPPINGS = {
    "leads": {
        "Company": "company", "First_Name": "first_name", "Last_Name": "last_name",
        "Title": "title", "Email": "email", "Phone": "phone", "Mobile": "mobile",
        "Website": "website", "Lead_Source": "lead_source", "Lead_Status": "lead_status",
        "Industry": "industry", "Rating": "rating", "Street": "street", "City": "city",
        "State": "state", "Zip_Code": "zip_code", "Country": "country",
        "Description": "description", "Annual_Revenue": "annual_revenue",
        "No_of_Employees": "number_of_employees",
    },
    "contacts": {
        "First_Name": "first_name", "Last_Name": "last_name", "Title": "title",
        "Email": "email", "Phone": "phone", "Mobile": "mobile",
        "Department": "department", "Account_Name": "account_id",
        "Lead_Source": "lead_source", "Description": "description",
        "Mailing_Street": "mailing_street", "Mailing_City": "mailing_city",
        "Mailing_State": "mailing_state", "Mailing_Zip": "mailing_zip",
        "Mailing_Country": "mailing_country",
    },
    "accounts": {
        "Account_Name": "account_name", "Account_Number": "account_number",
        "Account_Type": "account_type", "Industry": "industry",
        "Annual_Revenue": "annual_revenue", "Phone": "phone", "Website": "website",
        "Description": "description", "Parent_Account": "parent_account_id",
        "Billing_Street": "billing_street", "Billing_City": "billing_city",
        "Billing_State": "billing_state", "Billing_Code": "billing_zip",
        "Billing_Country": "billing_country",
        "Shipping_Street": "shipping_street", "Shipping_City": "shipping_city",
        "Shipping_State": "shipping_state", "Shipping_Code": "shipping_zip",
        "Shipping_Country": "shipping_country",
    },
    "deals": {
        "Deal_Name": "deal_name", "Account_Name": "account_id",
        "Contact_Name": "contact_id", "Pipeline": "pipeline", "Stage": "stage",
        "Amount": "amount", "Closing_Date": "close_date", "Type": "type",
        "Lead_Source": "lead_source", "Next_Step": "next_step",
        "Description": "description", "Probability": "probability",
    },
    "tasks": {
        "Subject": "subject", "Due_Date": "due_date", "Status": "status",
        "Priority": "priority", "Description": "description",
        "What_Id": "related_to_id", "$se_module": "related_to_module",
    },
    "events": {
        "Subject": "subject", "Start_DateTime": "start_datetime",
        "End_DateTime": "end_datetime", "Venue": "venue",
        "All_day": "all_day", "Description": "description",
    },
    "calls": {
        "Subject": "subject", "Call_Status": "call_status", "Call_Type": "call_type",
        "Call_Duration": "call_duration", "Call_Start_Time": "call_start_time",
        "Call_End_Time": "call_end_time", "Description": "description",
        "Who_Id": "contact_id", "What_Id": "related_to_id",
    },
    "notes": {
        "Note_Title": "note_title", "Note_Content": "note_content",
        "Parent_Id": "parent_id", "$se_module": "parent_module",
    },
    "products": {
        "Product_Name": "product_name", "Product_Code": "product_code",
        "Product_Active": "product_active", "Unit_Price": "unit_price",
        "Description": "description", "Tax": "tax",
        "Manufacturer": "manufacturer", "Category": "category",
    },
    "vendors": {
        "Vendor_Name": "vendor_name", "Phone": "phone", "Email": "email",
        "Website": "website", "Category": "category",
        "Street": "street", "City": "city", "State": "state",
        "Zip_Code": "zip_code", "Country": "country", "Description": "description",
    },
    "price_books": {
        "Price_Book_Name": "price_book_name", "Active": "active",
        "Description": "description",
    },
    "quotes": {
        "Quote_Stage": "quote_stage", "Subject": "subject",
        "Account_Name": "account_id", "Contact_Name": "contact_id",
        "Deal_Name": "deal_id", "Quote_Date": "quote_date",
        "Valid_Till": "valid_until", "Grand_Total": "grand_total",
        "Description": "description", "Terms_and_Conditions": "terms_and_conditions",
    },
    "sales_orders": {
        "Subject": "sales_order_name", "Account_Name": "account_id",
        "Contact_Name": "contact_id", "Deal_Name": "deal_id",
        "Quote_Name": "quote_id", "Status": "status",
        "Order_Date": "order_date", "Due_Date": "due_date",
        "Grand_Total": "grand_total", "Description": "description",
        "Terms_and_Conditions": "terms_and_conditions",
    },
    "purchase_orders": {
        "Subject": "purchase_order_name", "Vendor_Name": "vendor_id",
        "Status": "status", "Order_Date": "order_date",
        "Due_Date": "due_date", "Grand_Total": "grand_total",
        "Description": "description", "Terms_and_Conditions": "terms_and_conditions",
    },
    "invoices": {
        "Subject": "subject", "Account_Name": "account_id",
        "Contact_Name": "contact_id", "Deal_Name": "deal_id",
        "Sales_Order": "sales_order_id", "Invoice_Date": "invoice_date",
        "Due_Date": "due_date", "Grand_Total": "grand_total",
        "Status": "status", "Description": "description",
        "Terms_and_Conditions": "terms_and_conditions",
    },
    "campaigns": {
        "Campaign_Name": "campaign_name", "Type": "campaign_type",
        "Status": "status", "Start_Date": "start_date", "End_Date": "end_date",
        "Expected_Revenue": "expected_revenue", "Actual_Cost": "actual_cost",
        "Description": "description",
    },
    "cases": {
        "Case_Origin": "case_origin", "Status": "status", "Priority": "priority",
        "Subject": "subject", "Account_Name": "account_id",
        "Contact_Name": "contact_id", "Case_Reason": "case_reason",
        "Description": "description", "Internal_Comments": "internal_comments",
    },
    "solutions": {
        "Solution_Title": "solution_title", "Solution_Number": "solution_number",
        "Status": "status", "Question": "question", "Answer": "answer",
    },
    # Custom modules
    "client_leads": {
        "Name": "project_name", "Client_Name": "client_name",
        "Project_Value": "project_value", "Expected_Start_Date": "expected_start_date",
        "Status": "status", "Description": "description",
    },
    "projects_tender": {
        "Tender_Name": "tender_name", "Tender_Value": "tender_value",
        "Submission_Date": "submission_date", "Status": "status",
        "Description": "description",
    },
    "projects_contracts": {
        "Contract_Name": "contract_name", "Contract_Value": "contract_value",
        "Start_Date": "start_date", "End_Date": "end_date",
        "Status": "status", "Description": "description",
    },
}

# Reverse mappings (postgres -> zoho)
REVERSE_MAPPINGS = {}
for tbl, mapping in FIELD_MAPPINGS.items():
    REVERSE_MAPPINGS[tbl] = {v: k for k, v in mapping.items()}

# ---------------------------------------------------------------------------
# Sync state (in-memory, thread-safe)
# ---------------------------------------------------------------------------
sync_state = {
    "running": False,
    "direction": None,
    "module": None,
    "progress": 0,
    "message": "",
    "started_at": None,
    "completed_at": None,
    "results": {},
    "errors": [],
}
sync_lock = threading.Lock()


def _is_sync_running():
    """Check if sync is actually running — auto-reset if stale (>30 min)."""
    with sync_lock:
        if not sync_state["running"]:
            return False
        started = sync_state.get("started_at")
        if started:
            try:
                started_dt = datetime.fromisoformat(started)
                if (datetime.now() - started_dt).total_seconds() > 1800:
                    logger.warning(f"Auto-resetting stale sync lock (started {started})")
                    sync_state["running"] = False
                    sync_state["message"] = "Auto-reset: stale lock"
                    return False
            except (ValueError, TypeError):
                pass
        return True


# ---------------------------------------------------------------------------
# Automatic Sync Scheduler (Zoho -> PostgreSQL)
# ---------------------------------------------------------------------------
AUTO_SYNC_INTERVAL = int(os.environ.get("AUTO_SYNC_INTERVAL_MINUTES", "60"))
auto_sync_state = {
    "enabled": os.environ.get("AUTO_SYNC_ENABLED", "true").lower() == "true",
    "interval_minutes": AUTO_SYNC_INTERVAL,
    "last_sync": None,
    "next_sync": None,
    "running": False,
    "last_result": None,
}
auto_sync_lock = threading.Lock()


def auto_sync_worker():
    """Background thread: periodically pull all modules from Zoho to PostgreSQL.
    Uses sync_metadata table for per-module timestamps with 5-min overlap.
    Zoho CRM updated fields always take priority."""
    logger.info(f"Auto-sync scheduler started (interval: {AUTO_SYNC_INTERVAL}m)")

    # Wait 60s after startup to let gunicorn workers fully initialize
    time.sleep(60)

    # Use a file lock so only one gunicorn worker runs auto-sync
    import fcntl
    lock_path = "/tmp/.auto_sync_lock"
    try:
        _lock_fd = open(lock_path, "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        logger.info("Auto-sync: another worker holds the lock, exiting this thread")
        return

    # Ensure sync tables exist on first run
    try:
        ensure_sync_tables()
    except Exception as e:
        logger.warning(f"Auto-sync: ensure_sync_tables failed: {e}")
    try:
        ensure_related_tables()
    except Exception as e:
        logger.warning(f"Auto-sync: ensure_related_tables failed: {e}")

    while True:
        with auto_sync_lock:
            if not auto_sync_state["enabled"]:
                time.sleep(60)
                continue

        # Skip if a manual or bulk sync is already running
        with sync_lock:
            if sync_state["running"]:
                logger.info("Auto-sync: manual/bulk sync in progress, skipping this cycle")
                time.sleep(60)
                continue

        with auto_sync_lock:
            auto_sync_state["running"] = True
            auto_sync_state["last_sync"] = datetime.now().isoformat()

        cycle_start = time.time()
        logger.info(f"Auto-sync: starting incremental pull ({len(MODULE_TABLE_MAP)} modules)...")
        try:
            results = do_pull_sync(modified_since="auto")

            # After module sync, do incremental email import via COQL
            try:
                email_res = _import_emails_coql_incremental(minutes_back=90)
                if email_res.get("total_items", 0) > 0:
                    results["_emails_coql"] = email_res
            except Exception as e:
                logger.warning(f"Auto-sync email import: {e}")

            try:
                visits_res = _import_related_list_incremental(
                    "Visits_Zoho_Livedesk", _upsert_visit, "visits_auto",
                    parent_modules=["Contacts"])
                if visits_res.get("total_items", 0) > 0:
                    results["_visits_related"] = visits_res
            except Exception as e:
                logger.warning(f"Auto-sync visits import: {e}")

            # Build summary
            total_records = sum(r.get("total", 0) for r in results.values() if isinstance(r.get("total"), int))
            total_errors = sum(r.get("errors", 0) for r in results.values())
            modules_with_data = [m for m, r in results.items() if r.get("total", 0) > 0 or r.get("total_items", 0) > 0]
            cycle_dur = time.time() - cycle_start

            with auto_sync_lock:
                auto_sync_state["last_result"] = results
                auto_sync_state["running"] = False
                auto_sync_state["next_sync"] = (
                    datetime.now() + timedelta(minutes=AUTO_SYNC_INTERVAL)
                ).isoformat()

            if total_records > 0:
                detail = ", ".join(f"{m}:{results[m]['total']}" for m in modules_with_data)
                logger.info(f"Auto-sync done: {total_records} records across "
                            f"{len(modules_with_data)} modules in {cycle_dur:.1f}s ({detail})")
            else:
                logger.info(f"Auto-sync done: no changes detected in {cycle_dur:.1f}s")

            if total_errors > 0:
                logger.warning(f"Auto-sync: {total_errors} errors in this cycle")

        except Exception as e:
            logger.error(f"Auto-sync error: {e}")
            with auto_sync_lock:
                auto_sync_state["running"] = False
                auto_sync_state["last_result"] = {"error": str(e)}
                auto_sync_state["next_sync"] = (
                    datetime.now() + timedelta(minutes=AUTO_SYNC_INTERVAL)
                ).isoformat()

        # Sleep for the configured interval
        time.sleep(AUTO_SYNC_INTERVAL * 60)


# Start the auto-sync thread on import (Cloud Run will keep it alive)
_auto_sync_thread = None


def start_auto_sync():
    global _auto_sync_thread
    if _auto_sync_thread is None or not _auto_sync_thread.is_alive():
        _auto_sync_thread = threading.Thread(target=auto_sync_worker, daemon=True, name="auto-sync")
        _auto_sync_thread.start()
        logger.info("Auto-sync background thread launched")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def serialize(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, (dict, list)):
        return val
    return val

def get_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
        ORDER BY table_name
    """)
    tables = [r["table_name"] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return tables

def get_columns(table_name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
    """, (table_name,))
    cols = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return cols

def get_pk(table_name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
        WHERE i.indrelid=%s::regclass AND i.indisprimary
    """, (table_name,))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r["attname"] if r else None

def has_column(table_name, col_name):
    cols = get_columns(table_name)
    return any(c["column_name"] == col_name for c in cols)

def table_valid(table_name):
    return table_name in get_tables()


def ensure_sync_tables():
    """Create/migrate sync_metadata and sync_jobs tables, seed metadata rows."""
    conn = get_db()
    cur = conn.cursor()
    try:
        # Drop and recreate sync_metadata with correct schema (UNIQUE on table_name)
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='sync_metadata'")
        has_sm = cur.fetchone()
        if has_sm:
            # Check if UNIQUE constraint exists on table_name
            cur.execute("""
                SELECT 1 FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu USING (constraint_name)
                WHERE tc.table_name='sync_metadata' AND tc.constraint_type='UNIQUE'
                  AND ccu.column_name='table_name'
            """)
            if not cur.fetchone():
                # Add missing UNIQUE constraint and error_message column
                cur.execute("DELETE FROM sync_metadata WHERE table_name IN (SELECT table_name FROM sync_metadata GROUP BY table_name HAVING COUNT(*) > 1)")
                cur.execute("ALTER TABLE sync_metadata ADD CONSTRAINT sync_metadata_table_name_key UNIQUE (table_name)")
                conn.commit()
            # Add missing columns if needed
            for col_name, col_type in [
                ("error_message", "TEXT"),
                ("records_synced", "INTEGER DEFAULT 0"),
                ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP"),
            ]:
                cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='sync_metadata' AND column_name=%s", (col_name,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE sync_metadata ADD COLUMN {col_name} {col_type}")
            conn.commit()
        else:
            cur.execute("""
                CREATE TABLE sync_metadata (
                    id SERIAL PRIMARY KEY,
                    table_name VARCHAR(100) NOT NULL UNIQUE,
                    last_sync_timestamp TIMESTAMP WITH TIME ZONE,
                    sync_direction VARCHAR(20) DEFAULT 'zoho_to_db',
                    sync_status VARCHAR(20) DEFAULT 'idle',
                    records_synced INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

        # Create sync_jobs if not exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sync_jobs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                job_type VARCHAR(50) NOT NULL,
                direction VARCHAR(20) DEFAULT 'pull',
                module_name VARCHAR(100),
                status VARCHAR(20) DEFAULT 'pending',
                total_records INTEGER DEFAULT 0,
                created_records INTEGER DEFAULT 0,
                updated_records INTEGER DEFAULT 0,
                failed_records INTEGER DEFAULT 0,
                processed_records INTEGER DEFAULT 0,
                error_message TEXT,
                error_details TEXT,
                duration_seconds NUMERIC,
                retry_count INTEGER DEFAULT 0,
                started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Migrate sync_jobs check constraint to include new job types
        try:
            cur.execute("""
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE table_name='sync_jobs' AND constraint_type='CHECK'
            """)
            check_constraints = [r["constraint_name"] for r in cur.fetchall()]
            for cname in check_constraints:
                if "job_type" in cname:
                    cur.execute(f"ALTER TABLE sync_jobs DROP CONSTRAINT {cname}")
                    cur.execute("""
                        ALTER TABLE sync_jobs ADD CONSTRAINT sync_jobs_job_type_check
                        CHECK (job_type IN (
                            'full_sync', 'incremental_sync', 'module_sync', 'record_sync',
                            'email_tracking_import', 'visits_import', 'email_auto', 'visits_auto',
                            'bulk_pull', 'push'
                        ))
                    """)
                    logger.info(f"Migrated sync_jobs CHECK constraint: dropped {cname}, added expanded check")
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.debug(f"sync_jobs constraint migration (may already be correct): {e}")

        # Seed sync_metadata with a row per module (if missing)
        for module, table in MODULE_TABLE_MAP.items():
            cur.execute("""
                INSERT INTO sync_metadata (table_name, sync_direction, sync_status)
                VALUES (%s, 'zoho_to_db', 'idle')
                ON CONFLICT (table_name) DO NOTHING
            """, (table,))
        conn.commit()

        # Seed last_sync_timestamp from existing data (for first run after bulk import)
        for module, table in MODULE_TABLE_MAP.items():
            try:
                cur.execute(f"SELECT MAX(last_sync_at) as max_ts FROM {table} WHERE last_sync_at IS NOT NULL")
                row = cur.fetchone()
                if row and row.get("max_ts"):
                    cur.execute("""
                        UPDATE sync_metadata SET last_sync_timestamp = %s
                        WHERE table_name = %s AND last_sync_timestamp IS NULL
                    """, (row["max_ts"], table))
            except Exception:
                conn.rollback()
        conn.commit()
        logger.info("sync_metadata and sync_jobs tables ensured")
    except Exception as e:
        conn.rollback()
        logger.warning(f"ensure_sync_tables: {e}")
    finally:
        cur.close()
        conn.close()


def ensure_related_tables():
    """Create/migrate visits and email_tracking tables.
    Handles the case where visits already exists from bulk import (different schema)."""
    conn = get_db()
    cur = conn.cursor()
    try:
        # ── visits: add parent tracking columns to existing table ──
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='visits'")
        if cur.fetchone():
            # Table exists (from bulk import) — add missing columns
            for col, ctype in [
                ("parent_module", "VARCHAR(50)"),
                ("parent_zoho_id", "VARCHAR(100)"),
            ]:
                cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='visits' AND column_name=%s", (col,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE visits ADD COLUMN {col} {ctype}")
            conn.commit()
            # Backfill parent_module from existing _se_module column if available
            cur.execute("""
                UPDATE visits SET parent_module = LOWER(_se_module)
                WHERE parent_module IS NULL AND _se_module IS NOT NULL
            """)
            conn.commit()
        cur.execute("CREATE INDEX IF NOT EXISTS idx_visits_parent ON visits(parent_module, parent_zoho_id)")
        conn.commit()

        # ── email_tracking: create if not exists ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS email_tracking (
                id SERIAL PRIMARY KEY,
                zoho_id VARCHAR(100) UNIQUE,
                parent_module VARCHAR(50),
                parent_zoho_id VARCHAR(100),
                subject TEXT,
                from_email VARCHAR(255),
                to_email VARCHAR(255),
                status VARCHAR(50),
                open_count INTEGER DEFAULT 0,
                first_open TIMESTAMP WITH TIME ZONE,
                last_open TIMESTAMP WITH TIME ZONE,
                click_count INTEGER DEFAULT 0,
                bounce_type VARCHAR(50),
                sent_time TIMESTAMP WITH TIME ZONE,
                category VARCHAR(50),
                zoho_created_time TIMESTAMP WITH TIME ZONE,
                zoho_modified_time TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                last_sync_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_email_tracking_parent ON email_tracking(parent_module, parent_zoho_id)")
        conn.commit()
        logger.info("visits and email_tracking tables ensured")
    except Exception as e:
        conn.rollback()
        logger.warning(f"ensure_related_tables: {e}")
    finally:
        cur.close()
        conn.close()


SYNC_OVERLAP_SECONDS = 300  # 5 minutes overlap to avoid missing boundary records


def _get_last_sync_ts(table: str) -> str | None:
    """Get last sync timestamp for a module from sync_metadata, minus overlap buffer.
    Falls back to MAX(last_sync_at) from the table if sync_metadata has no entry.
    Returns ISO 8601 string or None (meaning full pull)."""
    conn = get_db()
    cur = conn.cursor()
    try:
        # Try sync_metadata first
        cur.execute("SELECT last_sync_timestamp FROM sync_metadata WHERE table_name = %s", (table,))
        row = cur.fetchone()
        if row and row.get("last_sync_timestamp"):
            ts = row["last_sync_timestamp"] - timedelta(seconds=SYNC_OVERLAP_SECONDS)
            return ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")

        # Fallback: derive from table data
        cur.execute(f"SELECT MAX(last_sync_at) as max_ts FROM {table} WHERE last_sync_at IS NOT NULL")
        row = cur.fetchone()
        if row and row.get("max_ts"):
            ts = row["max_ts"] - timedelta(seconds=SYNC_OVERLAP_SECONDS)
            return ts.strftime("%Y-%m-%dT%H:%M:%S+00:00")

        return None
    except Exception:
        return None
    finally:
        cur.close()
        conn.close()


def _update_sync_metadata(table: str, records_synced: int, status: str = "idle", error: str = None):
    """Update sync_metadata row after a module sync completes or fails."""
    conn = get_db()
    cur = conn.cursor()
    try:
        if status == "error":
            cur.execute("""
                UPDATE sync_metadata
                SET sync_status = %s, error_message = %s, updated_at = NOW()
                WHERE table_name = %s
            """, (status, error, table))
        else:
            cur.execute("""
                UPDATE sync_metadata
                SET last_sync_timestamp = NOW(), records_synced = %s,
                    sync_status = %s, error_message = NULL, updated_at = NOW()
                WHERE table_name = %s
            """, (records_synced, status, table))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning(f"_update_sync_metadata({table}): {e}")
    finally:
        cur.close()
        conn.close()


def _create_sync_job(job_type: str = "incremental_sync", direction: str = "pull") -> str | None:
    """Insert a new sync_jobs row, return its UUID."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO sync_jobs (job_type, direction, status, started_at)
            VALUES (%s, %s, 'running', NOW())
            RETURNING id
        """, (job_type, direction))
        job_id = cur.fetchone()["id"]
        conn.commit()
        return str(job_id)
    except Exception as e:
        conn.rollback()
        logger.warning(f"_create_sync_job: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def _complete_sync_job(job_id: str, total: int, created: int, updated: int, failed: int,
                       status: str = "completed", error: str = None, duration: float = None):
    """Mark a sync_jobs row as completed or failed."""
    if not job_id:
        return
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE sync_jobs
            SET status = %s, total_records = %s, created_records = %s,
                updated_records = %s, failed_records = %s, processed_records = %s,
                error_message = %s, duration_seconds = %s,
                completed_at = NOW(), updated_at = NOW()
            WHERE id = %s::uuid
        """, (status, total, created, updated, failed, total, error, duration, job_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning(f"_complete_sync_job: {e}")
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# SYNC ENGINE (embedded)
# ---------------------------------------------------------------------------
def zoho_record_to_pg(record: Dict, table_name: str) -> Dict:
    """Map a Zoho CRM record to PostgreSQL columns."""
    mapping = FIELD_MAPPINGS.get(table_name, {})
    row = {}
    row["zoho_id"] = record.get("id")

    # Owner
    owner = record.get("Owner", {})
    if isinstance(owner, dict):
        row["owner_id"] = owner.get("id")
        row["owner_name"] = owner.get("name")

    # Mapped fields
    for zoho_field, pg_col in mapping.items():
        val = record.get(zoho_field)
        if val is not None:
            # Handle lookup fields (dict with id/name)
            if isinstance(val, dict) and "id" in val:
                if pg_col.endswith("_id"):
                    row[pg_col] = val["id"]
                elif pg_col.endswith("_name"):
                    row[pg_col] = val.get("name")
                else:
                    row[pg_col] = val.get("name") or val.get("id")
            else:
                row[pg_col] = val

    # Timestamps
    ct = record.get("Created_Time")
    mt = record.get("Modified_Time")
    if ct:
        row["zoho_created_time"] = ct
    if mt:
        row["zoho_modified_time"] = mt

    cb = record.get("Created_By", {})
    mb = record.get("Modified_By", {})
    if isinstance(cb, dict):
        row["zoho_created_by"] = cb.get("id")
    if isinstance(mb, dict):
        row["zoho_modified_by"] = mb.get("id")

    # Custom fields
    custom = {}
    standard_keys = set(["id", "Owner", "Created_Time", "Modified_Time",
                         "Created_By", "Modified_By", "$currency_symbol",
                         "$state", "$process_flow", "$approved", "$approval",
                         "$editable", "$review_process", "$review", "$orchestration",
                         "$in_merge", "$approval_state"])
    standard_keys.update(mapping.keys())
    for k, v in record.items():
        if k not in standard_keys and not k.startswith("$"):
            custom[k] = v
    if custom:
        row["custom_fields"] = json.dumps(custom, default=str)

    return row

def pg_record_to_zoho(record: Dict, table_name: str) -> Dict:
    """Map PostgreSQL record to Zoho CRM API format.
    Only sends standard mapped fields (real PG columns that changed).
    Does NOT send custom_fields JSON back — that's a mirror of Zoho data
    and pushing it back causes validation errors with read-only/special fields."""
    rev = REVERSE_MAPPINGS.get(table_name, {})
    zoho_data = {}

    # Only push standard mapped fields (pg column -> Zoho API name)
    for pg_col, zoho_field in rev.items():
        val = record.get(pg_col)
        if val is not None:
            if isinstance(val, datetime):
                zoho_data[zoho_field] = val.strftime("%Y-%m-%d") if "date" in pg_col.lower() else val.isoformat()
            elif isinstance(val, bool):
                zoho_data[zoho_field] = val
            else:
                zoho_data[zoho_field] = val

    return zoho_data

def _upsert_records_to_pg(table, records_mapped, label=""):
    """Fast batch upsert using execute_values + INSERT ON CONFLICT. Returns (inserted, 0, errors)."""
    if not records_mapped:
        return 0, 0, 0

    conn = get_db()
    cur = conn.cursor()
    cols_info = get_columns(table)
    valid_cols = {c["column_name"] for c in cols_info}
    now = datetime.now()
    batch_size = 2000
    total = 0
    errors = 0

    # Collect ALL possible columns across all records
    all_keys = set()
    for rec in records_mapped:
        all_keys.update(rec.keys())
    all_keys.update(["updated_at", "last_sync_at", "sync_status"])
    cols = sorted([k for k in all_keys if k in valid_cols])

    if "zoho_id" not in cols:
        logger.error(f"  {label}: zoho_id not in valid columns, cannot upsert")
        cur.close()
        conn.close()
        return 0, 0, len(records_mapped)

    col_str = ", ".join(cols)
    update_cols = [c for c in cols if c not in ("zoho_id", "id", "created_at")]
    update_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    # Template for execute_values: (%s, %s, ...)
    tpl = "(" + ", ".join(["%s"] * len(cols)) + ")"

    sql_base = (
        f"INSERT INTO {table} ({col_str}) VALUES %s "
        f"ON CONFLICT (zoho_id) DO UPDATE SET {update_str}"
    )

    for batch_start in range(0, len(records_mapped), batch_size):
        batch = records_mapped[batch_start:batch_start + batch_size]
        batch_vals = []

        for rec in batch:
            if not rec.get("zoho_id"):
                errors += 1
                continue
            rec["updated_at"] = now
            rec["last_sync_at"] = now
            rec["sync_status"] = "synced"
            batch_vals.append(tuple(rec.get(c) for c in cols))

        if not batch_vals:
            continue

        try:
            psycopg2.extras.execute_values(cur, sql_base, batch_vals, template=tpl, page_size=2000)
            total += len(batch_vals)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"  {label}: Batch failed ({e}), retrying per-row...")
            for row in batch_vals:
                try:
                    cur.execute(
                        f"INSERT INTO {table} ({col_str}) VALUES {tpl} "
                        f"ON CONFLICT (zoho_id) DO UPDATE SET {update_str}",
                        row
                    )
                    conn.commit()
                    total += 1
                except Exception:
                    conn.rollback()
                    errors += 1

        if label:
            done = min(batch_start + batch_size, len(records_mapped))
            logger.info(f"  {label}: {done:,}/{len(records_mapped):,} done ({total:,} ok, {errors} err)")

    cur.close()
    conn.close()
    return total, 0, errors


def _bulk_csv_record_to_pg(csv_row: Dict, table_name: str) -> Dict:
    """Map a bulk-read CSV row to PostgreSQL columns.
    Bulk CSV uses the same Zoho API field names as column headers."""
    mapping = FIELD_MAPPINGS.get(table_name, {})
    row = {}

    # The CSV uses 'Record Id' (not 'id') as the Zoho record identifier
    row["zoho_id"] = csv_row.get("Record Id") or csv_row.get("id") or csv_row.get("Id")

    # Owner
    owner_id = csv_row.get("Owner") or csv_row.get("Owner.id")
    owner_name = csv_row.get("Owner.name")
    if owner_id:
        row["owner_id"] = owner_id
    if owner_name:
        row["owner_name"] = owner_name

    # Mapped fields - bulk CSV headers match Zoho API names
    for zoho_field, pg_col in mapping.items():
        val = csv_row.get(zoho_field, "")
        if val and val != "":
            # Bulk CSV returns lookup IDs as separate columns: "Account_Name" and "Account_Name.id"
            if pg_col.endswith("_id"):
                # Prefer the .id column if available
                id_val = csv_row.get(f"{zoho_field}.id", "") or csv_row.get(zoho_field, "")
                if id_val and id_val != "":
                    row[pg_col] = id_val
            else:
                row[pg_col] = val

    # Timestamps
    ct = csv_row.get("Created Time") or csv_row.get("Created_Time")
    mt = csv_row.get("Modified Time") or csv_row.get("Modified_Time")
    if ct and ct != "":
        row["zoho_created_time"] = ct
    if mt and mt != "":
        row["zoho_modified_time"] = mt

    cb = csv_row.get("Created By") or csv_row.get("Created_By") or csv_row.get("Created By.id")
    mb = csv_row.get("Modified By") or csv_row.get("Modified_By") or csv_row.get("Modified By.id")
    if cb and cb != "":
        row["zoho_created_by"] = cb
    if mb and mb != "":
        row["zoho_modified_by"] = mb

    # Custom fields: everything not in standard mapping
    custom = {}
    standard_keys = {"Record Id", "Id", "id", "Owner", "Owner.id", "Owner.name",
                     "Created Time", "Created_Time", "Modified Time", "Modified_Time",
                     "Created By", "Created_By", "Created By.id", "Modified By",
                     "Modified_By", "Modified By.id"}
    for z_field in mapping.keys():
        standard_keys.add(z_field)
        standard_keys.add(f"{z_field}.id")
        standard_keys.add(f"{z_field}.name")
    for k, v in csv_row.items():
        if k not in standard_keys and not k.startswith("$") and v and v != "":
            custom[k] = v
    if custom:
        row["custom_fields"] = json.dumps(custom, default=str)

    return row


def _bulk_copy_import(table, csv_text, label=""):
    """Ultra-fast bulk import: COPY CSV into staging table, then SQL merge into target.
    Casts TEXT staging columns to target column types automatically.
    Returns (count, 0, errors)."""
    import csv as csv_mod

    conn = get_db()
    cur = conn.cursor()
    mapping = FIELD_MAPPINGS.get(table, {})

    # Parse CSV headers only (first line)
    header_line = csv_text[:csv_text.index('\n')]
    reader = csv_mod.reader(io.StringIO(header_line))
    csv_cols = next(reader)
    logger.info(f"  {label}: CSV has {len(csv_cols)} columns")

    # Create staging table with TEXT columns matching CSV headers
    stg = f"_stg_{table}"
    cur.execute(f"DROP TABLE IF EXISTS {stg}")
    col_defs = ", ".join(f'"{c}" TEXT' for c in csv_cols)
    cur.execute(f"CREATE TEMP TABLE {stg} ({col_defs})")
    conn.commit()

    # COPY raw CSV into staging (skip header line)
    csv_body = csv_text[csv_text.index('\n') + 1:]
    buf = io.StringIO(csv_body)
    cols_quoted = ", ".join(f'"{c}"' for c in csv_cols)
    cur.copy_expert(
        f"COPY {stg} ({cols_quoted}) FROM STDIN WITH (FORMAT csv, NULL '')",
        buf
    )
    conn.commit()
    cur.execute(f"SELECT COUNT(*) as cnt FROM {stg}")
    stg_count = cur.fetchone()["cnt"]
    logger.info(f"  {label}: {stg_count:,} rows loaded into staging")

    # Build target column type map for casting
    target_cols = get_columns(table)
    target_col_types = {c["column_name"]: c["data_type"] for c in target_cols}
    target_col_names = set(target_col_types.keys())

    def _cast(expr, pg_col):
        """Wrap expr with cast to match target column type."""
        dtype = target_col_types.get(pg_col, "text")
        if dtype in ("integer", "bigint", "smallint"):
            return f"CASE WHEN {expr} ~ '^[0-9]+$' THEN ({expr})::bigint ELSE NULL END"
        elif dtype in ("numeric", "double precision", "real"):
            return f"CASE WHEN {expr} ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN ({expr})::numeric ELSE NULL END"
        elif dtype == "date":
            return f"CASE WHEN {expr} != '' THEN ({expr})::date ELSE NULL END"
        elif dtype in ("timestamp without time zone", "timestamp with time zone"):
            return f"CASE WHEN {expr} != '' THEN ({expr})::timestamp ELSE NULL END"
        elif dtype == "boolean":
            return f"CASE WHEN {expr} IN ('true','1','yes') THEN true WHEN {expr} IN ('false','0','no') THEN false ELSE NULL END"
        elif dtype == "jsonb":
            return f"CASE WHEN {expr} != '' THEN ({expr})::jsonb ELSE NULL END"
        else:
            return f"NULLIF({expr}, '')"

    select_parts = []
    insert_cols = []

    # zoho_id (required)
    id_csv = "Record Id" if "Record Id" in csv_cols else ("Id" if "Id" in csv_cols else None)
    if not id_csv:
        logger.error(f"  {label}: no Record Id / Id column in CSV!")
        cur.execute(f"DROP TABLE IF EXISTS {stg}")
        conn.commit()
        cur.close()
        conn.close()
        return 0, 0, stg_count
    select_parts.append(f'"{id_csv}"')
    insert_cols.append("zoho_id")

    # Owner fields
    if "owner_id" in target_col_names and "Owner" in csv_cols:
        select_parts.append(_cast('COALESCE("Owner", NULL)', "owner_id"))
        insert_cols.append("owner_id")
    if "owner_name" in target_col_names and "Owner.name" in csv_cols:
        select_parts.append(_cast('"Owner.name"', "owner_name"))
        insert_cols.append("owner_name")

    # Mapped fields from FIELD_MAPPINGS
    for zoho_field, pg_col in mapping.items():
        if pg_col not in target_col_names or pg_col in insert_cols:
            continue
        if pg_col.endswith("_id"):
            id_col = f"{zoho_field}.id"
            if id_col in csv_cols:
                expr = f'COALESCE(NULLIF("{id_col}", \'\'), NULLIF("{zoho_field}", \'\'))'
            elif zoho_field in csv_cols:
                expr = f'NULLIF("{zoho_field}", \'\')'
            else:
                continue
        else:
            if zoho_field in csv_cols:
                expr = f'NULLIF("{zoho_field}", \'\')'
            else:
                continue
        select_parts.append(_cast(expr, pg_col))
        insert_cols.append(pg_col)

    # Timestamps
    for csv_name, pg_name in [("Created Time", "zoho_created_time"), ("Modified Time", "zoho_modified_time")]:
        if pg_name in target_col_names and csv_name in csv_cols:
            select_parts.append(_cast(f'NULLIF("{csv_name}", \'\')', pg_name))
            insert_cols.append(pg_name)
    for csv_name, pg_name in [("Created By", "zoho_created_by"), ("Modified By", "zoho_modified_by")]:
        if pg_name not in target_col_names:
            continue
        id_variant = f"{csv_name}.id"
        if id_variant in csv_cols:
            select_parts.append(_cast(f'COALESCE(NULLIF("{id_variant}", \'\'), NULLIF("{csv_name}", \'\'))', pg_name))
        elif csv_name in csv_cols:
            select_parts.append(_cast(f'NULLIF("{csv_name}", \'\')', pg_name))
        else:
            continue
        insert_cols.append(pg_name)

    # Metadata columns
    now_str = datetime.now().isoformat()
    select_parts.append(f"'{now_str}'::timestamp")
    insert_cols.append("updated_at")
    select_parts.append(f"'{now_str}'::timestamp")
    insert_cols.append("last_sync_at")
    select_parts.append("'synced'")
    insert_cols.append("sync_status")

    # Build and execute the merge SQL
    insert_col_str = ", ".join(insert_cols)
    select_str = ", ".join(select_parts)
    update_cols = [c for c in insert_cols if c not in ("zoho_id", "id", "created_at")]
    update_str = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    where_clause = f'"{id_csv}" IS NOT NULL AND "{id_csv}" != \'\''
    merge_sql = (
        f"INSERT INTO {table} ({insert_col_str}) "
        f"SELECT {select_str} FROM {stg} WHERE {where_clause} "
        f"ON CONFLICT (zoho_id) DO UPDATE SET {update_str}"
    )

    try:
        cur.execute(merge_sql)
        merged = cur.rowcount
        conn.commit()
        logger.info(f"  {label}: {merged:,} records merged into {table}")
    except Exception as e:
        conn.rollback()
        logger.error(f"  {label}: merge failed: {e}")
        merged = 0

    # Cleanup
    cur.execute(f"DROP TABLE IF EXISTS {stg}")
    conn.commit()
    cur.close()
    conn.close()
    return merged, 0, 0


def do_bulk_pull_sync(modules=None):
    """Pull ALL records from Zoho CRM using Bulk Read API.
    Phase 1: Create jobs for ALL modules at once.
    Phase 2: Poll all jobs until complete.
    Phase 3: Download CSV and COPY+merge into DB (ultra-fast, no Python per-row).
    """
    global sync_state
    zoho = get_zoho()
    modules = modules or list(MODULE_TABLE_MAP.keys())
    results = {}

    # Phase 1: Create all jobs at once
    with sync_lock:
        sync_state["message"] = f"Phase 1: Creating bulk jobs for {len(modules)} modules..."
        sync_state["progress"] = 5
    jobs = zoho.bulk_create_all_jobs(modules)
    if not jobs:
        logger.error("No bulk read jobs created")
        return results

    # Phase 2: Poll all jobs (max 5 min)
    with sync_lock:
        sync_state["message"] = f"Phase 2: Waiting for {len(jobs)} jobs to complete..."
        sync_state["progress"] = 15
    completed = zoho.bulk_poll_all(jobs, max_wait=300)

    # Phase 3: Download and COPY+merge one module at a time
    total_modules = len(completed)
    logger.info(f"Phase 2 done: {total_modules} modules ready: {list(completed.keys())}")
    sys.stdout.flush()

    for i, (module, job_id) in enumerate(completed.items()):
        table = MODULE_TABLE_MAP.get(module)
        if not table:
            continue

        pct = 40 + int((i / max(total_modules, 1)) * 55)
        with sync_lock:
            sync_state["module"] = module
            sync_state["progress"] = pct
            sync_state["message"] = f"[{i+1}/{total_modules}] Importing {module}..."
        logger.info(f"Phase 3 [{i+1}/{total_modules}]: {module} (job {job_id})...")
        sys.stdout.flush()

        try:
            t0 = time.time()
            csv_text = zoho.bulk_read_download(job_id)
            if not csv_text:
                logger.info(f"  {module}: empty result, skipping")
                results[module] = {"total": 0, "created": 0, "updated": 0, "errors": 0, "method": "bulk"}
                continue

            dl_time = time.time() - t0
            logger.info(f"  {module}: downloaded {len(csv_text):,} bytes in {dl_time:.1f}s")

            t1 = time.time()
            created, updated, errors = _bulk_copy_import(table, csv_text, module)
            imp_time = time.time() - t1

            # Count lines for total
            total_csv = csv_text.count('\n')
            csv_text = None

            results[module] = {"total": total_csv, "created": created, "updated": updated, "errors": errors, "method": "bulk-copy"}
            logger.info(f"  {module}: {created:,} records in {imp_time:.1f}s (download {dl_time:.1f}s)")

        except Exception as e:
            results[module] = {"total": 0, "created": 0, "updated": 0, "errors": 1, "error": str(e)}
            logger.error(f"Failed to bulk pull {module}: {e}", exc_info=True)

    # Summary
    total_recs = sum(r.get("created", 0) for r in results.values())
    logger.info(f"Bulk pull complete: {total_recs:,} total records across {len(results)} modules")
    return results


_SKIP_API_MODULES = {"Quotes", "Sales_Orders", "Purchase_Orders", "Invoices", "Price_Books"}


def do_pull_sync(modules=None, modified_since=None):
    """Pull records from Zoho CRM into PostgreSQL.
    If modified_since='auto', use sync_metadata table with 5-min overlap buffer.
    Zoho CRM is always the source of truth — all updated fields overwrite PostgreSQL.
    Logs results to sync_jobs table for audit trail.
    """
    global sync_state
    zoho = get_zoho()
    modules = modules or [m for m in MODULE_TABLE_MAP.keys() if m not in _SKIP_API_MODULES]
    results = {}
    sync_start = time.time()

    # Create a sync_jobs entry for this run
    job_id = _create_sync_job("incremental_sync", "pull")
    total_all = 0
    created_all = 0
    errors_all = 0

    for i, module in enumerate(modules):
        table = MODULE_TABLE_MAP.get(module)
        if not table:
            continue

        with sync_lock:
            sync_state["module"] = module
            sync_state["progress"] = int((i / len(modules)) * 100)
            sync_state["message"] = f"Pulling {module} from Zoho..."

        mod_start = time.time()
        try:
            # Determine modified_since for this module
            mod_since = modified_since
            if mod_since == "auto":
                mod_since = _get_last_sync_ts(table)
                if mod_since:
                    logger.info(f"  {module}: incremental since {mod_since}")
                else:
                    logger.info(f"  {module}: no previous sync, full pull")

            records = zoho.get_all_records(module, modified_since=mod_since)
            if not records:
                results[module] = {"total": 0, "created": 0, "updated": 0, "errors": 0, "incremental": bool(mod_since)}
                _update_sync_metadata(table, 0, "idle")
                continue

            mapped_records = [zoho_record_to_pg(rec, table) for rec in records]
            created, updated, errs = _upsert_records_to_pg(table, mapped_records, module)
            dur = time.time() - mod_start
            results[module] = {"total": len(records), "created": created, "updated": updated, "errors": errs, "incremental": bool(mod_since)}
            total_all += len(records)
            created_all += created
            errors_all += errs

            # Update sync_metadata for this module
            _update_sync_metadata(table, len(records), "idle")
            logger.info(f"  {module}: {len(records)} records ({created} upserted, {errs} errors) in {dur:.1f}s")

        except Exception as e:
            results[module] = {"total": 0, "created": 0, "updated": 0, "errors": 1, "error": str(e)}
            errors_all += 1
            _update_sync_metadata(table, 0, "error", str(e))
            logger.error(f"  {module}: FAILED - {e}")

    # Complete the sync_jobs entry
    total_dur = time.time() - sync_start
    _complete_sync_job(job_id, total_all, created_all, 0, errors_all,
                       status="completed" if errors_all == 0 else "completed_with_errors",
                       duration=round(total_dur, 1))

    return results

def do_push_sync(modules=None, record_ids=None, table_name=None):
    """Push modified/enriched records from PostgreSQL to Zoho CRM.
    Supports: all modules, specific modules, or specific record IDs."""
    global sync_state
    zoho = get_zoho()
    start_time = time.time()
    job_id = _create_sync_job("push", "push")

    if table_name and record_ids:
        # Push specific records from a specific table
        modules_to_push = {TABLE_MODULE_MAP.get(table_name, ""): table_name}
    else:
        modules_to_push = {m: MODULE_TABLE_MAP[m] for m in (modules or MODULE_TABLE_MAP.keys())}

    results = {}
    total_success = total_failed = total_records = 0

    module_list = list(modules_to_push.items())
    for mi, (module, table) in enumerate(module_list):
        if not module or not table:
            continue

        with sync_lock:
            sync_state["module"] = module
            sync_state["message"] = f"Pushing {module} to Zoho... ({mi+1}/{len(module_list)})"
            sync_state["progress"] = int(mi / max(len(module_list), 1) * 100)

        try:
            conn = get_db()
            cur = conn.cursor()

            if record_ids:
                pk = get_pk(table)
                phs = ",".join(["%s"] * len(record_ids))
                cur.execute(f"SELECT * FROM {table} WHERE {pk} IN ({phs})", record_ids)
            else:
                if not has_column(table, "sync_status"):
                    cur.close()
                    conn.close()
                    continue
                cur.execute(f"SELECT * FROM {table} WHERE sync_status IN ('modified','pending')")

            records = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()

            if not records:
                results[module] = {"total": 0, "success": 0, "failed": 0, "created": 0, "updated": 0}
                continue

            success = failed = created = updated = 0
            for ri, rec in enumerate(records):
                zoho_id = rec.get("zoho_id")
                zoho_data = pg_record_to_zoho(rec, table)
                if not zoho_data:
                    failed += 1
                    logger.warning(f"Push {module}: empty zoho_data for record id={rec.get('id')}, skipping")
                    continue

                logger.debug(f"Push {module}/{zoho_id}: sending {len(zoho_data)} fields: {list(zoho_data.keys())}")

                # Progress update
                if ri % 10 == 0:
                    with sync_lock:
                        sync_state["message"] = f"Pushing {module} record {ri+1}/{len(records)}..."

                # Conflict pre-check: compare our zoho_modified_time with Zoho's current Modified_Time
                if zoho_id and rec.get("zoho_modified_time"):
                    try:
                        zoho_rec = zoho.api("GET", f"{module}/{zoho_id}", params={"fields": "Modified_Time"})
                        if zoho_rec and "data" in zoho_rec:
                            zoho_mod = zoho_rec["data"][0].get("Modified_Time", "")
                            local_mod = rec["zoho_modified_time"]
                            if isinstance(local_mod, datetime):
                                local_mod = local_mod.isoformat()
                            if zoho_mod and str(zoho_mod) > str(local_mod):
                                logger.warning(f"Push {module}/{zoho_id}: CONFLICT - Zoho modified {zoho_mod} > local {local_mod}")
                                # Log conflict
                                try:
                                    conn3 = get_db(); cur3 = conn3.cursor()
                                    cur3.execute("""INSERT INTO conflicts
                                        (id, table_name, record_id, zoho_id, conflict_type, postgres_modified_time, zoho_modified_time, resolution, detected_at)
                                        VALUES (gen_random_uuid(), %s, %s, %s, 'concurrent_modification', %s, %s, 'skipped', NOW())""",
                                        (table, rec.get("id"), zoho_id, rec.get("zoho_modified_time"), zoho_mod))
                                    conn3.commit(); cur3.close(); conn3.close()
                                except Exception:
                                    pass
                                failed += 1
                                _mark_push_error(table, rec.get("id"), f"Conflict: Zoho modified after our pull ({zoho_mod})")
                                continue
                    except Exception as e:
                        logger.debug(f"Push {module}/{zoho_id}: conflict check failed (proceeding): {e}")

                try:
                    if zoho_id:
                        resp = zoho.update_record(module, zoho_id, zoho_data)
                    else:
                        resp = zoho.create_record(module, zoho_data)

                    if resp and "data" in resp:
                        r = resp["data"][0]
                        if r.get("status") == "success":
                            new_id = r.get("details", {}).get("id", zoho_id)
                            conn2 = get_db()
                            cur2 = conn2.cursor()
                            if not zoho_id and new_id:
                                cur2.execute(f"UPDATE {table} SET zoho_id=%s, sync_status='synced', last_sync_at=%s WHERE id=%s",
                                             (new_id, datetime.now(), rec["id"]))
                                created += 1
                            else:
                                cur2.execute(f"UPDATE {table} SET sync_status='synced', last_sync_at=%s, sync_version=COALESCE(sync_version,0)+1 WHERE zoho_id=%s",
                                             (datetime.now(), zoho_id))
                                updated += 1
                            conn2.commit()
                            cur2.close()
                            conn2.close()
                            success += 1
                        else:
                            errmsg = r.get("message", "Unknown error")
                            details = r.get("details", {})
                            logger.warning(f"Push {module}/{zoho_id}: Zoho rejected: {errmsg} | details: {details}")
                            failed += 1
                            _mark_push_error(table, rec.get("id"), f"{errmsg}: {details}")
                    elif resp:
                        # Response exists but no 'data' key — log full response
                        logger.warning(f"Push {module}/{zoho_id}: unexpected response: {str(resp)[:300]}")
                        failed += 1
                        _mark_push_error(table, rec.get("id"), f"Unexpected response: {str(resp)[:200]}")
                    else:
                        logger.warning(f"Push {module}/{zoho_id}: no response from Zoho API")
                        failed += 1
                        _mark_push_error(table, rec.get("id"), "No response from Zoho API")
                except Exception as e:
                    failed += 1
                    logger.error(f"Push error {module}/{zoho_id}: {e}")
                    _mark_push_error(table, rec.get("id"), str(e))

                time.sleep(0.1)  # Rate limit: ~10 records/sec

            total_success += success
            total_failed += failed
            total_records += len(records)
            results[module] = {"total": len(records), "success": success, "failed": failed,
                               "created": created, "updated": updated}
            logger.info(f"Push {module}: {success} success ({created} created, {updated} updated), {failed} failed")

        except Exception as e:
            results[module] = {"total": 0, "success": 0, "failed": 1, "error": str(e)}
            logger.error(f"Failed to push {module}: {e}")

    duration = time.time() - start_time
    _complete_sync_job(job_id, total_records, total_success - (total_records - total_failed), 0, total_failed,
                       status="completed" if total_failed == 0 else "completed_with_errors",
                       duration=duration)
    logger.info(f"Push sync done: {total_success} success, {total_failed} failed in {duration:.0f}s")
    return results


def _mark_push_error(table, record_id, error_msg):
    """Mark a record as push error in DB."""
    if not record_id:
        return
    try:
        conn = get_db()
        cur = conn.cursor()
        pk = get_pk(table)
        cur.execute(f"UPDATE {table} SET sync_status='error', updated_at=%s WHERE {pk}=%s",
                     (datetime.now(), record_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Site Visits & Email Tracking Imports (related lists)
# ---------------------------------------------------------------------------

def _upsert_visit(cur, rec, parent_module, parent_zoho_id):
    """Upsert a single visit record from Zoho related list.
    Uses column names matching the existing visits table (from bulk import)."""
    zoho_id = str(rec.get("id", ""))
    if not zoho_id:
        return False
    cur.execute("""
        INSERT INTO visits (zoho_id, parent_module, parent_zoho_id,
            ip_address, visited_page, visited_page_url, referrer,
            time_spent, search_engine, browser, operating_system,
            portal_name, visit_source, visited_time, visitor_type,
            no_of_pages, user_agent, device_type,
            created_time, modified_time, _se_module)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (zoho_id) DO UPDATE SET
            parent_module=EXCLUDED.parent_module, parent_zoho_id=EXCLUDED.parent_zoho_id,
            ip_address=EXCLUDED.ip_address,
            visited_page=EXCLUDED.visited_page, visited_page_url=EXCLUDED.visited_page_url,
            referrer=EXCLUDED.referrer, time_spent=EXCLUDED.time_spent,
            search_engine=EXCLUDED.search_engine, browser=EXCLUDED.browser,
            operating_system=EXCLUDED.operating_system,
            portal_name=EXCLUDED.portal_name, visit_source=EXCLUDED.visit_source,
            visited_time=EXCLUDED.visited_time, visitor_type=EXCLUDED.visitor_type,
            no_of_pages=EXCLUDED.no_of_pages, user_agent=EXCLUDED.user_agent,
            device_type=EXCLUDED.device_type,
            created_time=EXCLUDED.created_time, modified_time=EXCLUDED.modified_time,
            _se_module=EXCLUDED._se_module
    """, (
        zoho_id, parent_module, parent_zoho_id,
        rec.get("IP_Address"),
        rec.get("Visited_Page"),
        rec.get("Visited_Page_URL"),
        rec.get("Referrer"),
        rec.get("Time_Spent"),
        rec.get("Search_Engine"),
        rec.get("Browser"),
        rec.get("Operating_System"),
        rec.get("Portal_Name"),
        rec.get("Visit_Source"),
        rec.get("Visited_Time"),
        rec.get("Visitor_Type"),
        rec.get("No_of_Pages"),
        rec.get("User_Agent"),
        rec.get("Device_type"),
        rec.get("Created_Time"),
        rec.get("Modified_Time"),
        parent_module.capitalize() if parent_module else None,
    ))
    return True


def _upsert_email(cur, rec, parent_module, parent_zoho_id):
    """Upsert a single email tracking record.
    Handles BOTH related-list format (message_id, from dict, to list) AND
    COQL format (id, Sender str, Sent_To str, No_of_Opens int, Entity_Id)."""
    zoho_id = str(rec.get("message_id") or rec.get("id") or "")
    if not zoho_id:
        return False

    # --- from_email: related-list has dict, COQL has Sender string ---
    from_raw = rec.get("Sender") or rec.get("from") or rec.get("From") or {}
    if isinstance(from_raw, dict):
        from_email = from_raw.get("email", str(from_raw))
    else:
        from_email = str(from_raw) if from_raw else None

    # --- to_email: related-list has list of dicts, COQL has Sent_To string ---
    to_raw = rec.get("Sent_To") or rec.get("to") or rec.get("To") or []
    if isinstance(to_raw, list):
        to_email = ", ".join(t.get("email", str(t)) if isinstance(t, dict) else str(t) for t in to_raw)
    else:
        to_email = str(to_raw) if to_raw else None

    # --- status: related-list has list of dicts, COQL has Status string ---
    status_raw = rec.get("status") or rec.get("Status") or []
    if isinstance(status_raw, list):
        status = ", ".join(s.get("type", str(s)) if isinstance(s, dict) else str(s) for s in status_raw)
    else:
        status = str(status_raw) if status_raw else None

    # --- Entity_Id: COQL provides parent linkage, override parent_zoho_id if available ---
    entity_id_raw = rec.get("Entity_Id")
    if entity_id_raw and isinstance(entity_id_raw, dict):
        parent_zoho_id = str(entity_id_raw.get("id", parent_zoho_id))
    elif entity_id_raw:
        parent_zoho_id = str(entity_id_raw)

    # --- Module: COQL provides parent module name ---
    module_raw = rec.get("Module")
    if module_raw:
        parent_module = str(module_raw).lower()

    cur.execute("""
        INSERT INTO email_tracking (zoho_id, parent_module, parent_zoho_id,
            subject, from_email, to_email, status,
            open_count, first_open, last_open,
            click_count, bounce_type, sent_time, category,
            zoho_created_time, zoho_modified_time, last_sync_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, NOW())
        ON CONFLICT (zoho_id) DO UPDATE SET
            parent_module=EXCLUDED.parent_module, parent_zoho_id=EXCLUDED.parent_zoho_id,
            subject=EXCLUDED.subject, from_email=EXCLUDED.from_email,
            to_email=EXCLUDED.to_email, status=EXCLUDED.status,
            open_count=EXCLUDED.open_count, first_open=EXCLUDED.first_open,
            last_open=EXCLUDED.last_open, click_count=EXCLUDED.click_count,
            bounce_type=EXCLUDED.bounce_type, sent_time=EXCLUDED.sent_time,
            category=EXCLUDED.category,
            zoho_created_time=EXCLUDED.zoho_created_time,
            zoho_modified_time=EXCLUDED.zoho_modified_time,
            updated_at=NOW(), last_sync_at=NOW()
    """, (
        zoho_id[:100], (parent_module or "")[:50], (parent_zoho_id or "")[:100],
        (rec.get("Subject") or rec.get("subject") or "")[:500] or None,
        from_email[:255] if from_email else None,
        to_email[:255] if to_email else None,
        status[:50] if status else None,
        rec.get("No_of_Opens") or rec.get("open_count") or rec.get("Open_Count") or 0,
        rec.get("First_Opened") or rec.get("first_open") or rec.get("First_Open"),
        rec.get("Last_Opened") or rec.get("last_open") or rec.get("Last_Open"),
        rec.get("No_of_Clicks") or rec.get("click_count") or rec.get("Click_Count") or 0,
        (str(rec.get("Bounce_Reason") or rec.get("bounce_type") or rec.get("Bounce_Type") or "")[:50]) or None,
        rec.get("Sent_On") or rec.get("sent_time") or rec.get("Sent_Time") or rec.get("Date_Sent"),
        (str(rec.get("Source") or rec.get("source") or rec.get("Category") or rec.get("category") or "")[:50]) or None,
        rec.get("Created_Time"),
        rec.get("Modified_Time"),
    ))
    return True


def _import_related_list(related_list_name, upsert_fn, job_type, parent_modules=None):
    """Generic import of a related list (Visits/Emails) for specified parent modules.
    Aborts a parent_module if first 50 consecutive calls all fail (wrong API name).
    Returns summary dict."""
    global sync_state
    zoho = get_zoho()
    job_id = _create_sync_job(job_type, "pull")
    total_items = 0
    total_parents = 0
    errors = 0
    start = time.time()

    if parent_modules is None:
        parent_modules = ["Leads", "Contacts"]

    for parent_module in parent_modules:
        parent_table = MODULE_TABLE_MAP.get(parent_module)
        if not parent_table:
            continue

        conn = get_db()
        cur = conn.cursor()
        cur.execute(f"SELECT zoho_id FROM {parent_table} WHERE zoho_id IS NOT NULL ORDER BY zoho_id")
        parent_ids = [r["zoho_id"] for r in cur.fetchall()]
        cur.close()
        conn.close()

        logger.info(f"{job_type}: {len(parent_ids)} {parent_module} to process")

        consecutive_fails = 0
        module_items = 0
        abort_module = False

        for i, pid in enumerate(parent_ids):
            if abort_module:
                break

            if i > 0 and i % 1000 == 0:
                elapsed = time.time() - start
                rate = total_parents / elapsed if elapsed > 0 else 0
                logger.info(f"  {job_type} progress: {parent_module} {i}/{len(parent_ids)}, "
                            f"{module_items} items found, {rate:.1f} rec/s")
                with sync_lock:
                    pct = int((total_parents / 131000) * 100)
                    sync_state["message"] = (f"Importing {related_list_name}: "
                                             f"{parent_module} {i}/{len(parent_ids)} ({total_items} total)")
                    sync_state["progress"] = min(pct, 99)

            records = zoho.get_related_records(parent_module, pid, related_list_name)
            if records is None:
                # API error (400/401/network) — count toward abort
                consecutive_fails += 1
                if consecutive_fails >= 50 and module_items == 0 and i < 60:
                    logger.warning(f"  {job_type}: Aborting {parent_module} — {consecutive_fails} "
                                   f"consecutive API errors. Related list '{related_list_name}' may not exist.")
                    abort_module = True
                    continue
            elif records:
                # Got data — reset fail counter, upsert records
                consecutive_fails = 0
                conn = get_db()
                cur = conn.cursor()
                for rec in records:
                    try:
                        upsert_fn(cur, rec, parent_module.lower(), pid)
                        total_items += 1
                        module_items += 1
                    except Exception as e:
                        errors += 1
                        if errors <= 5:
                            logger.warning(f"  {job_type} upsert error {parent_module}/{pid}: {e}")
                conn.commit()
                cur.close()
                conn.close()
            # else: records == [] — no data for this parent, not an error

            total_parents += 1
            time.sleep(0.08)  # ~12 req/sec

        if not abort_module:
            logger.info(f"  {job_type}: {parent_module} done — {module_items} items from {len(parent_ids)} records")

    dur = time.time() - start
    _complete_sync_job(job_id, total_items, total_items, 0, errors,
                       status="completed" if errors == 0 else "completed_with_errors",
                       duration=round(dur, 1))
    logger.info(f"{job_type} done: {total_items} items from {total_parents} parents in {dur:.0f}s ({errors} errors)")
    return {"total_items": total_items, "total_parents": total_parents, "errors": errors,
            "duration_seconds": round(dur, 1)}


def do_visits_import():
    """Import site visits from Zoho SalesIQ related list on Contacts.
    Note: Visits related list (Visits_Zoho_Livedesk) only exists on Contacts, not Leads.
    Standalone Visits module is synced separately via regular module sync."""
    return _import_related_list("Visits_Zoho_Livedesk", _upsert_visit, "visits_import",
                                parent_modules=["Contacts"])


def do_email_tracking_import():
    """Import ALL email activity via COQL (200 records per API call).
    Uses cursor-based pagination on Created_Time (COQL offset limit is 2000).
    Each email record includes Entity_Id (parent link) and Module (parent type)."""
    global sync_state
    zoho = get_zoho()
    job_id = _create_sync_job("email_tracking_import", "pull")
    total_items = 0
    errors = 0
    start = time.time()
    batch_size = 200  # COQL max per call
    consecutive_empty = 0

    COQL_FIELDS = ("Subject, Sender, Sent_To, Status, No_of_Opens, No_of_Clicks, "
                   "First_Opened, Last_Opened, Sent_On, Source, Entity_Id, Module, "
                   "Bounce_Reason, Created_Time, Modified_Time")

    # Cursor-based pagination: start from 2010 (Zoho CRM didn't exist before that)
    cursor_time = "2010-01-01T00:00:00+00:00"
    last_id = None  # Track last record ID to avoid duplicates at time boundaries
    api_calls = 0

    logger.info("email_tracking_import: starting COQL bulk fetch (cursor-based)")

    while True:
        # Use offset 0 always, paginate by Created_Time cursor
        query = (f"select {COQL_FIELDS} from Emails "
                 f"where Created_Time >= '{cursor_time}' "
                 f"order by Created_Time asc "
                 f"limit {batch_size} offset 0")
        if api_calls == 0:
            logger.info(f"  First COQL query: {query[:120]}...")
        resp = zoho.coql_query(query)
        api_calls += 1
        if api_calls <= 3:
            logger.info(f"  COQL call #{api_calls}: resp={'has data' if resp and 'data' in resp else str(resp)[:150]}")

        if not resp or "data" not in resp:
            if resp is None:
                errors += 1
                logger.warning(f"  COQL error at cursor {cursor_time}, retrying...")
                time.sleep(2)
                resp = zoho.coql_query(query)
                api_calls += 1
                if not resp or "data" not in resp:
                    logger.error(f"  COQL retry failed at cursor {cursor_time}, stopping. resp={str(resp)[:200]}")
                    break
            else:
                logger.info(f"  COQL: no data at cursor {cursor_time}, resp keys={list(resp.keys()) if resp else 'None'}")
                break

        records = resp.get("data", [])
        if not records:
            break

        # Skip records we've already seen (at time boundary)
        new_records = []
        for rec in records:
            rec_id = str(rec.get("id", ""))
            if rec_id == last_id:
                continue  # Skip exact duplicate at boundary
            new_records.append(rec)

        if not new_records:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                logger.info("  COQL: 3 consecutive empty batches, stopping")
                break
            # Advance cursor by 1 second to escape stuck position
            try:
                ct = datetime.fromisoformat(cursor_time.replace("+00:00", "+00:00"))
                cursor_time = (ct + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            except Exception:
                break
            continue
        consecutive_empty = 0

        conn = get_db()
        cur = conn.cursor()
        batch_ok = 0
        batch_failed = False
        for rec in new_records:
            try:
                if _upsert_email(cur, rec, "unknown", ""):
                    batch_ok += 1
                    total_items += 1
            except Exception as e:
                # Transaction aborted — rollback, log error, and re-insert remaining via savepoints
                conn.rollback()
                errors += 1
                batch_failed = True
                if errors <= 5:
                    logger.warning(f"  email upsert error: {e}")
                break
        if not batch_failed:
            conn.commit()
        cur.close()
        conn.close()
        # If batch failed, retry remaining records individually (slower but resilient)
        if batch_failed:
            conn2 = get_db()
            cur2 = conn2.cursor()
            for rec in new_records:
                try:
                    _upsert_email(cur2, rec, "unknown", "")
                    total_items += 1
                    conn2.commit()
                except Exception:
                    conn2.rollback()
                    errors += 1
            cur2.close()
            conn2.close()

        # Advance cursor to last record's Created_Time
        last_rec = records[-1]
        new_cursor = last_rec.get("Created_Time")
        last_id = str(last_rec.get("id", ""))

        if new_cursor and new_cursor == cursor_time and len(records) == batch_size:
            # All 200 records have the same Created_Time — advance by 1s to avoid infinite loop
            try:
                ct = datetime.fromisoformat(new_cursor.replace("+00:00", "+00:00"))
                cursor_time = (ct + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            except Exception:
                cursor_time = new_cursor
        elif new_cursor:
            cursor_time = new_cursor
        else:
            break

        # Progress update every 2000 records
        if total_items % 2000 < batch_size:
            elapsed = time.time() - start
            rate = total_items / elapsed if elapsed > 0 else 0
            logger.info(f"  email_tracking_import: {total_items} emails "
                        f"({api_calls} API calls, {rate:.0f} rec/s, cursor={cursor_time[:19]})")
            with sync_lock:
                sync_state["message"] = (f"Importing emails via COQL: "
                                         f"{total_items} records ({rate:.0f}/s)")
                sync_state["progress"] = min(int(total_items / 50000 * 100), 99)

        # Check if there are more records
        info = resp.get("info", {})
        if not info.get("more_records", False) and len(records) < batch_size:
            break

        time.sleep(0.1)

    dur = time.time() - start
    rate = total_items / dur if dur > 0 else 0
    _complete_sync_job(job_id, total_items, total_items, 0, errors,
                       status="completed" if errors == 0 else "completed_with_errors",
                       duration=round(dur, 1))
    logger.info(f"email_tracking_import done: {total_items} emails in {dur:.0f}s "
                f"({rate:.0f} rec/s, {api_calls} API calls, {errors} errors)")
    return {"total_items": total_items, "errors": errors, "duration_seconds": round(dur, 1),
            "api_calls": api_calls}


def _import_related_list_incremental(related_list_name, upsert_fn, job_type, parent_modules=None, minutes_back=90):
    """Incremental import: only fetch related lists for recently modified parent records.
    Used by auto-sync to keep emails/visits up-to-date without scanning all 131K records.
    minutes_back: how far back to look (default 90 = sync interval + 30m buffer)."""
    zoho = get_zoho()
    total_items = 0
    total_parents = 0
    errors = 0
    start = time.time()
    cutoff = datetime.utcnow() - timedelta(minutes=minutes_back)

    if parent_modules is None:
        parent_modules = ["Leads", "Contacts"]

    for parent_module in parent_modules:
        parent_table = MODULE_TABLE_MAP.get(parent_module)
        if not parent_table:
            continue

        conn = get_db()
        cur = conn.cursor()
        cur.execute(f"""SELECT zoho_id FROM {parent_table}
                       WHERE zoho_id IS NOT NULL AND zoho_modified_time > %s
                       ORDER BY zoho_modified_time DESC""", (cutoff,))
        parent_ids = [r["zoho_id"] for r in cur.fetchall()]
        cur.close()
        conn.close()

        if not parent_ids:
            logger.info(f"  {job_type}: no recently modified {parent_module} (cutoff {cutoff.isoformat()})")
            continue

        logger.info(f"  {job_type}: {len(parent_ids)} recently modified {parent_module} to scan")

        for pid in parent_ids:
            records = zoho.get_related_records(parent_module, pid, related_list_name)
            if records is None:
                errors += 1
            elif records:
                conn = get_db()
                cur = conn.cursor()
                for rec in records:
                    try:
                        upsert_fn(cur, rec, parent_module.lower(), pid)
                        total_items += 1
                    except Exception as e:
                        errors += 1
                        if errors <= 3:
                            logger.warning(f"  {job_type} upsert error: {e}")
                conn.commit()
                cur.close()
                conn.close()
            total_parents += 1
            time.sleep(0.08)

    dur = time.time() - start
    if total_items > 0 or errors > 0:
        logger.info(f"  {job_type}: {total_items} items from {total_parents} parents in {dur:.1f}s ({errors} errors)")
    return {"total_items": total_items, "total_parents": total_parents, "errors": errors}


def _import_emails_coql_incremental(minutes_back=90):
    """Incremental email import via COQL — fetch only emails modified in last N minutes.
    Uses cursor-based pagination on Modified_Time (COQL offset limit is 2000)."""
    zoho = get_zoho()
    total_items = 0
    errors = 0
    start = time.time()
    batch_size = 200

    cursor_time = (datetime.utcnow() - timedelta(minutes=minutes_back)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    COQL_FIELDS = ("Subject, Sender, Sent_To, Status, No_of_Opens, No_of_Clicks, "
                   "First_Opened, Last_Opened, Sent_On, Source, Entity_Id, Module, "
                   "Bounce_Reason, Created_Time, Modified_Time")

    while True:
        query = (f"select {COQL_FIELDS} from Emails "
                 f"where Modified_Time >= '{cursor_time}' "
                 f"order by Modified_Time asc "
                 f"limit {batch_size} offset 0")
        resp = zoho.coql_query(query)

        if not resp or "data" not in resp:
            if resp is None:
                errors += 1
            break

        records = resp.get("data", [])
        if not records:
            break

        conn = get_db()
        cur = conn.cursor()
        for rec in records:
            try:
                _upsert_email(cur, rec, "unknown", "")
                total_items += 1
            except Exception as e:
                conn.rollback()
                errors += 1
                if errors <= 3:
                    logger.warning(f"  email_auto COQL upsert error: {e}")
        try:
            conn.commit()
        except Exception:
            conn.rollback()
        cur.close()
        conn.close()

        # Advance cursor
        new_cursor = records[-1].get("Modified_Time")
        if new_cursor and new_cursor == cursor_time and len(records) == batch_size:
            try:
                ct = datetime.fromisoformat(new_cursor.replace("+00:00", "+00:00"))
                cursor_time = (ct + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            except Exception:
                break
        elif new_cursor:
            cursor_time = new_cursor
        else:
            break

        if not resp.get("info", {}).get("more_records", False) and len(records) < batch_size:
            break
        time.sleep(0.1)

    dur = time.time() - start
    if total_items > 0 or errors > 0:
        logger.info(f"  email_auto COQL: {total_items} emails (modified since cutoff) "
                    f"in {dur:.1f}s ({errors} errors)")
    return {"total_items": total_items, "errors": errors}


def run_sync_background(direction, modules=None, record_ids=None, table_name=None):
    """Run sync in background thread."""
    global sync_state

    def worker():
        global sync_state
        with sync_lock:
            sync_state["running"] = True
            sync_state["direction"] = direction
            sync_state["started_at"] = datetime.now().isoformat()
            sync_state["completed_at"] = None
            sync_state["results"] = {}
            sync_state["errors"] = []
            sync_state["progress"] = 0

        try:
            if direction == "pull":
                results = do_pull_sync(modules, modified_since="auto")
            elif direction == "bulk_pull":
                results = do_bulk_pull_sync(modules)
            elif direction == "push":
                results = do_push_sync(modules, record_ids, table_name)
            elif direction == "full":
                # Full bidirectional: bulk pull first, then push
                with sync_lock:
                    sync_state["message"] = "Phase 1: Bulk pulling ALL from Zoho..."
                pull_results = do_bulk_pull_sync(modules)
                with sync_lock:
                    sync_state["message"] = "Phase 2: Pushing to Zoho..."
                    sync_state["progress"] = 50
                push_results = do_push_sync(modules)
                results = {"pull": pull_results, "push": push_results}
            elif direction == "import_visits":
                results = do_visits_import()
            elif direction == "import_emails":
                results = do_email_tracking_import()
            else:
                results = {"error": f"Unknown direction: {direction}"}

            with sync_lock:
                sync_state["results"] = results
                sync_state["progress"] = 100
                sync_state["message"] = f"Sync complete ({direction})"

        except Exception as e:
            with sync_lock:
                sync_state["errors"].append(str(e))
                sync_state["message"] = f"Error: {e}"
        finally:
            with sync_lock:
                sync_state["running"] = False
                sync_state["completed_at"] = datetime.now().isoformat()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

# ---------------------------------------------------------------------------
# ROUTES - Pages
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("unified_index.html")

# ---------------------------------------------------------------------------
# ROUTES - API: Dashboard stats
# ---------------------------------------------------------------------------
@app.route("/api/dashboard")
def api_dashboard():
    """Get dashboard overview stats."""
    conn = get_db()
    cur = conn.cursor()
    try:
        tables = get_tables()
        crm_tables = [t for t in tables if t in MODULE_TABLE_MAP.values() or t in TABLE_MODULE_MAP]
        # Include related list tables (email_tracking, visits) in dashboard
        extra_tables = {"email_tracking": "Email Tracking", "visits": "Site Visits"}
        for et, elabel in extra_tables.items():
            if et in tables and et not in crm_tables:
                crm_tables.append(et)
        stats = []
        totals = {"records": 0, "synced": 0, "pending": 0, "modified": 0, "error": 0}

        for t in crm_tables:
            cur.execute(f"SELECT COUNT(*) as cnt FROM {t}")
            cnt = cur.fetchone()["cnt"]
            totals["records"] += cnt

            mod_name = TABLE_MODULE_MAP.get(t) or extra_tables.get(t) or t
            row = {"table": t, "module": mod_name, "count": cnt,
                   "synced": 0, "pending": 0, "modified": 0, "error": 0, "last_sync": None}

            if has_column(t, "sync_status"):
                cur.execute(f"""
                    SELECT sync_status, COUNT(*) as cnt FROM {t}
                    WHERE sync_status IS NOT NULL GROUP BY sync_status
                """)
                for sr in cur.fetchall():
                    s = sr["sync_status"]
                    c = sr["cnt"]
                    if s in row:
                        row[s] = c
                        totals[s] = totals.get(s, 0) + c

            if has_column(t, "last_sync_at"):
                cur.execute(f"SELECT MAX(last_sync_at) as ls FROM {t}")
                ls = cur.fetchone()
                if ls and ls["ls"]:
                    row["last_sync"] = ls["ls"].isoformat()

            stats.append(row)

        cur.close()
        conn.close()

        # Test Zoho connection
        zoho_ok = False
        try:
            zoho_ok = get_zoho().test_connection()
        except Exception:
            pass

        return jsonify({
            "tables": stats,
            "totals": totals,
            "zoho_connected": zoho_ok,
            "all_tables": tables,
        })
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ROUTES - API: Table data
# ---------------------------------------------------------------------------
@app.route("/api/table/<table_name>")
def api_table_data(table_name):
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    search = request.args.get("search", "")
    sync_filter = request.args.get("sync_status", "")
    sort_col = request.args.get("sort", "")
    sort_dir = request.args.get("dir", "desc")

    offset = (page - 1) * per_page
    conn = get_db()
    cur = conn.cursor()

    try:
        cols = get_columns(table_name)
        col_names = [c["column_name"] for c in cols]
        pk = get_pk(table_name)

        wheres = []
        params = []

        if search:
            text_cols = [c["column_name"] for c in cols if c["data_type"] in ("character varying", "text")]
            if text_cols:
                wheres.append("(" + " OR ".join(f"{c}::text ILIKE %s" for c in text_cols) + ")")
                params.extend([f"%{search}%"] * len(text_cols))

        if sync_filter and "sync_status" in col_names:
            wheres.append("sync_status=%s")
            params.append(sync_filter)

        where = ("WHERE " + " AND ".join(wheres)) if wheres else ""

        # Sorting
        order = ""
        if sort_col and sort_col in col_names:
            d = "ASC" if sort_dir.lower() == "asc" else "DESC"
            order = f"ORDER BY {sort_col} {d} NULLS LAST"
        elif pk:
            order = f"ORDER BY {pk} DESC"

        cur.execute(f"SELECT COUNT(*) as cnt FROM {table_name} {where}", params)
        total = cur.fetchone()["cnt"]

        cur.execute(f"SELECT * FROM {table_name} {where} {order} LIMIT %s OFFSET %s",
                    params + [per_page, offset])
        rows = [{k: serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]

        cur.close()
        conn.close()

        return jsonify({
            "data": rows,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "columns": [{"name": c["column_name"], "type": c["data_type"],
                         "nullable": c["is_nullable"] == "YES"} for c in cols],
            "primary_key": pk,
            "has_sync_status": "sync_status" in col_names,
        })
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ROUTES - API: Record CRUD
# ---------------------------------------------------------------------------
@app.route("/api/record/<table_name>", methods=["POST"])
def api_create_record(table_name):
    """Create a new record in the database."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    cols = get_columns(table_name)
    col_names = [c["column_name"] for c in cols]
    pk = get_pk(table_name)

    # Filter to valid columns, exclude auto-generated
    skip = {pk, "id", "full_name", "created_at"}
    record = {}
    for k, v in data.items():
        if k in col_names and k not in skip and v is not None and v != "":
            record[k] = v

    # Add metadata
    if "sync_status" in col_names:
        record["sync_status"] = "pending"
    if "updated_at" in col_names:
        record["updated_at"] = datetime.now()
    if "created_at" in col_names:
        record["created_at"] = datetime.now()

    if not record:
        return jsonify({"error": "No valid fields"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        cols_str = ", ".join(record.keys())
        phs = ", ".join(["%s"] * len(record))
        cur.execute(f"INSERT INTO {table_name} ({cols_str}) VALUES ({phs}) RETURNING *",
                    list(record.values()))
        new_rec = dict(cur.fetchone())
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "record": {k: serialize(v) for k, v in new_rec.items()}})
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/record/<table_name>/<record_id>", methods=["GET"])
def api_get_record(table_name, record_id):
    """Get a single record by ID."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400
    pk = get_pk(table_name)
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table_name} WHERE {pk}=%s", (record_id,))
        rec = cur.fetchone()
        cur.close()
        conn.close()
        if rec:
            return jsonify({"record": {k: serialize(v) for k, v in dict(rec).items()},
                            "columns": [{"name": c["column_name"], "type": c["data_type"],
                                         "nullable": c["is_nullable"] == "YES"} for c in get_columns(table_name)]})
        return jsonify({"error": "Record not found"}), 404
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/record/<table_name>/<record_id>", methods=["PUT"])
def api_update_record(table_name, record_id):
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    cols = [c["column_name"] for c in get_columns(table_name)]
    pk = get_pk(table_name)
    skip = {pk, "id", "full_name", "created_at"}

    updates = {}
    for k, v in data.items():
        if k in cols and k not in skip:
            updates[k] = v

    if "sync_status" in cols:
        updates["sync_status"] = "modified"
    if "updated_at" in cols:
        updates["updated_at"] = datetime.now()

    if not updates:
        return jsonify({"error": "No valid fields"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        # Fetch old values for change tracking
        cur.execute(f"SELECT * FROM {table_name} WHERE {pk}=%s", (record_id,))
        old_rec = cur.fetchone()
        if not old_rec:
            cur.close(); conn.close()
            return jsonify({"error": "Record not found"}), 404
        old_dict = dict(old_rec)

        sets = ", ".join(f"{k}=%s" for k in updates.keys())
        cur.execute(f"UPDATE {table_name} SET {sets} WHERE {pk}=%s RETURNING *",
                    list(updates.values()) + [record_id])
        rec = cur.fetchone()

        # Log changes to changes_detected
        changed_fields = {}
        for k, v in data.items():
            if k in old_dict and str(old_dict.get(k)) != str(v) and k not in {"sync_status", "updated_at"}:
                changed_fields[k] = {"old": serialize(old_dict[k]), "new": serialize(v)}
        if changed_fields:
            try:
                cur.execute("SAVEPOINT change_log")
                cur.execute("""INSERT INTO changes_detected
                    (id, table_name, record_id, zoho_id, change_type, change_source, old_values, new_values, detected_at, processing_status)
                    VALUES (gen_random_uuid(), %s, %s::uuid, %s, 'updated', 'postgres', %s, %s, NOW(), 'synced')""",
                    (table_name, record_id, old_dict.get("zoho_id"),
                     json.dumps({k: v["old"] for k, v in changed_fields.items()}, default=str),
                     json.dumps({k: v["new"] for k, v in changed_fields.items()}, default=str)))
                cur.execute("RELEASE SAVEPOINT change_log")
            except Exception as e:
                cur.execute("ROLLBACK TO SAVEPOINT change_log")
                logger.warning(f"Change tracking insert failed: {e}")

        conn.commit()
        cur.close()
        conn.close()
        if rec:
            return jsonify({"success": True, "record": {k: serialize(v) for k, v in dict(rec).items()},
                            "changes": changed_fields})
        return jsonify({"error": "Record not found"}), 404
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/record/<table_name>/<record_id>/history")
def api_record_history(table_name, record_id):
    """Get change history for a specific record."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""SELECT id, change_type, change_source, old_values, new_values,
                              detected_at, processing_status, conflict_resolution
                       FROM changes_detected
                       WHERE table_name=%s AND record_id=%s::uuid
                       ORDER BY detected_at DESC LIMIT 50""", (table_name, record_id))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({"history": [{k: serialize(v) for k, v in r.items()} for r in rows],
                        "total": len(rows)})
    except Exception as e:
        return jsonify({"history": [], "error": str(e)})

@app.route("/api/changes/recent")
def api_recent_changes():
    """Get recent changes across all tables."""
    limit = request.args.get("limit", 50, type=int)
    table_filter = request.args.get("table", None)
    try:
        conn = get_db()
        cur = conn.cursor()
        sql = """SELECT cd.id, cd.table_name, cd.record_id, cd.zoho_id,
                        cd.change_type, cd.change_source, cd.old_values, cd.new_values,
                        cd.detected_at, cd.processing_status
                 FROM changes_detected cd"""
        params = []
        if table_filter:
            sql += " WHERE cd.table_name = %s"
            params.append(table_filter)
        sql += " ORDER BY cd.detected_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({"changes": [{k: serialize(v) for k, v in r.items()} for r in rows],
                        "total": len(rows)})
    except Exception as e:
        return jsonify({"changes": [], "error": str(e)})

@app.route("/api/record/<table_name>/<record_id>", methods=["DELETE"])
def api_delete_record(table_name, record_id):
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400
    pk = get_pk(table_name)
    conn = get_db()
    cur = conn.cursor()
    try:
        # Soft delete if deleted_at column exists
        if has_column(table_name, "deleted_at"):
            cur.execute(f"UPDATE {table_name} SET deleted_at=%s WHERE {pk}=%s RETURNING {pk}",
                        (datetime.now(), record_id))
        else:
            cur.execute(f"DELETE FROM {table_name} WHERE {pk}=%s RETURNING {pk}", (record_id,))
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": bool(result)})
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ROUTES - API: Bulk operations
# ---------------------------------------------------------------------------
@app.route("/api/bulk/<table_name>", methods=["POST"])
def api_bulk_operation(table_name):
    """Bulk operations: delete, update_status, push_to_zoho."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    data = request.get_json()
    action = data.get("action")
    record_ids = data.get("record_ids", [])

    if not action or not record_ids:
        return jsonify({"error": "action and record_ids required"}), 400

    pk = get_pk(table_name)
    conn = get_db()
    cur = conn.cursor()
    phs = ",".join(["%s"] * len(record_ids))

    try:
        if action == "delete":
            if has_column(table_name, "deleted_at"):
                cur.execute(f"UPDATE {table_name} SET deleted_at=%s WHERE {pk} IN ({phs})",
                            [datetime.now()] + record_ids)
            else:
                cur.execute(f"DELETE FROM {table_name} WHERE {pk} IN ({phs})", record_ids)
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True, "affected": len(record_ids)})

        elif action == "update_status":
            new_status = data.get("status", "pending")
            if new_status not in ("pending", "synced", "modified", "error"):
                return jsonify({"error": "Invalid status"}), 400
            cur.execute(f"UPDATE {table_name} SET sync_status=%s, updated_at=%s WHERE {pk} IN ({phs})",
                        [new_status, datetime.now()] + record_ids)
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True, "affected": len(record_ids)})

        elif action == "push_to_zoho":
            cur.close()
            conn.close()
            if _is_sync_running():
                return jsonify({"error": "Sync already running"}), 409
            run_sync_background("push", record_ids=record_ids, table_name=table_name)
            return jsonify({"success": True, "status": "push_started", "records": len(record_ids)})

        elif action == "mark_pending":
            cur.execute(f"UPDATE {table_name} SET sync_status='pending', updated_at=%s WHERE {pk} IN ({phs})",
                        [datetime.now()] + record_ids)
            conn.commit()
            cur.close()
            conn.close()
            return jsonify({"success": True, "affected": len(record_ids)})

        else:
            cur.close()
            conn.close()
            return jsonify({"error": f"Unknown action: {action}"}), 400

    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ROUTES - API: Sync
# ---------------------------------------------------------------------------
@app.route("/api/sync/pull", methods=["POST"])
def api_sync_pull():
    """Incremental pull - only records modified since last sync."""
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    data = request.get_json() or {}
    modules = data.get("modules")
    run_sync_background("pull", modules=modules)
    return jsonify({"status": "started", "direction": "pull", "mode": "incremental"})

@app.route("/api/sync/bulk-pull", methods=["POST"])
def api_sync_bulk_pull():
    """Full bulk pull - downloads ALL records from Zoho via Bulk Read API."""
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    data = request.get_json() or {}
    modules = data.get("modules")
    run_sync_background("bulk_pull", modules=modules)
    return jsonify({"status": "started", "direction": "bulk_pull", "mode": "bulk_read_api"})

@app.route("/api/sync/push", methods=["POST"])
def api_sync_push():
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    data = request.get_json() or {}
    modules = data.get("modules")
    record_ids = data.get("record_ids")
    table_name = data.get("table")
    run_sync_background("push", modules=modules, record_ids=record_ids, table_name=table_name)
    return jsonify({"status": "started", "direction": "push"})

@app.route("/api/sync/push-preview", methods=["POST"])
def api_push_preview():
    """Preview what records would be pushed to Zoho (without pushing).
    Shows record counts by module and sample data mapping."""
    data = request.get_json() or {}
    statuses = data.get("statuses", ["pending", "modified"])
    modules_filter = data.get("modules")
    limit_per_module = data.get("limit", 5)

    conn = get_db()
    cur = conn.cursor()
    try:
        preview = []
        for module, table in MODULE_TABLE_MAP.items():
            if modules_filter and module not in modules_filter:
                continue
            if not has_column(table, "sync_status"):
                continue
            phs = ",".join(["%s"] * len(statuses))
            cur.execute(f"SELECT COUNT(*) as cnt FROM {table} WHERE sync_status IN ({phs})", statuses)
            count = cur.fetchone()["cnt"]
            if count == 0:
                continue

            # Get sample records and their Zoho mapping
            cur.execute(f"SELECT * FROM {table} WHERE sync_status IN ({phs}) LIMIT %s",
                        statuses + [limit_per_module])
            samples = []
            for row in cur.fetchall():
                rec = dict(row)
                zoho_data = pg_record_to_zoho(rec, table)
                samples.append({
                    "id": rec.get("id"),
                    "zoho_id": rec.get("zoho_id"),
                    "sync_status": rec.get("sync_status"),
                    "action": "update" if rec.get("zoho_id") else "create",
                    "zoho_fields": zoho_data,
                    "field_count": len(zoho_data),
                })
            preview.append({
                "module": module,
                "table": table,
                "total_records": count,
                "updates": sum(1 for s in samples if s["action"] == "update"),
                "creates": sum(1 for s in samples if s["action"] == "create"),
                "samples": samples,
            })

        total = sum(p["total_records"] for p in preview)
        return jsonify({"preview": preview, "total_records": total, "statuses": statuses})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route("/api/sync/push-module/<module_name>", methods=["POST"])
def api_push_single_module(module_name):
    """Push all pending/modified records for a single module to Zoho."""
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    if module_name not in MODULE_TABLE_MAP:
        return jsonify({"error": f"Unknown module: {module_name}"}), 400
    data = request.get_json() or {}
    statuses = data.get("statuses", ["pending", "modified"])
    run_sync_background("push", modules=[module_name])
    return jsonify({"status": "started", "module": module_name, "direction": "push", "statuses": statuses})

@app.route("/api/sync/full", methods=["POST"])
def api_sync_full():
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    data = request.get_json() or {}
    modules = data.get("modules")
    run_sync_background("full", modules=modules)
    return jsonify({"status": "started", "direction": "full"})

@app.route("/api/sync/status")
def api_sync_status():
    with sync_lock:
        s = dict(sync_state)
    with auto_sync_lock:
        s["auto_sync"] = dict(auto_sync_state)
    return jsonify(s)

@app.route("/api/sync/reset", methods=["POST"])
def api_sync_reset():
    """Reset stuck sync state. Use when instance was killed mid-import."""
    with sync_lock:
        sync_state["running"] = False
        sync_state["message"] = "Reset by user"
        sync_state["progress"] = 0
    return jsonify({"status": "reset", "sync_state": dict(sync_state)})

@app.route("/api/sync/auto", methods=["GET", "POST"])
def api_sync_auto():
    """Get or update auto-sync settings."""
    if request.method == "GET":
        with auto_sync_lock:
            return jsonify(dict(auto_sync_state))

    data = request.get_json() or {}
    with auto_sync_lock:
        if "enabled" in data:
            auto_sync_state["enabled"] = bool(data["enabled"])
        if "interval_minutes" in data:
            val = int(data["interval_minutes"])
            if val >= 5:
                auto_sync_state["interval_minutes"] = val
    # Ensure thread is running
    start_auto_sync()
    with auto_sync_lock:
        return jsonify(dict(auto_sync_state))

@app.route("/api/sync/history")
def api_sync_history():
    """Get sync history from sync_jobs table if it exists."""
    try:
        conn = get_db()
    except Exception as e:
        return jsonify({"jobs": [], "error": f"DB connection failed: {e}"}), 200
    cur = conn.cursor()
    try:
        tables = get_tables()
        if "sync_jobs" not in tables:
            cur.close()
            conn.close()
            return jsonify({"jobs": [], "message": "sync_jobs table not found"})

        limit = request.args.get("limit", 20, type=int)
        cur.execute("""
            SELECT * FROM sync_jobs
            ORDER BY started_at DESC NULLS LAST
            LIMIT %s
        """, (limit,))
        jobs = [{k: serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]
        cur.close()
        conn.close()
        return jsonify({"jobs": jobs})
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/sync/import-visits", methods=["POST"])
def api_import_visits():
    """Trigger site visits import from Zoho related lists (long-running)."""
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    run_sync_background("import_visits")
    return jsonify({"status": "started", "type": "visits_import",
                    "note": "This may take 2+ hours for ~130K records"})

@app.route("/api/sync/import-emails", methods=["POST"])
def api_import_emails():
    """Trigger email tracking import from Zoho related lists (long-running)."""
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    run_sync_background("import_emails")
    return jsonify({"status": "started", "type": "email_tracking_import",
                    "note": "This may take 2+ hours for ~130K records"})

@app.route("/api/sync/module/<module_name>", methods=["POST"])
def api_sync_single_module(module_name):
    """Sync a single module on demand."""
    if _is_sync_running():
        return jsonify({"error": "Sync already running"}), 409
    # Validate module name
    valid_modules = list(MODULE_TABLE_MAP.keys())
    if module_name not in valid_modules:
        return jsonify({"error": f"Unknown module: {module_name}", "valid": valid_modules}), 400
    run_sync_background("pull", modules=[module_name])
    return jsonify({"status": "started", "module": module_name, "direction": "pull"})

# ---------------------------------------------------------------------------
# ROUTES - API: SQL Query Execution
# ---------------------------------------------------------------------------
@app.route("/api/query", methods=["POST"])
def api_query():
    """Execute a read-only SQL query and return results."""
    data = request.get_json() or {}
    sql = (data.get("sql") or "").strip()
    if not sql:
        return jsonify({"error": "No SQL provided"}), 400

    # Safety: only allow SELECT, WITH, EXPLAIN
    sql_upper = sql.upper().lstrip()
    if not any(sql_upper.startswith(kw) for kw in ("SELECT", "WITH", "EXPLAIN")):
        return jsonify({"error": "Only SELECT / WITH / EXPLAIN queries allowed"}), 400

    limit = data.get("limit", 500)
    conn = get_db()
    cur = conn.cursor()
    try:
        # Wrap in a read-only transaction
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql)
        if cur.description:
            columns = [desc[0] for desc in cur.description]
            rows = [{k: serialize(v) for k, v in dict(r).items()} for r in cur.fetchmany(limit)]
            return jsonify({"columns": columns, "data": rows, "count": len(rows),
                            "truncated": len(rows) >= limit})
        else:
            return jsonify({"columns": [], "data": [], "count": 0, "message": "Query returned no results"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

# ---------------------------------------------------------------------------
# ROUTES - API: Table Management
# ---------------------------------------------------------------------------
@app.route("/api/tables", methods=["GET"])
def api_list_tables():
    """List all tables with row counts and column info."""
    conn = get_db()
    cur = conn.cursor()
    try:
        tables = get_tables()
        result = []
        for t in tables:
            cur.execute(f"SELECT COUNT(*) as cnt FROM {t}")
            cnt = cur.fetchone()["cnt"]
            cols = get_columns(t)
            result.append({
                "name": t,
                "rows": cnt,
                "columns": len(cols),
                "column_details": [{"name": c["column_name"], "type": c["data_type"],
                                    "nullable": c.get("is_nullable", "YES") == "YES"} for c in cols],
                "is_crm": t in TABLE_MODULE_MAP,
                "module": TABLE_MODULE_MAP.get(t)
            })
        return jsonify({"tables": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route("/api/tables/create", methods=["POST"])
def api_create_table():
    """Create a new table with specified columns."""
    data = request.get_json() or {}
    table_name = data.get("name", "").strip().lower()
    columns = data.get("columns", [])

    if not table_name or not columns:
        return jsonify({"error": "Table name and columns required"}), 400

    import re
    if not re.match(r'^[a-z][a-z0-9_]*$', table_name):
        return jsonify({"error": "Invalid table name (use lowercase letters, numbers, underscores)"}), 400

    if table_name in get_tables():
        return jsonify({"error": f"Table '{table_name}' already exists"}), 409

    conn = get_db()
    cur = conn.cursor()
    try:
        col_defs = []
        for c in columns:
            cname = _sanitize_col(c.get("name", ""))
            ctype = c.get("type", "TEXT").upper()
            allowed_types = {"TEXT", "VARCHAR(255)", "INTEGER", "BIGINT", "NUMERIC", "BOOLEAN",
                             "TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "DATE", "JSONB", "UUID"}
            if ctype not in allowed_types:
                ctype = "TEXT"
            nullable = "" if c.get("nullable", True) else " NOT NULL"
            col_defs.append(f"{cname} {ctype}{nullable}")

        col_defs.insert(0, "id SERIAL PRIMARY KEY")
        create_sql = f"CREATE TABLE {table_name} ({', '.join(col_defs)})"
        cur.execute(create_sql)
        conn.commit()
        return jsonify({"status": "created", "table": table_name, "sql": create_sql})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

@app.route("/api/tables/<table_name>/columns", methods=["POST"])
def api_add_column(table_name):
    """Add a column to an existing table."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400
    data = request.get_json() or {}
    col_name = _sanitize_col(data.get("name", ""))
    col_type = data.get("type", "TEXT").upper()
    if not col_name:
        return jsonify({"error": "Column name required"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}")
        conn.commit()
        return jsonify({"status": "added", "table": table_name, "column": col_name, "type": col_type})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

@app.route("/api/tables/<table_name>/drop", methods=["POST"])
def api_drop_table(table_name):
    """Drop a table (non-CRM tables only for safety)."""
    if table_name in TABLE_MODULE_MAP:
        return jsonify({"error": "Cannot drop CRM module tables. Use manual SQL for this."}), 403
    if not table_valid(table_name):
        return jsonify({"error": "Table not found"}), 404

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"DROP TABLE {table_name}")
        conn.commit()
        return jsonify({"status": "dropped", "table": table_name})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

@app.route("/api/tables/<table_name>/truncate", methods=["POST"])
def api_truncate_table(table_name):
    """Truncate a table (remove all rows)."""
    if not table_valid(table_name):
        return jsonify({"error": "Table not found"}), 404
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"TRUNCATE TABLE {table_name}")
        conn.commit()
        cur.execute(f"SELECT COUNT(*) as cnt FROM {table_name}")
        return jsonify({"status": "truncated", "table": table_name, "rows_remaining": cur.fetchone()["cnt"]})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        cur.close()
        conn.close()

@app.route("/api/stats/overview")
def api_stats_overview():
    """Get detailed stats for dashboard charts."""
    try:
        conn = get_db()
    except Exception as e:
        return jsonify({"modules": [], "error": f"DB connection failed: {e}"}), 200
    cur = conn.cursor()
    try:
        tables = get_tables()
        crm_tables = [t for t in tables if t in MODULE_TABLE_MAP.values() or t in TABLE_MODULE_MAP]
        extra_tables = {"email_tracking": "Email Tracking", "visits": "Site Visits"}
        for et in extra_tables:
            if et in tables and et not in crm_tables:
                crm_tables.append(et)

        # Status distribution per module
        modules = []
        for t in crm_tables:
            module_name = TABLE_MODULE_MAP.get(t) or extra_tables.get(t) or t
            row = {"module": module_name, "table": t}

            cur.execute(f"SELECT COUNT(*) as cnt FROM {t}")
            row["total"] = cur.fetchone()["cnt"]

            if has_column(t, "sync_status"):
                for status in ("synced", "pending", "modified", "error"):
                    cur.execute(f"SELECT COUNT(*) as cnt FROM {t} WHERE sync_status=%s", (status,))
                    row[status] = cur.fetchone()["cnt"]
            else:
                for status in ("synced", "pending", "modified", "error"):
                    row[status] = 0

            # Recent activity
            if has_column(t, "updated_at"):
                cur.execute(f"SELECT COUNT(*) as cnt FROM {t} WHERE updated_at > NOW() - INTERVAL '24 hours'")
                row["recent_24h"] = cur.fetchone()["cnt"]
            else:
                row["recent_24h"] = 0

            modules.append(row)

        cur.close()
        conn.close()
        return jsonify({"modules": modules})
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ROUTES - API: Upload
# ---------------------------------------------------------------------------
def _read_upload_file(f, nrows=None):
    """Read an uploaded file (CSV or Excel) into a pandas DataFrame.
    nrows: if set, only read this many rows (for preview)."""
    fname = (f.filename or "").lower()
    if fname.endswith(".csv"):
        return pd.read_csv(f, low_memory=False, nrows=nrows)
    elif fname.endswith(".tsv"):
        return pd.read_csv(f, sep="\t", low_memory=False, nrows=nrows)
    else:
        return pd.read_excel(f, engine="openpyxl", nrows=nrows)


# Background upload job tracking
_upload_jobs: Dict[str, dict] = {}


def _bulk_insert_df_chunk(cur, table_name, df_chunk, col_names, pk):
    """Bulk insert a DataFrame chunk using execute_values (50-100x faster than row-by-row)."""
    valid_cols = [c for c in df_chunk.columns if c in col_names and c != pk and c != "full_name"]
    if not valid_cols:
        return 0, 0, []
    df_chunk = df_chunk[valid_cols]
    df_chunk = df_chunk.where(pd.notnull(df_chunk), None)

    cols_str = ", ".join(valid_cols)
    tpl = "(" + ", ".join(["%s"] * len(valid_cols)) + ")"
    values = [tuple(row[c] for c in valid_cols) for _, row in df_chunk.iterrows()]

    if not values:
        return 0, 0, []

    # Use INSERT ... ON CONFLICT DO NOTHING for speed (no upsert overhead)
    sql = f"INSERT INTO {table_name} ({cols_str}) VALUES %s ON CONFLICT DO NOTHING"
    try:
        psycopg2.extras.execute_values(cur, sql, values, template=tpl, page_size=2000)
        return len(values), 0, []
    except Exception as e:
        # Fallback: try individual inserts
        inserted = 0
        errors = []
        for i, vals in enumerate(values):
            try:
                cur.execute(f"INSERT INTO {table_name} ({cols_str}) VALUES ({', '.join(['%s']*len(valid_cols))})", vals)
                inserted += 1
            except Exception as e2:
                errors.append({"row": i, "error": str(e2)[:200]})
        return inserted, 0, errors


def _background_upload_worker(job_id, file_bytes, filename, table_name, mapping,
                               create_new, new_table_name):
    """Background worker for large file uploads. Streams CSV in chunks."""
    import io as _io
    job = _upload_jobs[job_id]
    job["status"] = "running"
    job["started_at"] = datetime.now().isoformat()

    try:
        is_csv = filename.lower().endswith((".csv", ".tsv"))
        sep = "\t" if filename.lower().endswith(".tsv") else ","

        conn = get_db()
        cur = conn.cursor()

        # --- Auto-create table if needed ---
        if create_new and new_table_name:
            table_name = _sanitize_col(new_table_name)
            # Read a small sample to infer schema
            sample_df = pd.read_csv(_io.BytesIO(file_bytes), sep=sep, nrows=100) if is_csv \
                else pd.read_excel(_io.BytesIO(file_bytes), engine="openpyxl", nrows=100)
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=%s", (table_name,))
            if cur.fetchone():
                job["status"] = "error"
                job["error"] = f"Table '{table_name}' already exists"
                cur.close(); conn.close()
                return
            _create_table_from_df(cur, table_name, sample_df)
            conn.commit()
            mapping = {c: _sanitize_col(c) for c in sample_df.columns}
            job["table"] = table_name
            job["created_table"] = True

        col_names = [c["column_name"] for c in get_columns(table_name)]
        pk = get_pk(table_name)
        has_sync_status = "sync_status" in col_names
        has_created_at = "created_at" in col_names

        chunk_size = 5000
        total_imported = 0
        total_errors = []

        if is_csv:
            # Stream CSV in chunks — never loads entire file
            reader = pd.read_csv(_io.BytesIO(file_bytes), sep=sep, chunksize=chunk_size, low_memory=False)
            chunk_num = 0
            for chunk_df in reader:
                chunk_num += 1
                chunk_df = chunk_df.rename(columns=mapping)
                if has_sync_status and "sync_status" not in chunk_df.columns:
                    chunk_df["sync_status"] = "pending"
                if has_created_at and "created_at" not in chunk_df.columns:
                    chunk_df["created_at"] = datetime.now()

                inserted, _, errs = _bulk_insert_df_chunk(cur, table_name, chunk_df, col_names, pk)
                conn.commit()
                total_imported += inserted
                total_errors.extend(errs[:10])

                job["imported"] = total_imported
                job["chunks_done"] = chunk_num
                job["errors_count"] = len(total_errors)
                logger.info(f"Upload {job_id}: chunk {chunk_num}, total {total_imported} rows inserted")
        else:
            # Excel: must load entirely (openpyxl limitation), but bulk insert in chunks
            df = pd.read_excel(_io.BytesIO(file_bytes), engine="openpyxl")
            df = df.rename(columns=mapping)
            if has_sync_status and "sync_status" not in df.columns:
                df["sync_status"] = "pending"
            if has_created_at and "created_at" not in df.columns:
                df["created_at"] = datetime.now()

            job["total_rows"] = len(df)
            for start in range(0, len(df), chunk_size):
                chunk_df = df.iloc[start:start + chunk_size]
                inserted, _, errs = _bulk_insert_df_chunk(cur, table_name, chunk_df, col_names, pk)
                conn.commit()
                total_imported += inserted
                total_errors.extend(errs[:10])

                job["imported"] = total_imported
                job["chunks_done"] = (start // chunk_size) + 1
                job["errors_count"] = len(total_errors)

        cur.close()
        conn.close()

        job["status"] = "completed"
        job["imported"] = total_imported
        job["errors"] = total_errors[:100]
        job["completed_at"] = datetime.now().isoformat()
        logger.info(f"Upload {job_id}: DONE — {total_imported} rows into {table_name}")

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        logger.error(f"Upload {job_id} failed: {e}", exc_info=True)


def _sanitize_col(name):
    """Convert a column name to a valid PostgreSQL column name."""
    import re
    s = str(name).strip().lower()
    s = re.sub(r'[^a-z0-9_]', '_', s)
    s = re.sub(r'_+', '_', s).strip('_')
    if not s or s[0].isdigit():
        s = "col_" + s
    # Reserved words
    reserved = {"id", "order", "group", "table", "select", "where", "from", "index", "user", "check"}
    if s in reserved:
        s = s + "_val"
    return s[:63]


def _infer_pg_type(series):
    """Infer PostgreSQL column type from a pandas Series."""
    if series.dropna().empty:
        return "TEXT"
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(dtype):
        mx = series.dropna().max()
        if mx < 2147483647:
            return "INTEGER"
        return "BIGINT"
    if pd.api.types.is_float_dtype(dtype):
        # Check if all non-null values are actually integers (pandas float64 due to NaN)
        non_null = series.dropna()
        if len(non_null) > 0 and (non_null == non_null.astype(int)).all():
            mx = non_null.max()
            return "INTEGER" if mx < 2147483647 else "BIGINT"
        return "NUMERIC"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMP"
    # Check if values look like dates
    sample = series.dropna().head(20).astype(str)
    date_like = sum(1 for v in sample if len(v) >= 8 and ("-" in v or "/" in v))
    if date_like > len(sample) * 0.7:
        return "TEXT"  # Keep as text, let user cast
    # Check max length for VARCHAR vs TEXT
    max_len = series.dropna().astype(str).str.len().max() if not series.dropna().empty else 0
    if max_len <= 255:
        return "VARCHAR(255)"
    return "TEXT"


def _create_table_from_df(cur, table_name, df):
    """Auto-create a PostgreSQL table from DataFrame columns."""
    col_defs = ["id UUID PRIMARY KEY DEFAULT gen_random_uuid()"]
    for col in df.columns:
        pg_name = _sanitize_col(col)
        pg_type = _infer_pg_type(df[col])
        col_defs.append(f"{pg_name} {pg_type}")
    col_defs.append("created_at TIMESTAMP DEFAULT NOW()")
    col_defs.append("updated_at TIMESTAMP DEFAULT NOW()")
    ddl = f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(col_defs)})"
    cur.execute(ddl)
    logger.info(f"Created new table: {table_name} with {len(df.columns)} data columns")


@app.route("/api/upload/preview", methods=["POST"])
def api_upload_preview():
    """Preview an Excel/CSV file before import. Supports large files."""
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    table_name = request.form.get("table_name", "")
    create_new = request.form.get("create_new_table", "false").lower() == "true"
    new_table_name = request.form.get("new_table_name", "").strip()

    try:
        # Only read first 100 rows for preview (fast even for huge files)
        df_sample = _read_upload_file(f, nrows=100)
        excel_cols = df_sample.columns.tolist()
        preview = df_sample.head(10).fillna("").to_dict("records")

        # Get total row count for CSV (without loading entire file)
        total_rows = len(df_sample)
        if len(df_sample) >= 100:
            # Estimate total from file size for CSV
            f.seek(0, 2)
            file_size = f.tell()
            f.seek(0)
            if file_size > 0 and total_rows > 0:
                # Read 100 rows to estimate bytes per row
                f.seek(0)
                header_and_sample = f.read(min(file_size, 1024 * 1024))  # 1MB sample
                f.seek(0)
                lines_in_sample = header_and_sample.count(b'\n') if isinstance(header_and_sample, bytes) else header_and_sample.count('\n')
                if lines_in_sample > 1:
                    avg_bytes_per_row = len(header_and_sample) / lines_in_sample
                    total_rows = max(100, int(file_size / avg_bytes_per_row))

        # Auto-suggest column mapping
        table_cols = []
        suggested = {}
        target_table = table_name

        if create_new and new_table_name:
            target_table = _sanitize_col(new_table_name)
            table_cols = [_sanitize_col(c) for c in excel_cols]
            suggested = {ec: _sanitize_col(ec) for ec in excel_cols}
        elif table_name:
            try:
                if table_valid(table_name):
                    table_cols = [c["column_name"] for c in get_columns(table_name)]
                    for ec in excel_cols:
                        ec_lower = ec.lower().replace(" ", "_").replace("-", "_")
                        for tc in table_cols:
                            if ec_lower == tc or ec_lower.replace("_", "") == tc.replace("_", ""):
                                suggested[ec] = tc
                                break
            except Exception:
                pass

        return jsonify({
            "excel_columns": excel_cols,
            "table_columns": table_cols,
            "suggested_mapping": suggested,
            "preview": preview,
            "total_rows": total_rows,
            "total_rows_estimated": total_rows > 100,
            "target_table": target_table,
            "create_new": create_new,
            "inferred_types": {_sanitize_col(c): _infer_pg_type(df_sample[c]) for c in excel_cols} if create_new else {},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload/import", methods=["POST"])
def api_upload_import():
    """Import Excel/CSV data into a table. Runs in background for large files.
    Uses chunked CSV streaming + bulk execute_values INSERT (50-100x faster)."""
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400

    f = request.files["file"]
    table_name = request.form.get("table_name", "")
    mapping = json.loads(request.form.get("column_mapping", "{}"))
    create_new = request.form.get("create_new_table", "false").lower() == "true"
    new_table_name = request.form.get("new_table_name", "").strip()

    if not table_name and not (create_new and new_table_name):
        return jsonify({"error": "No table specified"}), 400
    if not mapping and not create_new:
        return jsonify({"error": "No column mapping"}), 400

    try:
        # Read file bytes into memory (stays under 500MB limit)
        file_bytes = f.read()
        filename = f.filename or "upload.csv"
        file_size_mb = len(file_bytes) / (1024 * 1024)

        # Generate job ID
        import uuid
        job_id = str(uuid.uuid4())[:8]

        _upload_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "table": table_name or _sanitize_col(new_table_name),
            "filename": filename,
            "file_size_mb": round(file_size_mb, 1),
            "imported": 0,
            "chunks_done": 0,
            "errors_count": 0,
            "created_table": False,
            "created_at": datetime.now().isoformat(),
        }

        # Launch background thread
        t = threading.Thread(
            target=_background_upload_worker,
            args=(job_id, file_bytes, filename, table_name, mapping, create_new, new_table_name),
            daemon=True
        )
        t.start()

        return jsonify({
            "success": True,
            "background": True,
            "job_id": job_id,
            "message": f"Upload started in background ({file_size_mb:.1f} MB). Poll /api/upload/status/{job_id} for progress.",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upload/status/<job_id>")
def api_upload_status(job_id):
    """Check status of a background upload job."""
    job = _upload_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/api/upload/jobs")
def api_upload_jobs():
    """List all upload jobs."""
    jobs = sorted(_upload_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return jsonify({"jobs": jobs[:20]})


@app.route("/api/upload/create-table", methods=["POST"])
def api_upload_create_table():
    """Create a new empty table with specified columns."""
    data = request.get_json()
    table_name = _sanitize_col(data.get("table_name", ""))
    columns = data.get("columns", [])

    if not table_name:
        return jsonify({"error": "table_name required"}), 400
    if not columns:
        return jsonify({"error": "columns required (list of {name, type})"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        # Check table doesn't exist
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_name=%s
        """, (table_name,))
        if cur.fetchone():
            cur.close(); conn.close()
            return jsonify({"error": f"Table '{table_name}' already exists"}), 400

        col_defs = ["id UUID PRIMARY KEY DEFAULT gen_random_uuid()"]
        for c in columns:
            cname = _sanitize_col(c.get("name", ""))
            ctype = c.get("type", "TEXT").upper()
            if ctype not in ("TEXT", "VARCHAR(255)", "INTEGER", "BIGINT", "NUMERIC",
                             "BOOLEAN", "TIMESTAMP", "DATE", "JSONB"):
                ctype = "TEXT"
            if cname:
                col_defs.append(f"{cname} {ctype}")
        col_defs.append("created_at TIMESTAMP DEFAULT NOW()")
        col_defs.append("updated_at TIMESTAMP DEFAULT NOW()")

        ddl = f"CREATE TABLE {table_name} ({', '.join(col_defs)})"
        cur.execute(ddl)
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "table": table_name, "columns": len(columns)})
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# Company Name Normalizer (adapted from OpenCode super_app research)
# ---------------------------------------------------------------------------
# 10-stage pipeline for company/account name normalization:
# Unicode NFKC → lowercase → whitespace → punctuation → symbol mapping →
# legal suffix normalization → tokenize → stopword removal → canonical form → phonetic hash

_LEGAL_SUFFIXES = {
    'limited': 'ltd', 'ltd': 'ltd', 'ltd.': 'ltd',
    'incorporated': 'inc', 'inc': 'inc', 'inc.': 'inc',
    'corporation': 'corp', 'corp': 'corp', 'corp.': 'corp',
    'company': 'co', 'co': 'co', 'co.': 'co',
    'llc': 'llc', 'l.l.c.': 'llc', 'l.l.c': 'llc',
    'plc': 'plc', 'p.l.c.': 'plc', 'p.l.c': 'plc',
    'gmbh': 'gmbh', 'g.m.b.h.': 'gmbh',
    'sarl': 'sarl', 's.a.r.l.': 'sarl',
    'bv': 'bv', 'b.v.': 'bv', 'nv': 'nv', 'n.v.': 'nv',
    'sa': 'sa', 's.a.': 'sa', 'ag': 'ag', 'a.g.': 'ag',
    'srl': 'srl', 's.r.l.': 'srl',
    'pty': 'pty', 'pty.': 'pty',
    'llp': 'llp', 'l.l.p.': 'llp',
    'ooo': 'ooo', 'ооо': 'ooo',  # Russian ООО
    'zao': 'zao', 'зао': 'zao',  # Russian ЗАО
    'oao': 'oao', 'оао': 'oao',  # Russian ОАО
    'ip': 'ip', 'ип': 'ip',      # Russian ИП
}

_COMPANY_STOPWORDS = {'the', 'of', 'in', 'for', 'to', 'an', 'at', 'by', 'with', 'from', 'a'}

# Soundex lookup for phonetic hashing
_SOUNDEX_MAP = {
    'b': '1', 'f': '1', 'p': '1', 'v': '1',
    'c': '2', 'g': '2', 'j': '2', 'k': '2', 'q': '2', 's': '2', 'x': '2', 'z': '2',
    'd': '3', 't': '3',
    'l': '4',
    'm': '5', 'n': '5',
    'r': '6',
}


def _soundex(text):
    """Soundex phonetic hash."""
    clean = re.sub(r'[^a-z]', '', text.lower())
    if not clean:
        return ""
    result = [clean[0].upper()]
    prev = _SOUNDEX_MAP.get(clean[0], '')
    for ch in clean[1:]:
        code = _SOUNDEX_MAP.get(ch, '')
        if code and code != prev:
            result.append(code)
        prev = code if code else prev
    return ''.join(result[:4]).ljust(4, '0')


def normalize_company_name(name):
    """Normalize a company/account name through a 12-stage pipeline.
    Based on OpenCode METHODS_REFERENCE: strips legal suffixes entirely so
    "AECOM LIMITED", "AECOM LTD", "AECOM LLC" all become "aecom".
    Returns dict with: normalized, stripped (no suffix), tokens, canonical,
    phonetic, legal_suffix found."""
    if not name or not isinstance(name, str):
        return {"normalized": "", "stripped": "", "tokens": [], "canonical": "",
                "phonetic": "", "legal_suffix": ""}

    import unicodedata as _ud

    # Stage 1: Unicode NFKC
    text = _ud.normalize('NFKC', name)
    # Stage 2: Lowercase
    text = text.lower()
    # Stage 3: Whitespace normalization
    text = ' '.join(text.split())
    # Stage 4: Remove CRN/registration codes in parentheses — e.g. "CONSULTUS (PEMXQ) LTD"
    text = re.sub(r'\s*\([A-Za-z0-9]+\)\s*', ' ', text)
    # Stage 5: Punctuation — keep & and alphanumerics
    text = re.sub(r'[""''`]', "'", text)
    text = re.sub(r'[—–−]', '-', text)
    text = re.sub(r'[^\w\s&]', ' ', text)
    # Stage 6: Symbol mapping
    text = text.replace('&', ' and ')
    text = ' '.join(text.split())

    # Stage 7: Legal suffix detection and REMOVAL (OpenCode approach: strip entirely)
    words = text.split()
    legal_suffix = ""
    core_words = []
    for w in words:
        clean_w = re.sub(r'[^\w]', '', w).lower()
        if clean_w in _LEGAL_SUFFIXES:
            legal_suffix = _LEGAL_SUFFIXES[clean_w]
            # Don't add to core_words — strip the suffix entirely
        else:
            core_words.append(w)

    # Stage 8: Stopword removal (keep 'and' — important for company names)
    tokens = [t for t in core_words if t and t not in _COMPANY_STOPWORDS]
    # Stage 9: "stripped" form — company name without any legal suffix (order preserved)
    stripped = ' '.join(tokens)
    # Stage 10: Canonical form (sorted tokens for order-independent matching)
    canonical = ' '.join(sorted(tokens)) if tokens else ""
    # Stage 11: Phonetic hash on stripped name
    phonetic = _soundex(stripped)
    # Stage 12: "normalized" form — includes suffix for display, stripped for matching
    normalized = stripped + (f" {legal_suffix}" if legal_suffix else "")

    return {
        "normalized": normalized,
        "stripped": stripped,
        "tokens": tokens,
        "canonical": canonical,
        "phonetic": phonetic,
        "legal_suffix": legal_suffix,
    }


def normalize_person_name(first_name, last_name):
    """Normalize a person name (title removal, unicode, canonical form)."""
    import unicodedata as _ud
    titles = {'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'sir', 'lord', 'lady',
              'duke', 'baron', 'earl', 'count', 'countess', 'rev', 'fr'}

    parts = []
    for raw in (first_name, last_name):
        if not raw or not isinstance(raw, str):
            continue
        text = _ud.normalize('NFKC', raw).lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        words = [w for w in text.split() if w.rstrip('.') not in titles]
        parts.extend(words)

    canonical = ' '.join(sorted(parts)) if parts else ""
    phonetic = _soundex(' '.join(parts))
    return {
        "normalized": ' '.join(parts),
        "tokens": parts,
        "canonical": canonical,
        "phonetic": phonetic,
    }


# ---------------------------------------------------------------------------
# ROUTES - API: Enrich
# ---------------------------------------------------------------------------
@app.route("/api/enrich/duplicates/<table_name>")
def api_enrich_duplicates(table_name):
    """Find duplicate records based on email/phone/name."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    conn = get_db()
    cur = conn.cursor()
    cols = [c["column_name"] for c in get_columns(table_name)]
    duplicates = []

    try:
        # Check email duplicates
        if "email" in cols:
            cur.execute(f"""
                SELECT email, COUNT(*) as cnt, array_agg(id::text) as ids
                FROM {table_name}
                WHERE email IS NOT NULL AND email != ''
                GROUP BY email HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT 50
            """)
            for r in cur.fetchall():
                duplicates.append({"field": "email", "value": r["email"],
                                   "count": r["cnt"], "ids": r["ids"]})

        # Check phone duplicates
        if "phone" in cols:
            cur.execute(f"""
                SELECT phone, COUNT(*) as cnt, array_agg(id::text) as ids
                FROM {table_name}
                WHERE phone IS NOT NULL AND phone != ''
                GROUP BY phone HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT 50
            """)
            for r in cur.fetchall():
                duplicates.append({"field": "phone", "value": r["phone"],
                                   "count": r["cnt"], "ids": r["ids"]})

        # Check name duplicates (for tables with first/last name)
        if "first_name" in cols and "last_name" in cols:
            cur.execute(f"""
                SELECT first_name, last_name, COUNT(*) as cnt, array_agg(id::text) as ids
                FROM {table_name}
                WHERE first_name IS NOT NULL AND last_name IS NOT NULL
                GROUP BY first_name, last_name HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT 50
            """)
            for r in cur.fetchall():
                duplicates.append({"field": "name", "value": f"{r['first_name']} {r['last_name']}",
                                   "count": r["cnt"], "ids": r["ids"]})

        # Check account name duplicates
        if "account_name" in cols:
            cur.execute(f"""
                SELECT account_name, COUNT(*) as cnt, array_agg(id::text) as ids
                FROM {table_name}
                WHERE account_name IS NOT NULL AND account_name != ''
                GROUP BY account_name HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT 50
            """)
            for r in cur.fetchall():
                duplicates.append({"field": "account_name", "value": r["account_name"],
                                   "count": r["cnt"], "ids": r["ids"]})

        # Check deal name duplicates
        if "deal_name" in cols:
            cur.execute(f"""
                SELECT deal_name, COUNT(*) as cnt, array_agg(id::text) as ids
                FROM {table_name}
                WHERE deal_name IS NOT NULL AND deal_name != ''
                GROUP BY deal_name HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT 50
            """)
            for r in cur.fetchall():
                duplicates.append({"field": "deal_name", "value": r["deal_name"],
                                   "count": r["cnt"], "ids": r["ids"]})

        # Check subject duplicates (tasks, events, cases)
        if "subject" in cols and table_name in ("tasks", "events", "cases", "quotes", "invoices"):
            cur.execute(f"""
                SELECT subject, COUNT(*) as cnt, array_agg(id::text) as ids
                FROM {table_name}
                WHERE subject IS NOT NULL AND subject != ''
                GROUP BY subject HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT 30
            """)
            for r in cur.fetchall():
                duplicates.append({"field": "subject", "value": r["subject"],
                                   "count": r["cnt"], "ids": r["ids"]})

        cur.close()
        conn.close()
        return jsonify({"duplicates": duplicates, "total": len(duplicates)})
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/enrich/completeness/<table_name>")
def api_enrich_completeness(table_name):
    """Analyze field completeness for a table."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) as total FROM {table_name}")
        total = cur.fetchone()["total"]
        if total == 0:
            return jsonify({"fields": [], "total": 0})

        cols = get_columns(table_name)
        fields = []
        # Skip system columns
        skip = {"id", "created_at", "updated_at", "deleted_at", "sync_status",
                "sync_version", "last_sync_at", "full_name", "custom_fields",
                "zoho_created_time", "zoho_modified_time", "zoho_created_by", "zoho_modified_by"}

        for c in cols:
            cn = c["column_name"]
            if cn in skip:
                continue
            cur.execute(f"SELECT COUNT(*) as filled FROM {table_name} WHERE {cn} IS NOT NULL AND {cn}::text != ''")
            filled = cur.fetchone()["filled"]
            pct = round((filled / total) * 100, 1) if total > 0 else 0
            fields.append({"field": cn, "filled": filled, "empty": total - filled,
                           "total": total, "completeness": pct})

        fields.sort(key=lambda x: x["completeness"])

        cur.close()
        conn.close()
        return jsonify({"fields": fields, "total": total})
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/enrich/validate/<table_name>")
def api_enrich_validate(table_name):
    """Validate data quality (email format, required fields, etc)."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    conn = get_db()
    cur = conn.cursor()
    issues = []

    try:
        cols = [c["column_name"] for c in get_columns(table_name)]

        # Check invalid emails
        if "email" in cols:
            cur.execute(f"""
                SELECT id::text, email FROM {table_name}
                WHERE email IS NOT NULL AND email != ''
                AND email !~ '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{{2,}}$'
                LIMIT 50
            """)
            for r in cur.fetchall():
                issues.append({"type": "invalid_email", "id": r["id"],
                               "field": "email", "value": r["email"]})

        # Check missing required fields
        required = {
            "leads": ["last_name", "company"], "contacts": ["last_name"],
            "accounts": ["account_name"], "deals": ["deal_name", "stage"],
            "tasks": ["subject"], "events": ["subject"],
            "products": ["product_name"], "vendors": ["vendor_name"],
            "cases": ["subject"], "campaigns": ["campaign_name"],
            "quotes": ["subject"], "invoices": ["subject"],
            "sales_orders": ["sales_order_name"], "purchase_orders": ["purchase_order_name"],
            "solutions": ["solution_title"],
        }
        req_fields = required.get(table_name, [])
        for rf in req_fields:
            if rf in cols:
                cur.execute(f"SELECT id::text FROM {table_name} WHERE {rf} IS NULL OR {rf}='' LIMIT 20")
                for r in cur.fetchall():
                    issues.append({"type": "missing_required", "id": r["id"],
                                   "field": rf, "value": None})

        # Check records with no zoho_id (not synced to CRM)
        if "zoho_id" in cols:
            cur.execute(f"SELECT COUNT(*) as cnt FROM {table_name} WHERE zoho_id IS NULL OR zoho_id=''")
            no_zoho = cur.fetchone()["cnt"]
            if no_zoho > 0:
                issues.append({"type": "no_zoho_id", "count": no_zoho,
                               "field": "zoho_id", "message": f"{no_zoho} records not linked to Zoho CRM"})

        cur.close()
        conn.close()
        return jsonify({"issues": issues, "total": len(issues)})
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/enrich/duplicates/<table_name>/detail")
def api_enrich_duplicate_detail(table_name):
    """Get full records for a set of duplicate IDs to enable merge review."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400
    ids = request.args.get("ids", "").split(",")
    if not ids or ids == [""]:
        return jsonify({"error": "No ids provided"}), 400

    pk = get_pk(table_name)
    conn = get_db()
    cur = conn.cursor()
    try:
        phs = ",".join(["%s"] * len(ids))
        cur.execute(f"SELECT * FROM {table_name} WHERE {pk} IN ({phs})", ids)
        rows = [{k: serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]
        cols = get_columns(table_name)
        cur.close()
        conn.close()
        return jsonify({
            "records": rows,
            "columns": [{"name": c["column_name"], "type": c["data_type"]} for c in cols],
            "primary_key": pk
        })
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

@app.route("/api/enrich/fuzzy-duplicates/<table_name>")
def api_enrich_fuzzy_duplicates(table_name):
    """Find near-duplicate records using normalized matching and trigram similarity.
    Optimized for 100K+ records: uses GIN indexes, SET similarity_threshold, and LIMIT."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    threshold = request.args.get("threshold", 0.6, type=float)
    page_limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    conn = get_db()
    cur = conn.cursor()
    cols = [c["column_name"] for c in get_columns(table_name)]
    pk = get_pk(table_name)
    fuzzy_dupes = []

    try:
        # Ensure pg_trgm
        has_trgm = False
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            conn.commit()
            has_trgm = True
        except Exception:
            conn.rollback()

        # Create GIN indexes on LOWER(TRIM(...)) for fuzzy matching via % operator
        if has_trgm:
            for field in ("first_name", "last_name", "email", "phone", "company", "account_name"):
                if field in cols:
                    idx_name = f"idx_trgm_{table_name}_{field}"
                    try:
                        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} USING gin (LOWER(TRIM({field})) gin_trgm_ops)")
                        conn.commit()
                    except Exception:
                        conn.rollback()
            # Composite expression index for name fuzzy matching
            if "first_name" in cols and "last_name" in cols:
                try:
                    cur.execute(f"""CREATE INDEX IF NOT EXISTS idx_trgm_{table_name}_fullname
                        ON {table_name} USING gin (
                            LOWER(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,''))) gin_trgm_ops
                        )""")
                    conn.commit()
                except Exception:
                    conn.rollback()

            # Set similarity threshold at session level (used by % operator)
            cur.execute("SET pg_trgm.similarity_threshold = %s", (threshold,))

        # --- Phone normalization duplicates (GROUP BY — efficient even at 1M) ---
        if "phone" in cols:
            cur.execute(f"""
                SELECT REGEXP_REPLACE(phone, '[^0-9+]', '', 'g') as norm_phone,
                       COUNT(*) as cnt, array_agg(id::text ORDER BY id) as ids,
                       array_agg(phone ORDER BY id) as phones
                FROM {table_name}
                WHERE phone IS NOT NULL AND phone != ''
                AND LENGTH(REGEXP_REPLACE(phone, '[^0-9]', '', 'g')) >= 6
                GROUP BY norm_phone HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT %s OFFSET %s
            """, (page_limit, offset))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "phone_normalized", "field": "phone",
                    "value": r["norm_phone"], "variants": r["phones"][:10],
                    "count": r["cnt"], "ids": r["ids"][:10],
                })

        # --- Email local-part duplicates (GROUP BY — efficient) ---
        if "email" in cols:
            cur.execute(f"""
                SELECT LOWER(SPLIT_PART(email, '@', 1)) as local_part,
                       COUNT(*) as cnt, array_agg(id::text ORDER BY id) as ids,
                       array_agg(email ORDER BY id) as emails
                FROM {table_name}
                WHERE email IS NOT NULL AND email LIKE '%%@%%'
                GROUP BY local_part HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT %s OFFSET %s
            """, (page_limit, offset))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "email_local_part", "field": "email",
                    "value": r["local_part"], "variants": r["emails"][:10],
                    "count": r["cnt"], "ids": r["ids"][:10],
                })

        # --- Fuzzy name matching: sample-based lateral join (fast at any scale) ---
        # Strategy: pick candidate names with duplicates, then use GIN index to find similar
        if has_trgm and "first_name" in cols and "last_name" in cols:
            # First: exact name duplicates after normalization (very fast GROUP BY)
            cur.execute(f"""
                SELECT LOWER(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,''))) as full_n,
                       COUNT(*) as cnt, array_agg({pk}::text ORDER BY {pk}) as ids
                FROM {table_name}
                WHERE COALESCE(first_name,'')||COALESCE(last_name,'') != ''
                GROUP BY full_n HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT %s OFFSET %s
            """, (page_limit, offset))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "exact_name", "field": "name",
                    "value": r["full_n"],
                    "similarity": 1.0,
                    "count": r["cnt"], "ids": r["ids"][:10],
                })

            # Then: approximate fuzzy matches via lateral join on sample (uses GIN index per lookup)
            cur.execute(f"""
                WITH samples AS (
                    SELECT DISTINCT LOWER(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,''))) as full_n
                    FROM {table_name}
                    WHERE COALESCE(first_name,'')||COALESCE(last_name,'') != ''
                    AND LENGTH(COALESCE(first_name,'')) >= 2
                    ORDER BY full_n LIMIT 500
                )
                SELECT s.full_n as name_a, m.full_n as name_b,
                       similarity(s.full_n, m.full_n) as sim,
                       m.ids
                FROM samples s,
                LATERAL (
                    SELECT LOWER(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,''))) as full_n,
                           array_agg({pk}::text) as ids
                    FROM {table_name}
                    WHERE COALESCE(first_name,'')||COALESCE(last_name,'') != ''
                    AND LOWER(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,''))) %% s.full_n
                    AND LOWER(TRIM(COALESCE(first_name,'')||' '||COALESCE(last_name,''))) != s.full_n
                    GROUP BY 1
                    LIMIT 3
                ) m
                WHERE similarity(s.full_n, m.full_n) > %s
                ORDER BY sim DESC LIMIT %s
            """, (threshold, page_limit))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "fuzzy_name", "field": "name",
                    "value": f"{r['name_a']} ~ {r['name_b']}",
                    "similarity": round(r["sim"], 3),
                    "count": len(r["ids"]) + 1, "ids": r["ids"][:10],
                })

        # --- Fuzzy account_name matching (lateral join + GIN index) ---
        if has_trgm and "account_name" in cols:
            # Exact normalized duplicates first
            cur.execute(f"""
                SELECT LOWER(TRIM(account_name)) as acct,
                       COUNT(*) as cnt, array_agg({pk}::text ORDER BY {pk}) as ids
                FROM {table_name}
                WHERE account_name IS NOT NULL AND account_name != ''
                GROUP BY acct HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT %s OFFSET %s
            """, (page_limit, offset))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "exact_account", "field": "account_name",
                    "value": r["acct"], "similarity": 1.0,
                    "count": r["cnt"], "ids": r["ids"][:10],
                })

            # Fuzzy via lateral
            cur.execute(f"""
                WITH samples AS (
                    SELECT DISTINCT LOWER(TRIM(account_name)) as acct
                    FROM {table_name}
                    WHERE account_name IS NOT NULL AND account_name != '' AND LENGTH(account_name) >= 3
                    ORDER BY acct LIMIT 500
                )
                SELECT s.acct as acct_a, m.acct as acct_b,
                       similarity(s.acct, m.acct) as sim, m.ids
                FROM samples s,
                LATERAL (
                    SELECT LOWER(TRIM(account_name)) as acct, array_agg({pk}::text) as ids
                    FROM {table_name}
                    WHERE account_name IS NOT NULL AND account_name != ''
                    AND LOWER(TRIM(account_name)) %% s.acct
                    AND LOWER(TRIM(account_name)) != s.acct
                    GROUP BY 1 LIMIT 3
                ) m
                WHERE similarity(s.acct, m.acct) > %s
                ORDER BY sim DESC LIMIT %s
            """, (threshold, page_limit))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "fuzzy_account", "field": "account_name",
                    "value": f"{r['acct_a']} ~ {r['acct_b']}",
                    "similarity": round(r["sim"], 3),
                    "count": len(r["ids"]) + 1, "ids": r["ids"][:10],
                })

        # --- Fuzzy company matching (lateral join + GIN index) ---
        if has_trgm and "company" in cols:
            # Exact normalized duplicates
            cur.execute(f"""
                SELECT LOWER(TRIM(company)) as comp,
                       COUNT(*) as cnt, array_agg({pk}::text ORDER BY {pk}) as ids
                FROM {table_name}
                WHERE company IS NOT NULL AND company != ''
                GROUP BY comp HAVING COUNT(*) > 1
                ORDER BY cnt DESC LIMIT %s OFFSET %s
            """, (page_limit, offset))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "exact_company", "field": "company",
                    "value": r["comp"], "similarity": 1.0,
                    "count": r["cnt"], "ids": r["ids"][:10],
                })

            # Fuzzy via lateral
            cur.execute(f"""
                WITH samples AS (
                    SELECT DISTINCT LOWER(TRIM(company)) as comp
                    FROM {table_name}
                    WHERE company IS NOT NULL AND company != '' AND LENGTH(company) >= 3
                    ORDER BY comp LIMIT 500
                )
                SELECT s.comp as comp_a, m.comp as comp_b,
                       similarity(s.comp, m.comp) as sim, m.ids
                FROM samples s,
                LATERAL (
                    SELECT LOWER(TRIM(company)) as comp, array_agg({pk}::text) as ids
                    FROM {table_name}
                    WHERE company IS NOT NULL AND company != ''
                    AND LOWER(TRIM(company)) %% s.comp
                    AND LOWER(TRIM(company)) != s.comp
                    GROUP BY 1 LIMIT 3
                ) m
                WHERE similarity(s.comp, m.comp) > %s
                ORDER BY sim DESC LIMIT %s
            """, (threshold, page_limit))
            for r in cur.fetchall():
                fuzzy_dupes.append({
                    "type": "fuzzy_company", "field": "company",
                    "value": f"{r['comp_a']} ~ {r['comp_b']}",
                    "similarity": round(r["sim"], 3),
                    "count": len(r["ids"]) + 1, "ids": r["ids"][:10],
                })

        cur.close()
        conn.close()
        return jsonify({
            "fuzzy_duplicates": fuzzy_dupes, "total": len(fuzzy_dupes),
            "has_trgm": has_trgm, "threshold": threshold,
            "limit": page_limit, "offset": offset,
        })
    except Exception as e:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrich/normalized-duplicates/<table_name>")
def api_enrich_normalized_duplicates(table_name):
    """Find duplicate company/account names using the 10-stage normalizer pipeline.
    Catches duplicates that LOWER(TRIM()) misses: 'Ltd' vs 'Limited', '&' vs 'and',
    legal suffix variants, and phonetic typo matches.
    Works on: account_name, company, first_name+last_name."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400

    page_limit = request.args.get("limit", 100, type=int)
    mode = request.args.get("mode", "all")  # all, company, person
    conn = get_db()
    cur = conn.cursor()
    cols = [c["column_name"] for c in get_columns(table_name)]
    pk = get_pk(table_name)
    clusters = []
    stats = {"total_values": 0, "total_clusters": 0, "methods": []}

    try:
        # --- Company / Account name normalization ---
        if mode in ("all", "company"):
            for field in ("account_name", "company"):
                if field not in cols:
                    continue

                # Fetch all distinct non-empty values with their record IDs
                cur.execute(f"""
                    SELECT {field} as val, array_agg({pk}::text ORDER BY {pk}) as ids,
                           COUNT(*) as cnt
                    FROM {table_name}
                    WHERE {field} IS NOT NULL AND TRIM({field}) != ''
                    GROUP BY {field}
                    ORDER BY {field}
                """)
                rows = cur.fetchall()
                stats["total_values"] += len(rows)

                # Normalize all values in Python — fast for distinct values (typically 1-10K)
                by_stripped = {}    # stripped (no suffix) → list of entries
                by_canonical = {}   # canonical (sorted, no suffix) → list of entries
                by_phonetic = {}    # phonetic_hash → list of entries

                for r in rows:
                    val = r["val"]
                    n = normalize_company_name(val)
                    entry = {"original": val, "ids": r["ids"], "count": r["cnt"], "norm": n}

                    # Group by stripped form (AECOM Ltd → aecom, AECOM Limited → aecom)
                    if n["stripped"]:
                        by_stripped.setdefault(n["stripped"], []).append(entry)
                    # Group by canonical form (sorted tokens, catches word reorder too)
                    if n["canonical"]:
                        by_canonical.setdefault(n["canonical"], []).append(entry)
                    # Group by phonetic hash (catches typos)
                    if n["phonetic"] and len(n["tokens"]) >= 2:
                        by_phonetic.setdefault(n["phonetic"], []).append(entry)

                # Priority 1: Stripped-form clusters (most useful — "AECOM Ltd" = "AECOM Limited" = "AECOM")
                stripped_originals = set()
                for stripped, entries in by_stripped.items():
                    if len(entries) < 2:
                        continue
                    originals = set(e["original"].lower().strip() for e in entries)
                    if len(originals) < 2:
                        continue
                    all_ids = []
                    variants = []
                    for e in entries[:10]:
                        all_ids.extend(e["ids"][:5])
                        variants.append({"value": e["original"], "count": e["count"],
                                         "normalized": e["norm"]["normalized"],
                                         "legal_suffix": e["norm"]["legal_suffix"]})
                    total = sum(e["count"] for e in entries)
                    clusters.append({
                        "type": "suffix_stripped", "field": field,
                        "stripped": stripped,
                        "variants": variants,
                        "count": total, "distinct_values": len(entries),
                        "ids": all_ids[:20],
                        "match_reason": "Same company after stripping legal suffixes (Ltd/Limited/LLC/Inc/Corp/GmbH)",
                    })
                    for e in entries:
                        stripped_originals.add(e["original"].lower().strip())

                # Priority 2: Canonical clusters — catches word-reorder not found by stripped
                for canonical, entries in by_canonical.items():
                    if len(entries) < 2:
                        continue
                    novel = [e for e in entries
                             if e["original"].lower().strip() not in stripped_originals]
                    if len(novel) < 2:
                        continue
                    originals = set(e["original"].lower().strip() for e in novel)
                    if len(originals) < 2:
                        continue
                    all_ids = []
                    variants = []
                    for e in novel[:10]:
                        all_ids.extend(e["ids"][:5])
                        variants.append({"value": e["original"], "count": e["count"],
                                         "normalized": e["norm"]["normalized"],
                                         "legal_suffix": e["norm"]["legal_suffix"]})
                    total = sum(e["count"] for e in novel)
                    clusters.append({
                        "type": "canonical_reorder", "field": field,
                        "canonical": canonical,
                        "variants": variants,
                        "count": total, "distinct_values": len(novel),
                        "ids": all_ids[:20],
                        "match_reason": "Same tokens in different order + suffix stripped",
                    })
                    for e in novel:
                        stripped_originals.add(e["original"].lower().strip())

                # Priority 3: Phonetic — only for entries not already found, strict token overlap
                for phon, entries in by_phonetic.items():
                    if len(entries) < 2 or not phon:
                        continue
                    novel = [e for e in entries
                             if e["original"].lower().strip() not in stripped_originals]
                    if len(novel) < 2:
                        continue
                    originals = set(e["original"].lower().strip() for e in novel)
                    if len(originals) < 2:
                        continue
                    # Strict filter: require ≥50% Jaccard token overlap to avoid noise
                    first_tokens = set(novel[0]["norm"]["tokens"])
                    related = [novel[0]]
                    for e in novel[1:]:
                        e_tokens = set(e["norm"]["tokens"])
                        shared = first_tokens & e_tokens
                        total = first_tokens | e_tokens
                        jaccard = len(shared) / len(total) if total else 0
                        if jaccard >= 0.5 and len(shared) >= 2:
                            related.append(e)
                    if len(related) < 2:
                        continue
                    all_ids = []
                    variants = []
                    for e in related[:10]:
                        all_ids.extend(e["ids"][:5])
                        variants.append({"value": e["original"], "count": e["count"],
                                         "normalized": e["norm"]["normalized"],
                                         "phonetic": e["norm"]["phonetic"]})
                    total = sum(e["count"] for e in related)
                    clusters.append({
                        "type": "phonetic_match", "field": field,
                        "phonetic": phon,
                        "variants": variants,
                        "count": total, "distinct_values": len(related),
                        "ids": all_ids[:20],
                        "match_reason": "Similar sound (Soundex) + shared tokens — possible typos",
                    })

                stats["methods"].append(f"{field}: {len(rows)} distinct values")

        # --- Person name normalization ---
        if mode in ("all", "person") and "first_name" in cols and "last_name" in cols:
            cur.execute(f"""
                SELECT first_name, last_name, array_agg({pk}::text ORDER BY {pk}) as ids,
                       COUNT(*) as cnt
                FROM {table_name}
                WHERE COALESCE(first_name,'')||COALESCE(last_name,'') != ''
                GROUP BY first_name, last_name
                ORDER BY first_name, last_name
            """)
            rows = cur.fetchall()
            stats["total_values"] += len(rows)

            by_canonical = {}
            by_phonetic = {}

            for r in rows:
                n = normalize_person_name(r["first_name"], r["last_name"])
                orig_display = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
                entry = {"original": orig_display, "ids": r["ids"], "count": r["cnt"], "norm": n}

                if n["canonical"]:
                    by_canonical.setdefault(n["canonical"], []).append(entry)
                if n["phonetic"]:
                    by_phonetic.setdefault(n["phonetic"], []).append(entry)

            for canonical, entries in by_canonical.items():
                if len(entries) < 2:
                    continue
                originals = set(e["original"].lower().strip() for e in entries)
                if len(originals) < 2:
                    continue
                all_ids = []
                variants = []
                for e in entries[:10]:
                    all_ids.extend(e["ids"][:5])
                    variants.append({"value": e["original"], "count": e["count"],
                                     "normalized": e["norm"]["normalized"]})
                total = sum(e["count"] for e in entries)
                clusters.append({
                    "type": "normalized_person", "field": "name",
                    "canonical": canonical,
                    "variants": variants,
                    "count": total, "distinct_values": len(entries),
                    "ids": all_ids[:20],
                    "match_reason": "Same person after title removal + normalization",
                })

            stats["methods"].append(f"person_name: {len(rows)} distinct values")

        # Sort by cluster size (biggest first)
        clusters.sort(key=lambda c: c["count"], reverse=True)
        clusters = clusters[:page_limit]
        stats["total_clusters"] = len(clusters)

        cur.close()
        conn.close()
        return jsonify({
            "normalized_duplicates": clusters,
            "total": len(clusters),
            "stats": stats,
            "mode": mode,
        })
    except Exception as e:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        logger.error(f"Normalized dedup error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrich/cross-module-duplicates")
def api_enrich_cross_module_duplicates():
    """Find records that appear in multiple modules (e.g. lead also exists as contact).
    Uses expression indexes for efficient cross-table matching at scale."""
    page_limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    try:
        conn = get_db()
    except Exception as e:
        return jsonify({"cross_duplicates": [], "error": f"DB connection failed: {e}"}), 200

    cur = conn.cursor()
    cross_dupes = []
    tables = get_tables()

    # Define cross-module pairs to check
    pairs = [
        ("leads", "contacts", "email", "email"),
        ("leads", "contacts", "phone", "phone"),
    ]

    try:
        # Create expression indexes for fast cross-module joins (idempotent)
        for tbl in ("leads", "contacts", "accounts"):
            if tbl not in tables:
                continue
            tbl_cols = [c["column_name"] for c in get_columns(tbl)]
            for field in ("email", "phone", "first_name", "last_name", "company", "account_name"):
                if field in tbl_cols:
                    idx = f"idx_lower_{tbl}_{field}"
                    try:
                        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON {tbl} (LOWER(TRIM({field}))) WHERE {field} IS NOT NULL AND {field} != ''")
                        conn.commit()
                    except Exception:
                        conn.rollback()

        for t1, t2, f1, f2 in pairs:
            if t1 not in tables or t2 not in tables:
                continue
            cols1 = [c["column_name"] for c in get_columns(t1)]
            cols2 = [c["column_name"] for c in get_columns(t2)]
            if f1 not in cols1 or f2 not in cols2:
                continue

            pk1 = get_pk(t1)
            pk2 = get_pk(t2)
            cur.execute(f"""
                SELECT a.{pk1}::text as id_a, b.{pk2}::text as id_b,
                       a.{f1} as value
                FROM {t1} a JOIN {t2} b ON LOWER(TRIM(a.{f1})) = LOWER(TRIM(b.{f2}))
                WHERE a.{f1} IS NOT NULL AND a.{f1} != ''
                AND b.{f2} IS NOT NULL AND b.{f2} != ''
                LIMIT %s OFFSET %s
            """, (page_limit, offset))
            for r in cur.fetchall():
                cross_dupes.append({
                    "field": f1,
                    "value": r["value"],
                    "source_table": t1, "source_id": r["id_a"],
                    "target_table": t2, "target_id": r["id_b"],
                })

        # Name-based cross-module match
        name_tables = [t for t in ("leads", "contacts") if t in tables]
        if len(name_tables) == 2:
            t1, t2 = name_tables
            cols1 = [c["column_name"] for c in get_columns(t1)]
            cols2 = [c["column_name"] for c in get_columns(t2)]
            if all(f in cols1 for f in ("first_name", "last_name")) and all(f in cols2 for f in ("first_name", "last_name")):
                pk1 = get_pk(t1)
                pk2 = get_pk(t2)
                cur.execute(f"""
                    SELECT a.{pk1}::text as id_a, b.{pk2}::text as id_b,
                           a.first_name||' '||a.last_name as name_a,
                           b.first_name||' '||b.last_name as name_b
                    FROM {t1} a JOIN {t2} b
                        ON LOWER(TRIM(a.first_name)) = LOWER(TRIM(b.first_name))
                        AND LOWER(TRIM(a.last_name)) = LOWER(TRIM(b.last_name))
                    WHERE a.first_name IS NOT NULL AND a.last_name IS NOT NULL
                    AND b.first_name IS NOT NULL AND b.last_name IS NOT NULL
                    LIMIT %s OFFSET %s
                """, (page_limit, offset))
                for r in cur.fetchall():
                    cross_dupes.append({
                        "field": "name",
                        "value": r["name_a"],
                        "source_table": t1, "source_id": r["id_a"],
                        "target_table": t2, "target_id": r["id_b"],
                    })

        # Accounts vs leads (company name = account name) — exact + normalized match
        if "leads" in tables and "accounts" in tables:
            leads_cols = [c["column_name"] for c in get_columns("leads")]
            accts_cols = [c["column_name"] for c in get_columns("accounts")]
            if "company" in leads_cols and "account_name" in accts_cols:
                lpk = get_pk("leads")
                apk = get_pk("accounts")
                # SQL exact match (LOWER/TRIM)
                cur.execute(f"""
                    SELECT l.{lpk}::text as lead_id, a.{apk}::text as account_id,
                           l.company as lead_company, a.account_name as account_name
                    FROM leads l JOIN accounts a
                        ON LOWER(TRIM(l.company)) = LOWER(TRIM(a.account_name))
                    WHERE l.company IS NOT NULL AND l.company != ''
                    AND a.account_name IS NOT NULL AND a.account_name != ''
                    LIMIT %s OFFSET %s
                """, (page_limit, offset))
                for r in cur.fetchall():
                    cross_dupes.append({
                        "field": "company/account_name",
                        "value": r["lead_company"],
                        "source_table": "leads", "source_id": r["lead_id"],
                        "target_table": "accounts", "target_id": r["account_id"],
                    })

                # Normalized match — catches Ltd vs Limited, & vs and, etc.
                exact_pairs = {(d["source_id"], d["target_id"])
                               for d in cross_dupes if d.get("field") == "company/account_name"}
                try:
                    cur.execute(f"SELECT {lpk}::text as id, company as val FROM leads WHERE company IS NOT NULL AND company != ''")
                    lead_companies = cur.fetchall()
                    cur.execute(f"SELECT {apk}::text as id, account_name as val FROM accounts WHERE account_name IS NOT NULL AND account_name != ''")
                    acct_names = cur.fetchall()

                    # Build normalized index from accounts (stripped = no legal suffix)
                    acct_by_stripped = {}
                    for a in acct_names:
                        n = normalize_company_name(a["val"])
                        if n["stripped"]:
                            acct_by_stripped.setdefault(n["stripped"], []).append(a)

                    # Match leads against accounts by stripped form
                    norm_count = 0
                    for l in lead_companies:
                        n = normalize_company_name(l["val"])
                        if not n["stripped"]:
                            continue
                        matches = acct_by_stripped.get(n["stripped"], [])
                        for a in matches:
                            pair = (l["id"], a["id"])
                            if pair in exact_pairs:
                                continue  # already found by SQL
                            cross_dupes.append({
                                "field": "company/account_name",
                                "value": f"{l['val']} ↔ {a['val']}",
                                "source_table": "leads", "source_id": l["id"],
                                "target_table": "accounts", "target_id": a["id"],
                                "match_type": "normalized",
                                "stripped": n["stripped"],
                            })
                            norm_count += 1
                            if norm_count >= page_limit:
                                break
                        if norm_count >= page_limit:
                            break
                except Exception as e:
                    logger.warning(f"Cross-module normalized match error: {e}")

        cur.close()
        conn.close()
        return jsonify({"cross_duplicates": cross_dupes, "total": len(cross_dupes),
                        "limit": page_limit, "offset": offset})
    except Exception as e:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrich/convert", methods=["POST"])
def api_enrich_convert():
    """Convert a record from one module to another (e.g. lead -> contact)."""
    data = request.get_json()
    source_table = data.get("source_table")
    source_id = data.get("source_id")
    target_table = data.get("target_table")
    delete_source = data.get("delete_source", False)

    if not source_table or not target_table or not source_id:
        return jsonify({"error": "source_table, source_id, target_table required"}), 400
    if not table_valid(source_table) or not table_valid(target_table):
        return jsonify({"error": "Invalid table name"}), 400

    # Allowed conversions
    allowed = {
        ("leads", "contacts"), ("leads", "accounts"),
        ("contacts", "leads"), ("quotes", "sales_orders"),
        ("quotes", "invoices"), ("sales_orders", "invoices"),
    }
    if (source_table, target_table) not in allowed:
        return jsonify({"error": f"Conversion from {source_table} to {target_table} not supported"}), 400

    src_pk = get_pk(source_table)
    tgt_pk = get_pk(target_table)
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(f"SELECT * FROM {source_table} WHERE {src_pk}=%s", (source_id,))
        source = cur.fetchone()
        if not source:
            cur.close(); conn.close()
            return jsonify({"error": "Source record not found"}), 404

        source = dict(source)
        tgt_cols = [c["column_name"] for c in get_columns(target_table)]

        # Map common fields
        new_rec = {}
        skip = {"id", src_pk, "full_name", "created_at", "deleted_at",
                "zoho_id", "sync_version", "last_sync_at",
                "zoho_created_time", "zoho_modified_time", "zoho_created_by", "zoho_modified_by"}
        for k, v in source.items():
            if k in skip:
                continue
            if k in tgt_cols and v is not None:
                new_rec[k] = v

        # Special field conversions (lead -> contact: company -> account lookup)
        if source_table == "leads" and target_table == "contacts":
            company = source.get("company")
            if company and "account_id" in tgt_cols:
                cur.execute("SELECT id FROM accounts WHERE LOWER(account_name)=LOWER(%s) LIMIT 1", (company,))
                acct = cur.fetchone()
                if acct:
                    new_rec["account_id"] = str(acct["id"])

        # Metadata
        if "sync_status" in tgt_cols:
            new_rec["sync_status"] = "pending"
        if "created_at" in tgt_cols:
            new_rec["created_at"] = datetime.now()
        if "updated_at" in tgt_cols:
            new_rec["updated_at"] = datetime.now()

        if not new_rec:
            cur.close(); conn.close()
            return jsonify({"error": "No fields could be mapped"}), 400

        cols_str = ", ".join(new_rec.keys())
        phs = ", ".join(["%s"] * len(new_rec))
        cur.execute(f"INSERT INTO {target_table} ({cols_str}) VALUES ({phs}) RETURNING {tgt_pk}",
                    list(new_rec.values()))
        new_id = cur.fetchone()[tgt_pk]

        # Optionally soft-delete source
        if delete_source:
            if has_column(source_table, "deleted_at"):
                cur.execute(f"UPDATE {source_table} SET deleted_at=%s WHERE {src_pk}=%s",
                            (datetime.now(), source_id))
            else:
                cur.execute(f"DELETE FROM {source_table} WHERE {src_pk}=%s", (source_id,))

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            "success": True, "new_id": str(new_id),
            "source_table": source_table, "target_table": target_table,
            "source_deleted": delete_source,
        })
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrich/merge", methods=["POST"])
def api_enrich_merge():
    """Merge duplicate records."""
    data = request.get_json()
    table_name = data.get("table")
    keep_id = data.get("keep_id")
    merge_ids = data.get("merge_ids", [])

    if not table_valid(table_name) or not keep_id or not merge_ids:
        return jsonify({"error": "Invalid parameters"}), 400

    pk = get_pk(table_name)
    conn = get_db()
    cur = conn.cursor()

    try:
        # Get the keeper record
        cur.execute(f"SELECT * FROM {table_name} WHERE {pk}=%s", (keep_id,))
        keeper = dict(cur.fetchone())

        # For each merge target, fill in nulls from the source
        for mid in merge_ids:
            if mid == keep_id:
                continue
            cur.execute(f"SELECT * FROM {table_name} WHERE {pk}=%s", (mid,))
            source = cur.fetchone()
            if not source:
                continue

            updates = {}
            for k, v in dict(source).items():
                if k in (pk, "id", "zoho_id", "created_at", "full_name"):
                    continue
                if v is not None and (keeper.get(k) is None or keeper.get(k) == ""):
                    updates[k] = v

            if updates:
                sets = ", ".join(f"{k}=%s" for k in updates.keys())
                cur.execute(f"UPDATE {table_name} SET {sets} WHERE {pk}=%s",
                            list(updates.values()) + [keep_id])

            # Soft delete the merged record
            if has_column(table_name, "deleted_at"):
                cur.execute(f"UPDATE {table_name} SET deleted_at=%s WHERE {pk}=%s",
                            (datetime.now(), mid))
            else:
                cur.execute(f"DELETE FROM {table_name} WHERE {pk}=%s", (mid,))

        # Mark keeper as modified
        if has_column(table_name, "sync_status"):
            cur.execute(f"UPDATE {table_name} SET sync_status='modified', updated_at=%s WHERE {pk}=%s",
                        (datetime.now(), keep_id))

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"success": True, "kept": keep_id, "merged": len(merge_ids)})
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ROUTES - API: Enrichment Pipeline (Field-configurable dedup, enrichment
#   tables, upload with dedup check, on-demand sync with dedup protection)
# ---------------------------------------------------------------------------

def _ensure_enrichment_registry():
    """Create enrichment_tables registry if missing."""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS enrichment_tables (
                id SERIAL PRIMARY KEY,
                table_name VARCHAR(255) UNIQUE NOT NULL,
                target_crm_table VARCHAR(255),
                description TEXT,
                field_mapping JSONB DEFAULT '{}',
                dedup_fields JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cur.close()
        conn.close()


@app.route("/api/enrich/custom-dedup", methods=["POST"])
def api_custom_dedup():
    """Field-configurable deduplication. User chooses which fields to match on.

    Body: {
        "table": "leads",
        "fields": ["email", "company"],   // fields to deduplicate on
        "mode": "exact|normalized|fuzzy",  // matching mode (default: exact)
        "cross_table": "contacts",         // optional: check against another table
        "cross_fields": ["email", "account_name"],  // fields in the cross table
        "limit": 100
    }
    """
    data = request.get_json() or {}
    table = data.get("table", "")
    fields = data.get("fields", [])
    mode = data.get("mode", "exact")
    cross_table = data.get("cross_table", "")
    cross_fields = data.get("cross_fields", [])
    limit = data.get("limit", 100)

    if not table or not fields:
        return jsonify({"error": "table and fields required"}), 400
    if not table_valid(table):
        return jsonify({"error": f"Invalid table: {table}"}), 400

    cols = [c["column_name"] for c in get_columns(table)]
    for f in fields:
        if f not in cols:
            return jsonify({"error": f"Field '{f}' not found in {table}. Available: {cols}"}), 400

    pk = get_pk(table)
    conn = get_db()
    cur = conn.cursor()
    clusters = []

    try:
        if mode == "exact":
            # Group by LOWER(TRIM()) of selected fields
            field_exprs = [f"LOWER(TRIM(COALESCE({f}::text,'')))" for f in fields]
            concat_expr = " || '|||' || ".join(field_exprs)
            cur.execute(f"""
                SELECT {concat_expr} as match_key,
                       array_agg({pk}::text ORDER BY {pk}) as ids,
                       COUNT(*) as cnt,
                       {', '.join(f"array_agg(DISTINCT {f}::text) as vals_{f}" for f in fields)}
                FROM {table}
                WHERE {' AND '.join(f"({f} IS NOT NULL AND TRIM({f}::text) != '')" for f in fields)}
                GROUP BY {concat_expr}
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC
                LIMIT %s
            """, (limit,))
            for r in cur.fetchall():
                field_vals = {f: r[f"vals_{f}"] for f in fields}
                clusters.append({
                    "type": "exact",
                    "match_key": r["match_key"],
                    "fields": fields,
                    "field_values": field_vals,
                    "count": r["cnt"],
                    "ids": r["ids"][:20],
                })

        elif mode == "normalized":
            # Use normalize_company_name on the first field + exact on rest
            primary_field = fields[0]
            other_fields = fields[1:]

            # Fetch distinct values
            select_cols = f"{pk}, {', '.join(fields)}"
            cur.execute(f"""
                SELECT {select_cols} FROM {table}
                WHERE {' AND '.join(f"({f} IS NOT NULL AND TRIM({f}::text) != '')" for f in fields)}
            """)
            rows = cur.fetchall()

            # Build groups by normalized primary field + exact others
            groups = {}
            for r in rows:
                pval = r[primary_field]
                if primary_field in ("account_name", "company"):
                    n = normalize_company_name(str(pval))
                    key_primary = n["stripped"] or n["canonical"] or n["normalized"]
                else:
                    key_primary = str(pval).strip().lower()

                key_others = "|||".join(str(r.get(f, "")).strip().lower() for f in other_fields)
                group_key = f"{key_primary}|||{key_others}"
                groups.setdefault(group_key, []).append(r)

            for gkey, entries in groups.items():
                if len(entries) < 2:
                    continue
                originals = set(str(e[primary_field]).lower().strip() for e in entries)
                if len(originals) < 2 and len(entries) < 2:
                    continue
                ids = [str(e[pk]) for e in entries[:20]]
                field_vals = {}
                for f in fields:
                    field_vals[f] = list(set(str(e[f]) for e in entries if e.get(f)))[:10]
                clusters.append({
                    "type": "normalized",
                    "match_key": gkey,
                    "fields": fields,
                    "field_values": field_vals,
                    "count": len(entries),
                    "ids": ids,
                })
            clusters.sort(key=lambda c: c["count"], reverse=True)
            clusters = clusters[:limit]

        elif mode == "fuzzy":
            # Use pg_trgm similarity on primary field (requires GIN index)
            primary_field = fields[0]
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                conn.commit()
            except Exception:
                conn.rollback()
            # Use LATERAL self-join with similarity() > 0.4
            cur.execute(f"""
                WITH distinct_vals AS (
                    SELECT DISTINCT ON (LOWER(TRIM({primary_field}::text)))
                           {pk}, {', '.join(fields)},
                           LOWER(TRIM({primary_field}::text)) as norm_val
                    FROM {table}
                    WHERE {primary_field} IS NOT NULL AND TRIM({primary_field}::text) != ''
                    ORDER BY LOWER(TRIM({primary_field}::text)), {pk}
                    LIMIT 5000
                )
                SELECT a.{pk} as id_a, b.{pk} as id_b,
                       a.{primary_field} as val_a, b.{primary_field} as val_b,
                       similarity(a.norm_val, b.norm_val) as sim
                FROM distinct_vals a
                JOIN distinct_vals b ON a.{pk} < b.{pk}
                    AND a.norm_val != b.norm_val
                    AND similarity(a.norm_val, b.norm_val) > 0.4
                ORDER BY sim DESC
                LIMIT %s
            """, (limit,))
            for r in cur.fetchall():
                clusters.append({
                    "type": "fuzzy",
                    "fields": [primary_field],
                    "field_values": {primary_field: [r["val_a"], r["val_b"]]},
                    "similarity": round(r["sim"], 3),
                    "count": 2,
                    "ids": [str(r["id_a"]), str(r["id_b"])],
                })

        # Cross-table dedup check
        cross_matches = []
        if cross_table and cross_fields:
            if not table_valid(cross_table):
                return jsonify({"error": f"Invalid cross_table: {cross_table}"}), 400
            cross_cols = [c["column_name"] for c in get_columns(cross_table)]
            for cf in cross_fields:
                if cf not in cross_cols:
                    return jsonify({"error": f"Field '{cf}' not in {cross_table}"}), 400

            cross_pk = get_pk(cross_table)
            # Match fields pairwise: fields[i] <-> cross_fields[i]
            n_pairs = min(len(fields), len(cross_fields))
            join_conds = []
            for i in range(n_pairs):
                if mode == "normalized" and fields[i] in ("account_name", "company") and cross_fields[i] in ("account_name", "company"):
                    # Normalized cross-match done in Python below
                    pass
                else:
                    join_conds.append(
                        f"LOWER(TRIM(a.{fields[i]}::text)) = LOWER(TRIM(b.{cross_fields[i]}::text))"
                    )

            if join_conds:
                where_a = " AND ".join(f"a.{fields[i]} IS NOT NULL AND a.{fields[i]}::text != ''" for i in range(n_pairs))
                where_b = " AND ".join(f"b.{cross_fields[i]} IS NOT NULL AND b.{cross_fields[i]}::text != ''" for i in range(n_pairs))
                cur.execute(f"""
                    SELECT a.{pk}::text as source_id, b.{cross_pk}::text as target_id,
                           {', '.join(f"a.{fields[i]}::text as src_{fields[i]}" for i in range(n_pairs))},
                           {', '.join(f"b.{cross_fields[i]}::text as tgt_{cross_fields[i]}" for i in range(n_pairs))}
                    FROM {table} a JOIN {cross_table} b ON {' AND '.join(join_conds)}
                    WHERE {where_a} AND {where_b}
                    LIMIT %s
                """, (limit,))
                for r in cur.fetchall():
                    match_detail = {}
                    for i in range(n_pairs):
                        match_detail[f"{fields[i]}/{cross_fields[i]}"] = {
                            "source": r[f"src_{fields[i]}"],
                            "target": r[f"tgt_{cross_fields[i]}"],
                        }
                    cross_matches.append({
                        "source_table": table, "source_id": r["source_id"],
                        "target_table": cross_table, "target_id": r["target_id"],
                        "matched_fields": match_detail,
                    })

        cur.close()
        conn.close()
        return jsonify({
            "duplicates": clusters,
            "total": len(clusters),
            "cross_matches": cross_matches,
            "cross_total": len(cross_matches),
            "table": table,
            "fields": fields,
            "mode": mode,
        })
    except Exception as e:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        logger.error(f"Custom dedup error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# --- Enrichment table management ---

@app.route("/api/enrichment/tables", methods=["GET"])
def api_list_enrichment_tables():
    """List all registered enrichment tables."""
    _ensure_enrichment_registry()
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT et.*,
                   (SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema='public' AND table_name=et.table_name) as table_exists
            FROM enrichment_tables et ORDER BY et.created_at DESC
        """)
        tables = []
        for r in cur.fetchall():
            row = {k: serialize(v) for k, v in dict(r).items()}
            # Get row count if table exists
            if r["table_exists"] > 0:
                try:
                    cur.execute(f"SELECT COUNT(*) as cnt FROM {r['table_name']}")
                    row["row_count"] = cur.fetchone()["cnt"]
                except Exception:
                    row["row_count"] = 0
            else:
                row["row_count"] = 0
            tables.append(row)
        cur.close()
        conn.close()
        return jsonify({"enrichment_tables": tables, "total": len(tables)})
    except Exception as e:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrichment/tables", methods=["POST"])
def api_register_enrichment_table():
    """Register a table as an enrichment/supporting table (not synced to CRM).

    Body: {
        "table_name": "my_research_data",
        "target_crm_table": "leads",        // which CRM table this enriches
        "description": "Purchased lead list for Q1 campaign",
        "dedup_fields": ["email", "company"],  // fields to check for duplicates
        "field_mapping": {"company_name": "company", "contact_email": "email"},
        "columns": [...]                     // optional: create new table with these columns
    }
    """
    _ensure_enrichment_registry()
    data = request.get_json() or {}
    table_name = _sanitize_col(data.get("table_name", ""))
    target_crm = data.get("target_crm_table", "")
    description = data.get("description", "")
    dedup_fields = data.get("dedup_fields", [])
    field_mapping = data.get("field_mapping", {})
    columns = data.get("columns", [])

    if not table_name:
        return jsonify({"error": "table_name required"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        # Optionally create the table
        if columns:
            if table_name in get_tables():
                return jsonify({"error": f"Table '{table_name}' already exists"}), 409
            col_defs = ["id SERIAL PRIMARY KEY"]
            for c in columns:
                cname = _sanitize_col(c.get("name", ""))
                ctype = c.get("type", "TEXT").upper()
                if ctype not in {"TEXT", "VARCHAR(255)", "INTEGER", "BIGINT", "NUMERIC",
                                 "BOOLEAN", "TIMESTAMP", "DATE", "JSONB", "UUID"}:
                    ctype = "TEXT"
                col_defs.append(f"{cname} {ctype}")
            col_defs.extend([
                "sync_status VARCHAR(50) DEFAULT 'new'",
                "dedup_status VARCHAR(50) DEFAULT 'unchecked'",
                "dedup_match_id TEXT",
                "dedup_match_table TEXT",
                "notes TEXT",
                "created_at TIMESTAMP DEFAULT NOW()",
                "updated_at TIMESTAMP DEFAULT NOW()"
            ])
            cur.execute(f"CREATE TABLE {table_name} ({', '.join(col_defs)})")
            conn.commit()
            logger.info(f"Created enrichment table: {table_name}")

        # Register in enrichment_tables
        cur.execute("""
            INSERT INTO enrichment_tables (table_name, target_crm_table, description, field_mapping, dedup_fields)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (table_name) DO UPDATE SET
                target_crm_table = EXCLUDED.target_crm_table,
                description = EXCLUDED.description,
                field_mapping = EXCLUDED.field_mapping,
                dedup_fields = EXCLUDED.dedup_fields,
                updated_at = NOW()
            RETURNING id
        """, (table_name, target_crm, description,
              json.dumps(field_mapping), json.dumps(dedup_fields)))
        reg_id = cur.fetchone()["id"]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            "status": "registered",
            "id": reg_id,
            "table_name": table_name,
            "target_crm_table": target_crm,
            "dedup_fields": dedup_fields,
        })
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrichment/tables/<table_name>", methods=["DELETE"])
def api_unregister_enrichment_table(table_name):
    """Unregister (but don't drop) an enrichment table."""
    _ensure_enrichment_registry()
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM enrichment_tables WHERE table_name=%s RETURNING id", (table_name,))
        deleted = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        if deleted:
            return jsonify({"status": "unregistered", "table_name": table_name})
        return jsonify({"error": "Not found"}), 404
    except Exception as e:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500


# --- Dedup check: compare enrichment data against CRM tables ---

@app.route("/api/enrichment/dedup-check", methods=["POST"])
def api_enrichment_dedup_check():
    """Check enrichment table records against CRM table for duplicates.
    Marks each enrichment record as 'unique', 'duplicate', or 'possible_match'.

    Body: {
        "enrichment_table": "my_leads_list",
        "target_crm_table": "leads",         // optional, uses registered default
        "field_pairs": [                      // optional, uses registered default
            {"source": "contact_email", "target": "email"},
            {"source": "company_name", "target": "company"}
        ],
        "mode": "exact|normalized"            // default: exact
    }
    """
    data = request.get_json() or {}
    enrich_table = data.get("enrichment_table", "")
    target_crm = data.get("target_crm_table", "")
    field_pairs = data.get("field_pairs", [])
    mode = data.get("mode", "exact")

    if not enrich_table or not table_valid(enrich_table):
        return jsonify({"error": "Valid enrichment_table required"}), 400

    # Load defaults from registry if not provided
    _ensure_enrichment_registry()
    conn = get_db()
    cur = conn.cursor()

    try:
        if not target_crm or not field_pairs:
            cur.execute("SELECT * FROM enrichment_tables WHERE table_name=%s", (enrich_table,))
            reg = cur.fetchone()
            if reg:
                reg = dict(reg)
                if not target_crm:
                    target_crm = reg.get("target_crm_table", "")
                if not field_pairs:
                    mapping = reg.get("field_mapping", {})
                    if isinstance(mapping, str):
                        mapping = json.loads(mapping)
                    field_pairs = [{"source": k, "target": v} for k, v in mapping.items()]

        if not target_crm or not field_pairs:
            cur.close()
            conn.close()
            return jsonify({"error": "target_crm_table and field_pairs required (not registered)"}), 400

        if not table_valid(target_crm):
            cur.close()
            conn.close()
            return jsonify({"error": f"Invalid target CRM table: {target_crm}"}), 400

        enrich_cols = [c["column_name"] for c in get_columns(enrich_table)]
        crm_cols = [c["column_name"] for c in get_columns(target_crm)]
        enrich_pk = get_pk(enrich_table)
        crm_pk = get_pk(target_crm)

        # Validate field pairs
        valid_pairs = []
        for fp in field_pairs:
            src = fp.get("source", "")
            tgt = fp.get("target", "")
            if src in enrich_cols and tgt in crm_cols:
                valid_pairs.append((src, tgt))
        if not valid_pairs:
            cur.close()
            conn.close()
            return jsonify({"error": "No valid field pairs found"}), 400

        # Ensure dedup columns exist on enrichment table
        for extra_col in ("dedup_status", "dedup_match_id", "dedup_match_table"):
            if extra_col not in enrich_cols:
                try:
                    cur.execute(f"ALTER TABLE {enrich_table} ADD COLUMN {extra_col} TEXT")
                    conn.commit()
                except Exception:
                    conn.rollback()

        # Fetch all enrichment records
        cur.execute(f"SELECT * FROM {enrich_table}")
        enrich_records = [dict(r) for r in cur.fetchall()]

        stats = {"total": len(enrich_records), "duplicates": 0, "unique": 0, "checked": 0}

        for rec in enrich_records:
            # Build match query against CRM table
            conditions = []
            params = []
            has_values = True
            for src, tgt in valid_pairs:
                val = rec.get(src)
                if not val or str(val).strip() == "":
                    has_values = False
                    break
                if mode == "normalized" and tgt in ("company", "account_name"):
                    # Normalized match — compare in Python
                    pass
                else:
                    conditions.append(f"LOWER(TRIM({tgt}::text)) = LOWER(TRIM(%s))")
                    params.append(str(val))

            if not has_values:
                cur.execute(f"UPDATE {enrich_table} SET dedup_status='skipped' WHERE {enrich_pk}=%s",
                            (rec[enrich_pk],))
                continue

            match_id = None
            if conditions:
                cur.execute(f"""
                    SELECT {crm_pk}::text as match_id FROM {target_crm}
                    WHERE {' AND '.join(conditions)} LIMIT 1
                """, params)
                match = cur.fetchone()
                if match:
                    match_id = match["match_id"]

            # Normalized company name match fallback
            if not match_id and mode == "normalized":
                for src, tgt in valid_pairs:
                    if tgt not in ("company", "account_name"):
                        continue
                    val = rec.get(src)
                    if not val:
                        continue
                    n_src = normalize_company_name(str(val))
                    if not n_src["stripped"]:
                        continue
                    cur.execute(f"SELECT {crm_pk}::text as mid, {tgt} FROM {target_crm} WHERE {tgt} IS NOT NULL AND {tgt} != ''")
                    for crm_rec in cur.fetchall():
                        n_crm = normalize_company_name(str(crm_rec[tgt]))
                        if n_crm["stripped"] == n_src["stripped"]:
                            match_id = crm_rec["mid"]
                            break
                    if match_id:
                        break

            if match_id:
                cur.execute(f"""UPDATE {enrich_table}
                    SET dedup_status='duplicate', dedup_match_id=%s, dedup_match_table=%s
                    WHERE {enrich_pk}=%s""",
                    (match_id, target_crm, rec[enrich_pk]))
                stats["duplicates"] += 1
            else:
                cur.execute(f"UPDATE {enrich_table} SET dedup_status='unique' WHERE {enrich_pk}=%s",
                            (rec[enrich_pk],))
                stats["unique"] += 1
            stats["checked"] += 1

        conn.commit()
        cur.close()
        conn.close()
        return jsonify({
            "status": "completed",
            "stats": stats,
            "enrichment_table": enrich_table,
            "target_crm_table": target_crm,
            "field_pairs": [{"source": s, "target": t} for s, t in valid_pairs],
            "mode": mode,
        })
    except Exception as e:
        try:
            conn.rollback()
            cur.close()
            conn.close()
        except Exception:
            pass
        logger.error(f"Dedup check error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# --- On-demand sync: push unique enrichment records to CRM table, then to Zoho ---

@app.route("/api/enrichment/sync-to-crm", methods=["POST"])
def api_enrichment_sync_to_crm():
    """Push unique (non-duplicate) enrichment records to a CRM table in PostgreSQL,
    then optionally push them to Zoho CRM.

    Only records with dedup_status='unique' are pushed (run dedup-check first).

    Body: {
        "enrichment_table": "my_leads_list",
        "target_crm_table": "leads",           // optional, uses registered default
        "field_mapping": {"company_name": "company", "contact_email": "email"},
        "push_to_zoho": false,                  // default: false (just insert into PG)
        "sync_status": "pending",               // status for new records (pending = will sync on next push)
        "filter_status": "unique"               // which dedup_status to push (default: unique)
    }
    """
    data = request.get_json() or {}
    enrich_table = data.get("enrichment_table", "")
    target_crm = data.get("target_crm_table", "")
    field_mapping = data.get("field_mapping", {})
    push_to_zoho = data.get("push_to_zoho", False)
    sync_status = data.get("sync_status", "pending")
    filter_status = data.get("filter_status", "unique")

    if not enrich_table or not table_valid(enrich_table):
        return jsonify({"error": "Valid enrichment_table required"}), 400

    _ensure_enrichment_registry()
    conn = get_db()
    cur = conn.cursor()

    try:
        # Load defaults from registry
        if not target_crm or not field_mapping:
            cur.execute("SELECT * FROM enrichment_tables WHERE table_name=%s", (enrich_table,))
            reg = cur.fetchone()
            if reg:
                reg = dict(reg)
                if not target_crm:
                    target_crm = reg.get("target_crm_table", "")
                if not field_mapping:
                    fm = reg.get("field_mapping", {})
                    if isinstance(fm, str):
                        fm = json.loads(fm)
                    field_mapping = fm

        if not target_crm or not field_mapping:
            cur.close()
            conn.close()
            return jsonify({"error": "target_crm_table and field_mapping required"}), 400

        if not table_valid(target_crm):
            cur.close()
            conn.close()
            return jsonify({"error": f"Invalid CRM table: {target_crm}"}), 400

        crm_cols = [c["column_name"] for c in get_columns(target_crm)]
        enrich_pk = get_pk(enrich_table)

        # Get unique records from enrichment table
        cur.execute(f"SELECT * FROM {enrich_table} WHERE dedup_status=%s", (filter_status,))
        records = [dict(r) for r in cur.fetchall()]

        if not records:
            cur.close()
            conn.close()
            return jsonify({
                "status": "no_records",
                "message": f"No records with dedup_status='{filter_status}'. Run dedup-check first.",
            })

        inserted = 0
        errors = []
        new_ids = []

        for rec in records:
            # Map enrichment fields to CRM fields
            new_rec = {}
            for src_field, tgt_field in field_mapping.items():
                if tgt_field in crm_cols and rec.get(src_field) is not None:
                    new_rec[tgt_field] = rec[src_field]

            if not new_rec:
                continue

            # Set metadata
            if "sync_status" in crm_cols:
                new_rec["sync_status"] = sync_status
            if "created_at" in crm_cols:
                new_rec["created_at"] = datetime.now()
            if "updated_at" in crm_cols:
                new_rec["updated_at"] = datetime.now()

            try:
                cols_str = ", ".join(new_rec.keys())
                phs = ", ".join(["%s"] * len(new_rec))
                crm_pk = get_pk(target_crm)
                cur.execute(f"INSERT INTO {target_crm} ({cols_str}) VALUES ({phs}) RETURNING {crm_pk}",
                            list(new_rec.values()))
                new_id = str(cur.fetchone()[crm_pk])
                new_ids.append(new_id)
                inserted += 1

                # Update enrichment record status
                cur.execute(f"""UPDATE {enrich_table}
                    SET sync_status='inserted', dedup_match_id=%s, dedup_match_table=%s
                    WHERE {enrich_pk}=%s""",
                    (new_id, target_crm, rec[enrich_pk]))
            except Exception as e:
                errors.append({"record": rec.get(enrich_pk), "error": str(e)[:200]})
                conn.rollback()
                # Reconnect after rollback
                conn = get_db()
                cur = conn.cursor()

        conn.commit()

        # Optionally push to Zoho
        zoho_result = None
        if push_to_zoho and new_ids and target_crm in TABLE_MODULE_MAP:
            module_name = TABLE_MODULE_MAP[target_crm]
            try:
                push_res = do_push_sync(modules=[module_name], record_ids=new_ids, table_name=target_crm)
                zoho_result = push_res
            except Exception as e:
                zoho_result = {"error": str(e)}

        cur.close()
        conn.close()
        return jsonify({
            "status": "completed",
            "inserted": inserted,
            "errors": errors[:20],
            "new_ids": new_ids[:100],
            "target_crm_table": target_crm,
            "push_to_zoho": push_to_zoho,
            "zoho_result": zoho_result,
        })
    except Exception as e:
        try:
            conn.rollback()
            cur.close()
            conn.close()
        except Exception:
            pass
        logger.error(f"Enrichment sync error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/enrichment/summary/<table_name>")
def api_enrichment_summary(table_name):
    """Get dedup status summary for an enrichment table."""
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400
    conn = get_db()
    cur = conn.cursor()
    try:
        cols = [c["column_name"] for c in get_columns(table_name)]
        if "dedup_status" not in cols:
            cur.close()
            conn.close()
            return jsonify({"error": "Not an enrichment table (no dedup_status column)"}), 400

        cur.execute(f"""
            SELECT dedup_status, COUNT(*) as cnt
            FROM {table_name}
            GROUP BY dedup_status
            ORDER BY cnt DESC
        """)
        summary = {r["dedup_status"] or "null": r["cnt"] for r in cur.fetchall()}
        total = sum(summary.values())

        cur.close()
        conn.close()
        return jsonify({
            "table": table_name,
            "total": total,
            "summary": summary,
        })
    except Exception as e:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# ROUTES - API: Zoho metadata
# ---------------------------------------------------------------------------
@app.route("/api/zoho/modules")
def api_zoho_modules():
    try:
        modules = get_zoho().get_modules()
        return jsonify({"modules": [{"name": m.get("module_name"), "api_name": m.get("api_name"),
                                      "plural_label": m.get("plural_label")} for m in modules]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/zoho/fields/<module_name>")
def api_zoho_fields(module_name):
    try:
        fields = get_zoho().get_fields(module_name)
        return jsonify({"fields": [{"api_name": f.get("api_name"), "display_label": f.get("display_label"),
                                     "data_type": f.get("data_type"), "required": f.get("required", False)}
                                    for f in fields]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/zoho/test")
def api_zoho_test():
    try:
        ok = get_zoho().test_connection()
        return jsonify({"connected": ok})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)})

# ---------------------------------------------------------------------------
# ROUTES - API: Conflicts
# ---------------------------------------------------------------------------
@app.route("/api/conflicts")
def api_list_conflicts():
    """List sync conflicts (records modified in both Zoho and PostgreSQL)."""
    try:
        conn = get_db()
        cur = conn.cursor()
        status = request.args.get("status", None)  # unresolved, resolved, all
        sql = "SELECT * FROM conflicts"
        params = []
        if status == "unresolved":
            sql += " WHERE resolved_at IS NULL"
        elif status == "resolved":
            sql += " WHERE resolved_at IS NOT NULL"
        sql += " ORDER BY detected_at DESC LIMIT 100"
        cur.execute(sql, params)
        rows = [{k: serialize(v) for k, v in dict(r).items()} for r in cur.fetchall()]
        cur.close(); conn.close()
        return jsonify({"conflicts": rows, "total": len(rows)})
    except Exception as e:
        return jsonify({"conflicts": [], "error": str(e)})

@app.route("/api/conflicts/<conflict_id>/resolve", methods=["POST"])
def api_resolve_conflict(conflict_id):
    """Resolve a sync conflict with a strategy."""
    data = request.get_json() or {}
    resolution = data.get("resolution", "manual")  # zoho_wins, postgres_wins, manual, skip
    notes = data.get("notes", "")
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""UPDATE conflicts SET resolved_at=NOW(), resolution=%s,
                       resolved_by='dashboard', resolution_notes=%s WHERE id=%s RETURNING id""",
                    (resolution, notes, conflict_id))
        result = cur.fetchone()
        if result and resolution == "postgres_wins":
            # Re-enable push for this record
            cur.execute("SELECT table_name, record_id FROM conflicts WHERE id=%s", (conflict_id,))
            conflict = cur.fetchone()
            if conflict:
                tbl = conflict["table_name"]
                rid = conflict["record_id"]
                if has_column(tbl, "sync_status"):
                    cur.execute(f"UPDATE {tbl} SET sync_status='modified' WHERE id=%s", (rid,))
        conn.commit(); cur.close(); conn.close()
        return jsonify({"success": bool(result)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# ROUTES - API: Bulk Enrichment
# ---------------------------------------------------------------------------
@app.route("/api/enrich/bulk-update", methods=["POST"])
def api_bulk_enrich():
    """Bulk update records for enrichment pipelines.
    Accepts: {"table": "leads", "records": [{"id": "...", "field1": "val1", ...}, ...]}
    Auto-sets sync_status='modified' and tracks changes."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    table = data.get("table")
    records = data.get("records", [])
    if not table or not table_valid(table):
        return jsonify({"error": "Invalid table"}), 400
    if not records:
        return jsonify({"error": "No records"}), 400

    cols = [c["column_name"] for c in get_columns(table)]
    pk = get_pk(table)
    skip = {pk, "id", "full_name", "created_at", "zoho_id", "zoho_created_time", "zoho_modified_time"}

    conn = get_db()
    cur = conn.cursor()
    updated = errors = 0
    change_log = []

    for rec in records:
        rec_id = rec.get("id") or rec.get(pk)
        if not rec_id:
            errors += 1
            continue
        try:
            # Fetch old values
            cur.execute(f"SELECT * FROM {table} WHERE {pk}=%s", (rec_id,))
            old = cur.fetchone()
            if not old:
                errors += 1
                continue
            old_dict = dict(old)

            updates = {}
            for k, v in rec.items():
                if k in cols and k not in skip:
                    updates[k] = v
            if not updates:
                continue
            if "sync_status" in cols:
                updates["sync_status"] = "modified"
            if "updated_at" in cols:
                updates["updated_at"] = datetime.now()

            sets = ", ".join(f"{k}=%s" for k in updates.keys())
            cur.execute(f"UPDATE {table} SET {sets} WHERE {pk}=%s",
                        list(updates.values()) + [rec_id])

            # Track changes
            changed = {}
            for k, v in rec.items():
                if k in old_dict and str(old_dict.get(k)) != str(v) and k not in skip:
                    changed[k] = {"old": serialize(old_dict[k]), "new": serialize(v)}
            if changed:
                try:
                    cur.execute("SAVEPOINT enrich_log")
                    cur.execute("""INSERT INTO changes_detected
                        (id, table_name, record_id, zoho_id, change_type, change_source, old_values, new_values, detected_at, processing_status)
                        VALUES (gen_random_uuid(), %s, %s::uuid, %s, 'updated', 'system', %s, %s, NOW(), 'synced')""",
                        (table, rec_id, old_dict.get("zoho_id"),
                         json.dumps({k: v["old"] for k, v in changed.items()}, default=str),
                         json.dumps({k: v["new"] for k, v in changed.items()}, default=str)))
                    cur.execute("RELEASE SAVEPOINT enrich_log")
                except Exception:
                    try: cur.execute("ROLLBACK TO SAVEPOINT enrich_log")
                    except: pass
            updated += 1
        except Exception as e:
            errors += 1
            logger.warning(f"Bulk enrich error for {table}/{rec_id}: {e}")
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"updated": updated, "errors": errors, "total": len(records)})

# ---------------------------------------------------------------------------
# ROUTES - API: Export
# ---------------------------------------------------------------------------
@app.route("/api/export/<table_name>")
def api_export(table_name):
    if not table_valid(table_name):
        return jsonify({"error": "Invalid table"}), 400
    fmt = request.args.get("format", "csv")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table_name}")
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()

        if fmt == "json":
            return Response(json.dumps(rows, default=str, indent=2),
                            mimetype="application/json",
                            headers={"Content-Disposition": f"attachment;filename={table_name}.json"})

        df = pd.DataFrame(rows)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment;filename={table_name}.csv"})
    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.route("/healthz")
@app.route("/health")
def healthz():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

# ---------------------------------------------------------------------------
# DB Migrations (run once at startup)
# ---------------------------------------------------------------------------
def run_migrations():
    """Drop unique constraints on email/phone that block bulk import.
    Zoho has many records with NULL or duplicate emails/phones."""
    try:
        conn = get_db()
        cur = conn.cursor()
        # Find all UNIQUE constraints on email/phone columns
        cur.execute("""
            SELECT tc.table_name, tc.constraint_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'UNIQUE'
              AND tc.table_schema = 'public'
              AND kcu.column_name IN ('email', 'phone', 'mobile', 'website')
        """)
        constraints = cur.fetchall()
        for c in constraints:
            tbl = c["table_name"]
            cname = c["constraint_name"]
            col = c["column_name"]
            logger.info(f"Migration: dropping constraint {cname} on {tbl}.{col}")
            cur.execute(f"ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS {cname}")
        conn.commit()
        if constraints:
            logger.info(f"Migration: dropped {len(constraints)} unique constraints on email/phone/mobile/website")
        # Ensure pg_trgm extension exists
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Migration error: {e}")

run_migrations()

# ---------------------------------------------------------------------------
# ROUTES - API: Gemini AI Chat
# ---------------------------------------------------------------------------
# In-memory chat sessions  {session_id: [{"role": ..., "parts": ...}, ...]}
_chat_sessions: Dict[str, list] = {}

def _build_schema_context() -> str:
    """Build a concise schema description for the Gemini system prompt."""
    try:
        tables = get_tables()
        lines = [f"Database: {DB_CONFIG['database']} (PostgreSQL)"]
        lines.append(f"Tables ({len(tables)}): {', '.join(tables)}")
        lines.append("")
        # CRM module mapping
        lines.append("CRM module -> table mapping:")
        for mod, tbl in MODULE_TABLE_MAP.items():
            lines.append(f"  {mod} -> {tbl}")
        lines.append("")
        # Show columns for key tables (first 8)
        for tbl in tables[:12]:
            try:
                cols = get_columns(tbl)
                col_strs = [f"{c['column_name']} ({c['data_type']})" for c in cols[:20]]
                lines.append(f"{tbl}: {', '.join(col_strs)}")
            except Exception:
                pass
        return "\n".join(lines)
    except Exception as e:
        return f"Could not load schema: {e}"

_GEMINI_SYSTEM = """You are an AI assistant for the Zoho CRM PostgreSQL dashboard.
You help users query data, manage tables, understand CRM records, and perform analytics.

CAPABILITIES:
- Execute read-only SQL queries against the PostgreSQL database
- List tables and describe their schemas
- Summarize data and provide insights
- Help write SQL queries for data analysis
- Create new tables and manage schema

RULES:
- For data queries, use the execute_sql tool. Only SELECT/WITH/EXPLAIN are allowed.
- Always limit queries to 200 rows unless user asks for more.
- Format numbers and dates nicely in your responses.
- When users ask about "leads", "contacts", "deals" etc, query the corresponding table.
- The custom_fields column (JSONB) contains additional Zoho fields not in standard columns.
- Use proper PostgreSQL syntax (ILIKE for case-insensitive, ::text for casts, etc).

DATABASE SCHEMA:
{schema}
"""

# Gemini function declarations for tool calling
_GEMINI_TOOLS = [
    {
        "name": "execute_sql",
        "description": "Execute a read-only SQL query (SELECT/WITH/EXPLAIN only) against the PostgreSQL database and return results.",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "The SQL query to execute"},
                "limit": {"type": "integer", "description": "Max rows to return (default 200)"}
            },
            "required": ["sql"]
        }
    },
    {
        "name": "list_tables",
        "description": "List all tables in the database with row counts.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "describe_table",
        "description": "Get the schema (columns, types) for a specific table.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string", "description": "Name of the table to describe"}
            },
            "required": ["table_name"]
        }
    },
    {
        "name": "create_table",
        "description": "Create a new table in the database.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string", "description": "Name for the new table (lowercase, underscores)"},
                "columns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string", "description": "PostgreSQL type: TEXT, INTEGER, BIGINT, NUMERIC, BOOLEAN, TIMESTAMP, DATE, JSONB, UUID, VARCHAR(255)"},
                            "nullable": {"type": "boolean"}
                        },
                        "required": ["name", "type"]
                    },
                    "description": "Column definitions"
                }
            },
            "required": ["table_name", "columns"]
        }
    }
]

def _exec_gemini_tool(name: str, args: dict) -> str:
    """Execute a Gemini function call and return result as string."""
    try:
        if name == "execute_sql":
            sql = (args.get("sql") or "").strip()
            limit = args.get("limit", 200)
            sql_upper = sql.upper().lstrip()
            if not any(sql_upper.startswith(kw) for kw in ("SELECT", "WITH", "EXPLAIN")):
                return json.dumps({"error": "Only SELECT/WITH/EXPLAIN queries allowed"})
            conn = get_db()
            cur = conn.cursor()
            try:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(sql)
                if cur.description:
                    columns = [desc[0] for desc in cur.description]
                    rows = [{k: serialize(v) for k, v in dict(r).items()} for r in cur.fetchmany(limit)]
                    return json.dumps({"columns": columns, "data": rows, "count": len(rows)}, default=str)
                return json.dumps({"message": "Query executed, no results"})
            except Exception as e:
                conn.rollback()
                return json.dumps({"error": str(e)})
            finally:
                cur.close()
                conn.close()

        elif name == "list_tables":
            tables = get_tables()
            result = []
            conn = get_db()
            cur = conn.cursor()
            for t in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) as cnt FROM {t}")
                    cnt = cur.fetchone()["cnt"]
                except Exception:
                    cnt = "?"
                result.append({"table": t, "rows": cnt, "crm_module": TABLE_MODULE_MAP.get(t)})
            cur.close()
            conn.close()
            return json.dumps(result, default=str)

        elif name == "describe_table":
            tbl = args.get("table_name", "")
            if tbl not in get_tables():
                return json.dumps({"error": f"Table '{tbl}' not found"})
            cols = get_columns(tbl)
            return json.dumps({"table": tbl, "columns": cols}, default=str)

        elif name == "create_table":
            import re
            tbl = args.get("table_name", "").strip().lower()
            columns = args.get("columns", [])
            if not tbl or not columns:
                return json.dumps({"error": "table_name and columns required"})
            if not re.match(r'^[a-z][a-z0-9_]*$', tbl):
                return json.dumps({"error": "Invalid table name"})
            if tbl in get_tables():
                return json.dumps({"error": f"Table '{tbl}' already exists"})
            conn = get_db()
            cur = conn.cursor()
            try:
                col_defs = ["id SERIAL PRIMARY KEY"]
                allowed_types = {"TEXT", "VARCHAR(255)", "INTEGER", "BIGINT", "NUMERIC",
                                 "BOOLEAN", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE",
                                 "DATE", "JSONB", "UUID"}
                for c in columns:
                    cname = _sanitize_col(c.get("name", ""))
                    ctype = c.get("type", "TEXT").upper()
                    if ctype not in allowed_types:
                        ctype = "TEXT"
                    nullable = "" if c.get("nullable", True) else " NOT NULL"
                    col_defs.append(f"{cname} {ctype}{nullable}")
                create_sql = f"CREATE TABLE {tbl} ({', '.join(col_defs)})"
                cur.execute(create_sql)
                conn.commit()
                return json.dumps({"success": True, "table": tbl, "columns": len(columns)})
            except Exception as e:
                conn.rollback()
                return json.dumps({"error": str(e)})
            finally:
                cur.close()
                conn.close()

        return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Non-streaming Gemini chat endpoint with function calling."""
    if not HAS_GENAI:
        return jsonify({"error": "google-genai not installed"}), 500

    data = request.get_json() or {}
    message = (data.get("message") or "").strip()
    session_id = data.get("session_id", "default")
    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        client = genai.Client(vertexai=True, project="leadenrich-a2b9d", location="europe-west1")

        # Build system prompt with schema
        schema_ctx = _build_schema_context()
        system_prompt = _GEMINI_SYSTEM.format(schema=schema_ctx)

        # Get or create session history
        if session_id not in _chat_sessions:
            _chat_sessions[session_id] = []
        history = _chat_sessions[session_id]

        # Build tool declarations
        tool_declarations = genai_types.Tool(function_declarations=[
            genai_types.FunctionDeclaration(**t) for t in _GEMINI_TOOLS
        ])

        # Add user message to history
        history.append({"role": "user", "parts": [{"text": message}]})

        # Create contents for API call — use plain dicts (SDK accepts them)
        contents = [{"role": m["role"], "parts": m["parts"]} for m in history]

        # Call Gemini with function calling loop (max 5 rounds)
        full_response = ""
        tool_results_log = []

        for _round in range(5):
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    tools=[tool_declarations],
                    temperature=0.1,
                )
            )

            # Check for function calls
            candidate = response.candidates[0] if response.candidates else None
            if not candidate:
                break

            has_function_call = False
            for part in candidate.content.parts:
                if part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}
                    logger.info(f"Gemini tool call: {tool_name}({json.dumps(tool_args, default=str)[:200]})")

                    # Execute tool
                    result_str = _exec_gemini_tool(tool_name, tool_args)
                    tool_results_log.append({"tool": tool_name, "args": tool_args, "result_preview": result_str[:500]})

                    # Add assistant's function_call response, then tool result
                    contents.append({"role": "model", "parts": [{"function_call": {"name": tool_name, "args": tool_args}}]})
                    contents.append({"role": "user", "parts": [{"function_response": {"name": tool_name, "response": {"result": result_str}}}]})
                    break  # Re-enter loop for next round

            if not has_function_call:
                # Extract text response
                for part in candidate.content.parts:
                    if part.text:
                        full_response += part.text
                break

        # Save to session history
        history.append({"role": "model", "parts": [{"text": full_response or "(no response)"}]})

        # Trim history to last 20 turns
        if len(history) > 40:
            _chat_sessions[session_id] = history[-40:]

        return jsonify({
            "response": full_response or "(no response)",
            "session_id": session_id,
            "tools_used": [t["tool"] for t in tool_results_log]
        })

    except Exception as e:
        logger.error(f"Gemini chat error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/reset", methods=["POST"])
def api_chat_reset():
    """Reset a chat session."""
    data = request.get_json() or {}
    session_id = data.get("session_id", "default")
    _chat_sessions.pop(session_id, None)
    return jsonify({"ok": True, "session_id": session_id})


@app.route("/api/chat/status", methods=["GET"])
def api_chat_status():
    """Check if Gemini AI is available."""
    return jsonify({
        "available": HAS_GENAI,
        "model": "gemini-2.5-pro",
        "sessions": len(_chat_sessions),
        "tools": [t["name"] for t in _GEMINI_TOOLS]
    })


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
# Ensure sync tracking tables exist, then start auto-sync
try:
    ensure_sync_tables()
except Exception as _e:
    logger.warning(f"ensure_sync_tables at startup: {_e}")
try:
    ensure_related_tables()
except Exception as _e:
    logger.warning(f"ensure_related_tables at startup: {_e}")
start_auto_sync()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Unified Dashboard on port {port}")
    logger.info(f"Modules: {list(MODULE_TABLE_MAP.keys())}")
    app.run(host="0.0.0.0", port=port, debug=True)
