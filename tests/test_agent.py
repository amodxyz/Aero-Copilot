"""
Automated Multi-Tenant Unit and Integration Tests for Productivity Agent.
"""

import pytest
import datetime
from fastapi.testclient import TestClient

from database import init_db, query_one, create_tenant, list_all_tenants
from tools import (
    get_daily_sales_summary,
    get_inventory_alerts,
    reorder_inventory,
    search_products,
    list_daily_tasks,
    create_operational_task,
    generate_daily_briefing,
    create_sales_order
)
from agent import agent_instance
from main import app


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Initializes and reseeds multi-tenant database before running tests."""
    init_db(force_reseed=True)


def test_multi_tenant_database_initialization():
    """Verify multiple tenants and their isolated catalogs exist."""
    tenants = list_all_tenants()
    assert len(tenants) >= 3
    tenant_ids = [t["tenant_id"] for t in tenants]
    assert "acme-electronics" in tenant_ids
    assert "beancrafters-cafe" in tenant_ids
    assert "nova-apparel" in tenant_ids

    # Verify Acme has Electronics
    acme_prods = query_one("SELECT COUNT(*) as count FROM products WHERE tenant_id = 'acme-electronics'")
    assert acme_prods["count"] >= 4

    # Verify BeanCrafters has Coffee
    bean_prods = query_one("SELECT COUNT(*) as count FROM products WHERE tenant_id = 'beancrafters-cafe'")
    assert bean_prods["count"] >= 4


def test_tenant_data_isolation():
    """Ensure querying sales/inventory for Tenant A does not bleed into Tenant B."""
    today = datetime.date.today().isoformat()
    sales_acme = get_daily_sales_summary(today, tenant_id="acme-electronics")
    sales_beans = get_daily_sales_summary(today, tenant_id="beancrafters-cafe")

    assert sales_acme["tenant_id"] == "acme-electronics"
    assert sales_beans["tenant_id"] == "beancrafters-cafe"
    # Acme sells keyboards, BeanCrafters sells beans
    assert any("Keyboard" in p["name"] for p in sales_acme["top_selling_products"])
    assert any("Yirgacheffe" in p["name"] or "Roast" in p["name"] for p in sales_beans["top_selling_products"])


def test_tenant_scoped_reorder():
    """Test reordering inventory updates only the target tenant's stock."""
    prod_before = query_one("SELECT stock_quantity FROM products WHERE tenant_id = 'acme-electronics' AND sku = 'SKU-101'")
    initial_stock = prod_before["stock_quantity"]

    res = reorder_inventory("SKU-101", 10, tenant_id="acme-electronics")
    assert res["success"] is True
    assert res["new_stock"] == initial_stock + 10

    # Ensure BeanCrafters does NOT have SKU-101
    invalid_res = reorder_inventory("SKU-101", 10, tenant_id="beancrafters-cafe")
    assert invalid_res["success"] is False


def test_tenant_creation():
    """Test registering a brand new tenant."""
    import time
    tid = f"skyline-logistics-{int(time.time() * 1000)}"
    new_tenant = create_tenant(tid, "Skyline Logistics", "Freight & Transport")
    assert new_tenant["success"] is True

    tenants = list_all_tenants()
    assert any(t["tenant_id"] == tid for t in tenants)


def test_agent_tenant_chat():
    """Test agent responses scoped to different tenants."""
    res_acme = agent_instance.process_message("Show sales summary", tenant_id="acme-electronics")
    assert "acme-electronics" in res_acme["reply"]

    res_beans = agent_instance.process_message("2", tenant_id="beancrafters-cafe")
    assert "beancrafters-cafe" in res_beans["reply"]

    # Test forecast prompt routing
    res_forecast = agent_instance.process_message("Forecast sales demand and stockout risk", tenant_id="acme-electronics")
    assert "forecast" in res_forecast["reply"].lower()
    assert res_forecast["tenant_id"] == "acme-electronics"

    # Test rule engine direct tool execution
    rule_forecast = agent_instance._process_with_rule_engine("Forecast sales demand and stockout risk", tenant_id="acme-electronics")
    assert any(tc["tool"] == "forecast_sales_demand" for tc in rule_forecast["tool_calls"])


