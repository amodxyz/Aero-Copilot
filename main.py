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
from fastapi import FastAPI, HTTPException, Header, Depends, Query, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from database import init_db, list_all_tenants, create_tenant, register_user, authenticate_user, verify_token, revoke_token
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
    tenant_id: str
    role: str = "OWNER"


class UserLoginRequest(BaseModel):
    email: str
    password: str


class TenantCreateRequest(BaseModel):
    tenant_id: str
    name: str
    industry: str = "General Retail"
    currency: str = "USD"


class ChatRequest(BaseModel):
    message: str
    tenant_id: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None


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
    res = register_user(req.tenant_id, req.email, req.password, req.full_name, req.role)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/auth/login", tags=["Auth"])
async def auth_login(req: UserLoginRequest):
    res = authenticate_user(req.email, req.password)
    if not res.get("success"):
        raise HTTPException(status_code=401, detail=res.get("error"))
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
async def chat_with_agent(req: ChatRequest, header_tid: str = Depends(resolve_tenant_id)):
    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    
    tid = req.tenant_id or header_tid
    result = agent_instance.process_message(req.message, req.history, tenant_id=tid)
    return result


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
async def add_product(req: ProductAddRequest, tid: str = Depends(resolve_tenant_id)):
    active_tid = req.tenant_id or tid
    res = add_new_product(
        sku=req.sku,
        name=req.name,
        category=req.category,
        stock_quantity=req.stock_quantity,
        low_stock_threshold=req.low_stock_threshold,
        unit_price=req.unit_price,
        cost_price=req.cost_price,
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


static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Multi-Tenant Productivity Agent API is active."}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"🚀 Starting Multi-Tenant Productivity Assistant on {host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
