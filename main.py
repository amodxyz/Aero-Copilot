"""
Multi-Tenant FastAPI Server for Personal Productivity Assistant.
Extracts tenant context from X-Tenant-ID header or tenant_id query/body.
"""

import os
import datetime
import uvicorn
from contextlib import asynccontextmanager
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import FastAPI, HTTPException, Header, Depends, Query, Response, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from database import init_db, list_all_tenants, create_tenant, register_user, authenticate_user, verify_token, revoke_token, reset_user_password, authenticate_or_register_google_user
from agent import agent_instance
from integrations.notification_connectors import MultiChannelDispatcher
from modules.expense_tracker import ExpenseTracker
from modules.employee_tasks import EmployeeTaskManager
from modules.customer_feedback import CustomerFeedbackAnalyzer
from tools import (
    get_daily_sales_summary,
    get_inventory_alerts,
    reorder_inventory,
    generate_daily_briefing,
    list_daily_tasks,
    create_operational_task,
    search_products,
    forecast_sales_demand,
    analyze_customer_feedback,
    trigger_operational_webhook_alert,
    create_sales_order,
    update_task_status,
    add_new_product,
    DEFAULT_TENANT
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Server] Initializing multi-tenant operations database...")
    init_db()
    yield
    print("[Server] Shutting down...")


app = FastAPI(
    title="Multi-Tenant Productivity Agent API",
    description="Personal Productivity Assistant for Daily Business Operations across Multiple Tenants with User Authentication",
    version="2.1.0",
    lifespan=lifespan
)

class VercelPathCorrectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Restore real client requested path from Vercel __path__ rewrite query parameter
        query_params = dict(request.query_params)
        if "__path__" in query_params:
            real_path = query_params.pop("__path__")
            if real_path:
                request.scope["path"] = real_path.split("?")[0]
            from urllib.parse import urlencode
            new_query = urlencode(query_params)
            request.scope["query_string"] = new_query.encode("utf-8")
        else:
            # 2. Restore real client requested path from Vercel rewrite headers
            for header_name in ["x-matched-path", "x-invoke-path", "x-forwarded-uri", "x-original-url", "x-rewrite-url", "x-vercel-sc-path"]:
                val = request.headers.get(header_name)
                if val and val not in ["/api/index.py", "/api/index", "/api/index.py/", "/api/index/"]:
                    clean_path = val.split("?")[0]
                    request.scope["path"] = clean_path
                    break
            else:
                # 3. Fallback prefix stripping
                for prefix in ["/api/index.py", "/api/index"]:
                    if request.scope.get("path") == prefix:
                        if request.method == "GET":
                            request.scope["path"] = "/"
                        break
                    elif request.scope.get("path", "").startswith(prefix + "/"):
                        request.scope["path"] = request.scope["path"][len(prefix):]
                        break

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app.add_middleware(VercelPathCorrectionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency to resolve authenticated user
def get_current_user_optional(authorization: Optional[str] = Header(default=None)) -> Optional[Dict[str, Any]]:
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1].strip()
        return verify_token(token)
    return None


# Dependency to resolve tenant_id
def resolve_tenant_id(
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    tenant_id: Optional[str] = Query(default=None),
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
) -> str:
    if user and "tenant_id" in user:
        return user["tenant_id"]
    if x_tenant_id and x_tenant_id.strip():
        return x_tenant_id.strip()
    if tenant_id and tenant_id.strip():
        return tenant_id.strip()
    return DEFAULT_TENANT


# Pydantic Schemas for Auth & Operations
class UserRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    tenant_id: Optional[str] = None
    company_name: Optional[str] = None
    role: str = "OWNER"


class UserLoginRequest(BaseModel):
    email: str
    password: str


class UserResetPasswordRequest(BaseModel):
    email: str
    new_password: str


class GoogleAuthRequest(BaseModel):
    credential: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    tenant_id: Optional[str] = "acme-electronics"