def test_fastapi_multi_tenant_endpoints():
    """Test FastAPI REST endpoints with X-Tenant-ID header."""
    client = TestClient(app)

    # Health
    health = client.get("/health")
    assert health.status_code == 200

    # List tenants
    t_resp = client.get("/api/tenants")
    assert t_resp.status_code == 200
    assert len(t_resp.json()) >= 3

    # Sales API for Acme
    sales_resp = client.get("/api/sales/summary", headers={"X-Tenant-ID": "acme-electronics"})
    assert sales_resp.status_code == 200
    assert sales_resp.json()["tenant_id"] == "acme-electronics"

    # Sales API for BeanCrafters
    sales_beans = client.get("/api/sales/summary", headers={"X-Tenant-ID": "beancrafters-cafe"})
    assert sales_beans.status_code == 200
    assert sales_beans.json()["tenant_id"] == "beancrafters-cafe"

    # Chat API with Tenant Header
    chat_resp = client.post(
        "/api/chat",
        json={"message": "1"},
        headers={"X-Tenant-ID": "nova-apparel"}
    )
    assert chat_resp.status_code == 200
    assert "nova-apparel" in chat_resp.json()["reply"]

    # CSV Export with Tenant
    csv_resp = client.get("/api/export/csv", headers={"X-Tenant-ID": "nova-apparel"})
    assert csv_resp.status_code == 200
    assert "TenantID" in csv_resp.text


def test_user_authentication_flow():
    """Test login, registration, password hashing, and token verification."""
    client = TestClient(app)
    import time
    unique_ts = int(time.time() * 1000)
    test_user_email = f"testuser_{unique_ts}@example.com"

    # 1. Register a new user
    reg_resp = client.post("/api/auth/register", json={
        "email": test_user_email,
        "password": "initialPassword123!",
        "full_name": "Test User",
        "tenant_id": "acme-electronics",
        "role": "OWNER"
    })
    assert reg_resp.status_code == 200
    reg_data = reg_resp.json()
    assert "token" in reg_data
    assert reg_data["user"]["email"] == test_user_email
    token = reg_data["token"]

    # 2. Access /api/auth/me with Bearer token
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["full_name"] == "Test User"
    assert me_resp.json()["role"] == "OWNER"

    # 3. Reject invalid password
    bad_login = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "wrongpassword"
    })
    assert bad_login.status_code == 401

    # 4. Login with valid password
    login_resp = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "initialPassword123!"
    })
    assert login_resp.status_code == 200
    assert "token" in login_resp.json()
    login_token = login_resp.json()["token"]

    # 5. Logout and revoke token
    logout_resp = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {login_token}"})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["success"] is True

    # 6. Verify revoked token is now rejected by /api/auth/me
    revoked_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login_token}"})
    assert revoked_me.status_code == 401

    # 7. Reset password flow
    reset_resp = client.post("/api/auth/reset-password", json={
        "email": test_user_email,
        "new_password": "NewSecretPass456!"
    })
    assert reset_resp.status_code == 200
    assert "token" in reset_resp.json()

    # 8. Login with newly updated password
    new_login = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "NewSecretPass456!"
    })
    assert new_login.status_code == 200
    assert new_login.json()["user"]["email"] == test_user_email

    # 9. Verify old password is now rejected
    old_login = client.post("/api/auth/login", json={
        "email": test_user_email,
        "password": "initialPassword123!"
    })
    assert old_login.status_code == 401


def test_cloud_scheduler_cron_daily_report():
    """Test Cloud Scheduler cron automated execution and multi-channel report dispatch."""
    client = TestClient(app)

    # 1. Trigger cron for all tenants
    cron_resp = client.post("/api/cron/daily-report", json={
        "channel": "all",
        "notify": True
    })
    assert cron_resp.status_code == 200
    data = cron_resp.json()
    assert data["status"] == "SUCCESS"
    assert data["job"] == "daily-productivity-briefing"
    assert data["tenants_processed"] >= 3
    assert len(data["results"]) >= 3

    # 2. Trigger cron for a specific tenant
    single_resp = client.post("/api/cron/daily-report", json={
        "tenant_id": "beancrafters-cafe",
        "channel": "slack",
        "notify": True
    })
    assert single_resp.status_code == 200
    single_data = single_resp.json()
    assert single_data["tenants_processed"] == 1
    assert single_data["results"][0]["tenant_id"] == "beancrafters-cafe"


def test_expense_tracker_module_and_api():
    """Test expense logging, category filtering, and P&L financial summary calculation."""
    client = TestClient(app)

    # 1. Log an expense via API
    log_resp = client.post("/api/expenses/log", json={
        "category": "Marketing",
        "description": "Google Search Ads Q3",
        "amount": 150.00,
        "payment_method": "CREDIT_CARD"
    }, headers={"X-Tenant-ID": "acme-electronics"})
    assert log_resp.status_code == 200
    assert log_resp.json()["amount"] == 150.00

    # 2. Query expenses list
    list_resp = client.get("/api/expenses", headers={"X-Tenant-ID": "acme-electronics"})
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    # 3. Query financial P&L summary
    summary_resp = client.get("/api/expenses/summary", headers={"X-Tenant-ID": "acme-electronics"})
    assert summary_resp.status_code == 200
    summary = summary_resp.json()
    assert "gross_revenue" in summary
    assert "gross_profit" in summary
    assert "net_profit" in summary
    assert "gross_margin_pct" in summary