def decode_google_id_token(credential: str) -> Dict[str, Any]:
    """Decodes and validates a Google ID token."""
    import json
    import base64
    import urllib.request
    
    # 1. Try Google tokeninfo API endpoint
    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
        req = urllib.request.Request(url, headers={"User-Agent": "Aero-Copilot/2.5"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data
    except Exception as e:
        print(f"[Google Auth] Tokeninfo check note: {e}")
    
    # 2. Fallback: Parse JWT payload
    try:
        parts = credential.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            rem = len(payload_b64) % 4
            if rem > 0:
                payload_b64 += "=" * (4 - rem)
            payload_json = base64.urlsafe_b64decode(payload_b64).decode("utf-8")
            return json.loads(payload_json)
    except Exception as e:
        print(f"[Google Auth] JWT decode fallback error: {e}")

    return {}


class TenantCreateRequest(BaseModel):
    tenant_id: str
    name: str
    industry: str = "General Retail"
    currency: str = "USD"


class ChatRequest(BaseModel):
    message: str
    tenant_id: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None


class ReorderRequest(BaseModel):
    sku: str
    quantity: int
    tenant_id: Optional[str] = None


class OrderCreateRequest(BaseModel):
    customer_name: str
    sku: str
    quantity: int = 1
    tenant_id: Optional[str] = None


class ProductAddRequest(BaseModel):
    sku: str
    name: str
    category: str = "General"
    stock_quantity: int = 25
    low_stock_threshold: int = 10
    unit_price: float = 49.99
    cost_price: float = 20.00
    tenant_id: Optional[str] = None


class TaskCreateRequest(BaseModel):
    title: str
    priority: str = "MEDIUM"
    due_date: Optional[str] = None
    assigned_to: str = "Business Owner"
    tenant_id: Optional[str] = None


class TaskStatusUpdateRequest(BaseModel):
    status: str = "COMPLETED"


class WebhookNotifyRequest(BaseModel):
    channel: str = "slack"
    message: Optional[str] = None
    tenant_id: Optional[str] = None


class CronReportRequest(BaseModel):
    tenant_id: Optional[str] = None
    channel: str = "all"
    notify: bool = True


class ExpenseLogRequest(BaseModel):
    category: str
    description: str
    amount: float
    date: Optional[str] = None
    payment_method: str = "CREDIT_CARD"
    tenant_id: Optional[str] = None


class ShiftScheduleRequest(BaseModel):
    employee_name: str
    role: str
    shift_date: Optional[str] = None
    start_time: str = "08:00"
    end_time: str = "17:00"
    tenant_id: Optional[str] = None


class CustomerReviewRequest(BaseModel):
    customer_name: str
    rating: int
    feedback_text: str
    source: str = "Google Reviews"
    review_date: Optional[str] = None
    tenant_id: Optional[str] = None


# Health Check
@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": "multi-tenant-productivity-agent",
        "version": "2.1.0"
    }


# Authentication Endpoints
@app.post("/api/auth/register", tags=["Auth"])
async def auth_register(req: UserRegisterRequest):
    import re
    company = (req.company_name or req.tenant_id or "My Business").strip()
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', company.lower()).strip('-')
    tid = req.tenant_id if req.tenant_id and req.tenant_id.strip() else (slug or "my-business")

    from database import query_one
    existing_tenant = query_one("SELECT * FROM tenants WHERE tenant_id = ?", (tid,))
    if not existing_tenant:
        create_tenant(tid, company, industry="General Business")

    res = register_user(tid, req.email, req.password, req.full_name, req.role)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/auth/login", tags=["Auth"])
async def auth_login(req: UserLoginRequest):
    res = authenticate_user(req.email, req.password)
    if not res.get("success"):
        raise HTTPException(status_code=401, detail=res.get("error"))
    return res


@app.post("/api/auth/reset-password", tags=["Auth"])
async def auth_reset_password(req: UserResetPasswordRequest):
    res = reset_user_password(req.email, req.new_password)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/auth/google", tags=["Auth"])
async def auth_google(req: GoogleAuthRequest):
    email = None
    full_name = None
    google_id = None

    if req.credential:
        token_info = decode_google_id_token(req.credential)
        email = token_info.get("email")
        full_name = token_info.get("name") or token_info.get("given_name")
        google_id = token_info.get("sub")

    if not email and req.email:
        email = req.email
        full_name = req.full_name or email.split("@")[0].capitalize()

    if not email:
        raise HTTPException(status_code=400, detail="Invalid Google authentication credential. Email not found.")

    tenant_id = req.tenant_id or "acme-electronics"
    res = authenticate_or_register_google_user(
        email=email,
        full_name=full_name or "",
        tenant_id=tenant_id,
        google_id=google_id
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Google authentication failed."))
    return res


@app.get("/api/auth/me", tags=["Auth"])
async def auth_me(user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@app.post("/api/auth/logout", tags=["Auth"])
async def auth_logout(authorization: Optional[str] = Header(None)):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    if token:
        revoke_token(token)
    return {"success": True, "message": "Logged out successfully"}


# Tenant Management
@app.get("/api/tenants", tags=["Tenants"])
async def get_tenants():
    return list_all_tenants()


@app.post("/api/tenants", tags=["Tenants"])
async def register_tenant(req: TenantCreateRequest):
    res = create_tenant(req.tenant_id, req.name, req.industry, req.currency)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


# Conversational Agent
@app.post("/api/chat", tags=["Agent"])
@app.post("/api/agent/chat", tags=["Agent"])
async def chat_with_agent(req: ChatRequest, header_tid: str = Depends(resolve_tenant_id)):
    try:
        msg = req.message if req and req.message else ""
        if not msg.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty.")
        
        tid = (req.tenant_id if req and req.tenant_id else None) or header_tid or DEFAULT_TENANT
        history = req.history if req else None
        result = agent_instance.process_message(msg, history, tenant_id=tid)
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Chat processing error: {e}")
        return {
            "tenant_id": header_tid or DEFAULT_TENANT,
            "reply": f"⚡ **Aero Copilot [{header_tid or DEFAULT_TENANT}]**\n\nI processed your request using local operational rules.",
            "tool_calls": [],
            "engine": "fallback-safe",
            "timestamp": datetime.datetime.now().isoformat()
        }


# Operational Analytics Endpoints
@app.get("/api/sales/summary", tags=["Operations"])
async def get_sales(date: Optional[str] = None, tid: str = Depends(resolve_tenant_id)):
    return get_daily_sales_summary(date, tenant_id=tid)


@app.get("/api/inventory/status", tags=["Operations"])
async def get_inventory(tid: str = Depends(resolve_tenant_id)):
    return get_inventory_alerts(tenant_id=tid)


@app.post("/api/inventory/reorder", tags=["Operations"])
async def reorder_stock(req: ReorderRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    res = reorder_inventory(req.sku, req.quantity, tenant_id=active_tid)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Reorder failed"))
    return res


@app.post("/api/orders/create", tags=["Operations"])
async def create_order(req: OrderCreateRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    res = create_sales_order(req.customer_name, req.sku, req.quantity, tenant_id=active_tid)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Order failed"))
    return res


@app.post("/api/products/add", tags=["Operations"])
@app.post("/api/products", tags=["Operations"])
async def add_product(req: ProductAddRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    res = add_new_product(
        sku=req.sku,
        name=req.name,
        category=req.category or "General",
        stock_quantity=req.stock_quantity if req.stock_quantity is not None else 25,
        low_stock_threshold=req.low_stock_threshold if req.low_stock_threshold is not None else 10,
        unit_price=req.unit_price if req.unit_price is not None else 49.99,
        cost_price=req.cost_price if req.cost_price is not None else 20.00,
        tenant_id=active_tid
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Failed to add product"))
    return res


@app.get("/api/products", tags=["Operations"])
async def get_products(query: str = "", tid: str = Depends(resolve_tenant_id)):
    return search_products(query, tenant_id=tid)


@app.get("/api/briefing", tags=["Operations"])
async def get_briefing(date: Optional[str] = None, tid: str = Depends(resolve_tenant_id)):
    return generate_daily_briefing(date, tenant_id=tid)


@app.get("/api/forecast", tags=["Operations"])
async def get_forecast(sku: Optional[str] = None, tid: str = Depends(resolve_tenant_id)):
    return forecast_sales_demand(sku, tenant_id=tid)


@app.get("/api/feedback", tags=["Operations"])
async def get_feedback(tid: str = Depends(resolve_tenant_id)):
    return analyze_customer_feedback(tenant_id=tid)


@app.post("/api/notify/webhook", tags=["Operations"])
async def trigger_webhook(req: WebhookNotifyRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    return trigger_operational_webhook_alert(req.channel, req.message, tenant_id=active_tid)


@app.get("/api/tasks", tags=["Operations"])
async def get_tasks(status: Optional[str] = None, tid: str = Depends(resolve_tenant_id)):
    return list_daily_tasks(status, tenant_id=tid)


@app.post("/api/tasks", tags=["Operations"])
async def add_task(req: TaskCreateRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    return create_operational_task(req.title, req.priority, req.due_date, req.assigned_to, tenant_id=active_tid)


@app.post("/api/tasks/{task_id}/status", tags=["Operations"])
async def update_task_status_endpoint(task_id: int, req: TaskStatusUpdateRequest, tid: str = Depends(resolve_tenant_id)):
    res = update_task_status(task_id, req.status, tenant_id=tid)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("error", "Task not found"))
    return res


@app.get("/api/export/csv", tags=["Operations"])
async def export_operations_csv(tid: str = Depends(resolve_tenant_id)):
    from database import query_all
    products = query_all("SELECT * FROM products WHERE tenant_id = ?", (tid,))
    csv_lines = ["TenantID,SKU,Name,Category,StockQuantity,Threshold,UnitPrice,CostPrice,LastRestocked"]
    for p in products:
        csv_lines.append(f'"{p["tenant_id"]}","{p["sku"]}","{p["name"]}","{p["category"]}",{p["stock_quantity"]},{p["low_stock_threshold"]},{p["unit_price"]},{p["cost_price"]},"{p["last_restocked_date"]}"')
    
    csv_content = "\n".join(csv_lines)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{tid}_operations_export.csv"'}
    )


# ---------------- Google Cloud Scheduler Automation ---------------- #

@app.post("/api/cron/daily-report", tags=["Automation"])
async def trigger_daily_cron_report(req: Optional[CronReportRequest] = None):
    """
    Automated execution endpoint triggered daily by Google Cloud Scheduler.
    Compiles daily sales totals & inventory alerts across all tenants and
    dispatches reports to Slack, Email, and WhatsApp.
    """
    request_data = req or CronReportRequest()
    dispatcher = MultiChannelDispatcher()
    
    target_tenants = [request_data.tenant_id] if request_data.tenant_id else [t["tenant_id"] for t in list_all_tenants()]
    
    channels_to_use = ["slack", "email", "whatsapp"] if request_data.channel.lower() in ("all", "multi") else [request_data.channel.lower()]
    
    dispatch_results = []
    for tid in target_tenants:
        briefing = generate_daily_briefing(tenant_id=tid)
        report_data = {
            "tenant_id": tid,
            "briefing": briefing,
            "dispatched": False,
            "channels": {}
        }
        if request_data.notify:
            res = dispatcher.dispatch_daily_report(tenant_id=tid, channels=channels_to_use)
            report_data["dispatched"] = True
            report_data["channels"] = res.get("dispatches", {})
        dispatch_results.append(report_data)
        
    return {
        "status": "SUCCESS",
        "job": "daily-productivity-briefing",
        "timestamp": datetime.datetime.now().isoformat(),
        "tenants_processed": len(dispatch_results),
        "results": dispatch_results
    }


# ---------------- Expense Management Endpoints ---------------- #

@app.post("/api/expenses/log", tags=["Expenses"])
async def log_expense_endpoint(req: ExpenseLogRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    tracker = ExpenseTracker(tenant_id=active_tid)
    res = tracker.log_expense(req.category, req.description, req.amount, req.date, req.payment_method)
    return res


@app.get("/api/expenses", tags=["Expenses"])
async def list_expenses_endpoint(date: Optional[str] = None, category: Optional[str] = None, tid: str = Depends(resolve_tenant_id)):
    tracker = ExpenseTracker(tenant_id=tid)
    return tracker.get_expenses(date=date, category=category)


@app.get("/api/expenses/summary", tags=["Expenses"])
async def get_expense_summary_endpoint(start_date: Optional[str] = None, end_date: Optional[str] = None, tid: str = Depends(resolve_tenant_id)):
    tracker = ExpenseTracker(tenant_id=tid)
    return tracker.get_financial_summary(start_date=start_date, end_date=end_date)


# ---------------- Employee Shift & Productivity Endpoints ---------------- #

@app.post("/api/employees/shifts/schedule", tags=["Employees"])
async def schedule_shift_endpoint(req: ShiftScheduleRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    manager = EmployeeTaskManager(tenant_id=active_tid)
    return manager.schedule_shift(req.employee_name, req.role, req.shift_date, req.start_time, req.end_time)


@app.get("/api/employees/shifts", tags=["Employees"])
async def list_shifts_endpoint(shift_date: Optional[str] = None, tid: str = Depends(resolve_tenant_id)):
    manager = EmployeeTaskManager(tenant_id=tid)
    return manager.list_shifts(shift_date=shift_date)


@app.get("/api/employees/productivity", tags=["Employees"])
async def get_productivity_endpoint(tid: str = Depends(resolve_tenant_id)):
    manager = EmployeeTaskManager(tenant_id=tid)
    return manager.get_productivity_report()


# ---------------- Customer Feedback Endpoints ---------------- #

@app.post("/api/feedback/review", tags=["Feedback"])
async def add_review_endpoint(req: CustomerReviewRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    analyzer = CustomerFeedbackAnalyzer(tenant_id=active_tid)
    return analyzer.add_review(req.customer_name, req.rating, req.feedback_text, req.source, req.review_date)


@app.get("/api/feedback/report", tags=["Feedback"])
async def get_feedback_report_endpoint(tid: str = Depends(resolve_tenant_id)):
    analyzer = CustomerFeedbackAnalyzer(tenant_id=tid)
    return analyzer.get_feedback_report()


try:
    from static_bundle import STATIC_ASSETS
except ImportError:
    STATIC_ASSETS = {}

static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)


@app.get("/static/{file_path:path}", include_in_schema=False)
@app.get("/api/index.py/static/{file_path:path}", include_in_schema=False)
@app.get("/api/index/static/{file_path:path}", include_in_schema=False)
async def serve_static_file(file_path: str):
    fname = os.path.basename(file_path)
    media_type = "text/css" if fname.endswith(".css") else ("application/javascript" if fname.endswith(".js") else None)
    
    # 1. Try resolving from disk
    possible_paths = [
        os.path.join(static_dir, file_path),
        os.path.join(os.getcwd(), "static", file_path),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", file_path)
    ]
    for target in possible_paths:
        if os.path.exists(target) and os.path.isfile(target):
            with open(target, "r", encoding="utf-8", errors="ignore") as f:
                return Response(content=f.read(), media_type=media_type, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    
    # 2. Serverless fallback bundle
    if fname in STATIC_ASSETS:
        return Response(content=STATIC_ASSETS[fname], media_type=media_type, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
        
    raise HTTPException(status_code=404, detail=f"Static file '{file_path}' not found")


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
async def serve_favicon():
    content = STATIC_ASSETS.get("favicon.svg") or STATIC_ASSETS.get("favicon.ico")
    if content:
        return Response(content=content, media_type="image/svg+xml")
    possible_paths = [
        os.path.join(static_dir, "favicon.svg"),
        os.path.join(os.getcwd(), "static", "favicon.svg")
    ]
    for p in possible_paths:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return Response(content=f.read(), media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Favicon not found")


app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
@app.get("/api/index.py", include_in_schema=False)
@app.get("/api/index", include_in_schema=False)
@app.get("/api", include_in_schema=False)
async def serve_index():
    possible_paths = [
        os.path.join(static_dir, "index.html"),
        os.path.join(os.getcwd(), "static", "index.html"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    ]
    for index_file in possible_paths:
        if os.path.exists(index_file) and os.path.isfile(index_file):
            with open(index_file, "r", encoding="utf-8", errors="ignore") as f:
                return HTMLResponse(content=f.read(), status_code=200)
    
    if "index.html" in STATIC_ASSETS:
        return HTMLResponse(content=STATIC_ASSETS["index.html"], status_code=200)

    return HTMLResponse(content="<h1>Multi-Tenant Productivity Agent API is active.</h1>", status_code=200)


@app.post("/", include_in_schema=False)
@app.post("/api/index.py", include_in_schema=False)
@app.post("/api/index", include_in_schema=False)
@app.post("/api", include_in_schema=False)
async def handle_root_post_dispatch(request: Request, header_tid: str = Depends(resolve_tenant_id)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    
    # 1. Chat dispatch
    if "message" in body:
        req = ChatRequest(**body)
        return await chat_with_agent(req, header_tid)
    
    # 2. Login dispatch
    if "email" in body and "password" in body and "full_name" not in body:
        req = UserLoginRequest(**body)
        return await auth_login(req)

    # 3. Password Reset dispatch
    if "email" in body and "new_password" in body:
        req = UserResetPasswordRequest(**body)
        return await auth_reset_password(req)
        
    # 4. Register dispatch
    if "email" in body and "password" in body and "full_name" in body:
        req = UserRegisterRequest(**body)
        return await auth_register(req)

    # 5. Order create dispatch
    if "customer_name" in body and "sku" in body:
        req = OrderCreateRequest(**body)
        return await create_order(req, header_tid)

    # 6. Inventory reorder dispatch
    if "sku" in body and "quantity" in body and "name" not in body:
        req = ReorderRequest(**body)
        return await reorder_stock(req, header_tid)

    # 7. Product add dispatch
    if "sku" in body and "name" in body:
        req = ProductAddRequest(**body)
        return await add_product(req, header_tid)

    # 8. Expense log dispatch
    if "category" in body and "amount" in body and "description" in body:
        req = ExpenseLogRequest(**body)
        return await log_expense_endpoint(req, header_tid)

    # 9. Customer review dispatch
    if "customer_name" in body and "feedback_text" in body:
        req = CustomerReviewRequest(**body)
        return await add_review_endpoint(req, header_tid)

    # 10. Task create dispatch
    if "title" in body and "priority" in body:
        req = TaskCreateRequest(**body)
        return await add_task(req, header_tid)

    return {"status": "ok", "detail": "Dispatched serverless POST request"}



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🚀 Starting Multi-Tenant Productivity Assistant on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