def test_employee_shifts_and_productivity_api():
    """Test employee shift scheduling and team productivity metrics."""
    client = TestClient(app)

    # 1. Schedule a shift
    shift_resp = client.post("/api/employees/shifts/schedule", json={
        "employee_name": "Sarah Connor",
        "role": "Security & Inventory Lead",
        "start_time": "07:00",
        "end_time": "15:00"
    }, headers={"X-Tenant-ID": "acme-electronics"})
    assert shift_resp.status_code == 200
    assert shift_resp.json()["employee_name"] == "Sarah Connor"

    # 2. List shifts
    shifts_list = client.get("/api/employees/shifts", headers={"X-Tenant-ID": "acme-electronics"})
    assert shifts_list.status_code == 200
    assert len(shifts_list.json()) >= 1

    # 3. Get team productivity report
    prod_resp = client.get("/api/employees/productivity", headers={"X-Tenant-ID": "acme-electronics"})
    assert prod_resp.status_code == 200
    prod_data = prod_resp.json()
    assert "total_tasks" in prod_data
    assert "team_completion_rate_pct" in prod_data
    assert "assignee_breakdown" in prod_data


def test_customer_feedback_module_and_api():
    """Test customer review ingestion, sentiment rating, and NPS analytics."""
    client = TestClient(app)

    # 1. Submit a 5-star review
    rev_resp = client.post("/api/feedback/review", json={
        "customer_name": "Jane Doe",
        "rating": 5,
        "feedback_text": "Incredible delivery speed and premium product quality!",
        "source": "Shopify"
    }, headers={"X-Tenant-ID": "acme-electronics"})
    assert rev_resp.status_code == 200
    assert rev_resp.json()["sentiment"] == "POSITIVE"

    # 2. Get feedback report & NPS score
    report_resp = client.get("/api/feedback/report", headers={"X-Tenant-ID": "acme-electronics"})
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert report["total_reviews"] >= 1
    assert "average_rating" in report
    assert "nps_score" in report
    assert "actionable_insights" in report


def test_sales_and_inventory_connectors():
    """Test external connector abstraction classes (Stripe, Square, Shopify, Firestore, Supabase)."""
    from integrations.sales_connectors import StripePOSConnector, SquarePOSConnector, ShopifyConnector, UnifiedSalesManager
    from integrations.inventory_connectors import FirestoreInventoryConnector, SupabaseInventoryConnector, UnifiedInventoryManager

    # Sales connectors
    stripe = StripePOSConnector()
    square = SquarePOSConnector()
    shopify = ShopifyConnector()
    assert len(stripe.fetch_daily_sales("acme-electronics")) >= 1
    assert len(square.fetch_daily_sales("beancrafters-cafe")) >= 1
    assert len(shopify.fetch_daily_sales("nova-apparel")) >= 1

    unified_sales = UnifiedSalesManager()
    summary = unified_sales.get_consolidated_sales_summary("acme-electronics")
    assert summary["gross_revenue"] > 0

    # Inventory connectors
    firestore = FirestoreInventoryConnector()
    supabase = SupabaseInventoryConnector()
    assert len(firestore.get_stock_levels("acme-electronics")) >= 1
    assert len(supabase.get_stock_levels("beancrafters-cafe")) >= 1

    unified_inv = UnifiedInventoryManager()
    inv_report = unified_inv.get_consolidated_inventory_report("acme-electronics")
    assert "total_products" in inv_report


def test_vercel_routing_and_index_serving():
    """Test Vercel serverless prefix rewrites and HTML landing page serving."""
    client = TestClient(app)

    # Root route
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "Aero Copilot" in r_root.text or "text/html" in r_root.headers.get("content-type", "")

    # Vercel function path rewrite aliases
    r_vercel1 = client.get("/api/index.py")
    assert r_vercel1.status_code == 200

    r_vercel2 = client.get("/api/index")
    assert r_vercel2.status_code == 200

    r_vercel3 = client.get("/api")
    assert r_vercel3.status_code == 200

    # Prefix stripping on API routes
    r_api = client.get("/api/index.py/api/tenants")
    assert r_api.status_code == 200
    assert len(r_api.json()) > 0

    # Static CSS and JS assets
    r_css = client.get("/static/style.css")
    assert r_css.status_code == 200
    assert "text/css" in r_css.headers.get("content-type", "")

    r_js = client.get("/static/app.js")
    assert r_js.status_code == 200
    assert "javascript" in r_js.headers.get("content-type", "")

    # Static CSS with serverless prefix
    r_css_pref = client.get("/api/index.py/static/style.css")
    assert r_css_pref.status_code == 200
    assert "text/css" in r_css_pref.headers.get("content-type", "")

    # Vercel rewrite header simulation
    r_vercel_css = client.get("/api/index.py", headers={"x-matched-path": "/static/style.css"})
    assert r_vercel_css.status_code == 200
    assert "text/css" in r_vercel_css.headers.get("content-type", "")

    r_vercel_js = client.get("/api/index.py", headers={"x-matched-path": "/static/app.js"})
    assert r_vercel_js.status_code == 200
    assert "javascript" in r_vercel_js.headers.get("content-type", "")

    # Favicon serving
    r_fav = client.get("/favicon.ico")
    assert r_fav.status_code == 200

def test_product_add_and_retrieval_flow():
    """Test adding new products via direct API, root serverless POST, and agent."""
    client = TestClient(app)
    import time
    base_ts = int(time.time() * 1000) % 100000
    sku1 = f"SKU-T{base_ts}"
    sku2 = f"SKU-U{base_ts}"
    sku3 = f"SKU-V{base_ts}"

    # 1. Add product via /api/products/add
    res1 = client.post("/api/products/add", json={
        "sku": sku1,
        "name": "Wireless Charging Mouse Pad",
        "category": "Accessories",
        "stock_quantity": 40,
        "low_stock_threshold": 15,
        "unit_price": 34.99,
        "cost_price": 14.00
    }, headers={"X-Tenant-ID": "acme-electronics"})
    assert res1.status_code == 200
    assert res1.json()["success"] is True
    assert res1.json()["sku"] == sku1

    # 2. Verify retrieval in /api/products
    list_res = client.get("/api/products", headers={"X-Tenant-ID": "acme-electronics"})
    assert list_res.status_code == 200
    skus = [p["sku"] for p in list_res.json()["products"]]
    assert sku1 in skus

    # 3. Add product via root POST /api/index.py (serverless fallback)
    res_root = client.post("/api/index.py", json={
        "sku": sku2,
        "name": "Bluetooth Mechanical Numpad",
        "category": "Peripherals",
        "stock_quantity": 25,
        "low_stock_threshold": 10,
        "unit_price": 59.99,
        "cost_price": 25.00
    }, headers={"X-Tenant-ID": "acme-electronics"})
    assert res_root.status_code == 200
    assert res_root.json()["success"] is True

    # 4. Verify duplicate SKU rejection
    dup_res = client.post("/api/products/add", json={
        "sku": sku1,
        "name": "Duplicate Pad"
    }, headers={"X-Tenant-ID": "acme-electronics"})
    assert dup_res.status_code == 400

    # 5. Add product via agent rule engine
    agent_res = agent_instance.process_message(f"Add product {sku3} Smart RGB Lightstrip", tenant_id="acme-electronics")
    assert sku3 in agent_res["reply"]
    assert any(tc["tool"] == "add_new_product" for tc in agent_res["tool_calls"])


def test_google_authentication_flow():
    """Test Google OAuth Signup/Login endpoint and user provisioning."""
    import secrets
    client = TestClient(app)
    test_google_email = f"googleuser_{secrets.token_hex(4)}@gmail.com"

    # 1. Signup/Login new user with Google Auth
    res = client.post("/api/auth/google", json={
        "email": test_google_email,
        "full_name": "Google Test User",
        "tenant_id": "beancrafters-cafe"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "token" in data
    assert data["user"]["email"] == test_google_email
    assert data["user"]["tenant_id"] == "beancrafters-cafe"
    assert data["user"]["role"] == "OWNER"

    token = data["token"]

    # 2. Verify /api/auth/me works with returned token
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == test_google_email
    assert me_data["tenant_id"] == "beancrafters-cafe"

    # 3. Existing Google user login
    res_login = client.post("/api/auth/google", json={
        "email": test_google_email,
        "full_name": "Google Test User"
    })
    assert res_login.status_code == 200
    login_data = res_login.json()
    assert login_data["success"] is True
    assert login_data["user"]["user_id"] == data["user"]["user_id"]








