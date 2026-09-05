# Personal Productivity Agent for Small Business Operations (Google Cloud Run)

An enterprise-grade, multi-tenant AI Operational Assistant designed for small business owners to automate daily tasks: sales aggregation, real-time inventory tracking, multi-channel automated reporting, expense tracking, employee task management, and customer feedback analysis.

Deployed serverless on **Google Cloud Run** with automated scheduling via **Google Cloud Scheduler**.

---

## 🌟 Core Architecture & Capabilities

```
                                  +-------------------------------------------------------------+
                                  |                      Google Cloud Run                       |
                                  |                                                             |
+---------------------+           |   +-----------------------------------------------------+   |
|   Business Owner    |           |   |                 FastAPI Server                      |   |
|  (Web Dashboard /   | <=======> |   |  (Multi-Tenant Auth, REST APIs, Static Web UI)      |   |
|   Voice Interface)  |           |   +--------------------------+--------------------------+   |
+---------------------+           |                              |                              |
                                  |   +--------------------------v--------------------------+   |
+---------------------+           |   |             Aero Operations Agent                   |   |
| Google Cloud        |           |   |    (Gemini Tool-Calling + Intent Fallback Engine)   |   |
| Scheduler           | --------> |   +--------------------------+--------------------------+   |
| (08:00 AM Cron)     |           |                              |                              |
+---------------------+           |   +--------------------------v--------------------------+   |
                                  |   |   Operations Database & Tenant Data Isolation       |   |
                                  |   |   (Products, Orders, Tasks, Expenses, Shifts)       |   |
                                  |   +--------------------------+--------------------------+   |
                                  +------------------------------|------------------------------+
                                                                 |
                                   +-----------------------------+-----------------------------+
                                   |                             |                             |
                                   v                             v                             v
                     +---------------------------+ +---------------------------+ +---------------------------+
                     |      Sales POS / CRM      | |    Inventory Databases    | |   Notification Channels   |
                     |  - Stripe Invoicing       | |  - Google Cloud Firestore | |  - Slack Webhook / Bot    |
                     |  - Square POS             | |  - Supabase PostgreSQL    | |  - SendGrid / SMTP Email  |
                     |  - Shopify Storefront     | |  - SQLite Multi-Tenant    | |  - WhatsApp Business API  |
                     +---------------------------+ +---------------------------+ +---------------------------+
```

---

## 🚀 Key Modules & Feature Highlights

### 1. 📊 Sales Monitoring & Aggregation
- **POS / CRM Connectors**: Standardized connectors for **Stripe**, **Square**, and **Shopify** (`integrations/sales_connectors.py`).
- **Daily & Weekly Totals**: Summarizes gross revenue, order volume, average order value (AOV), and top-selling SKUs in JSON + human-readable summaries.

### 2. ⚠️ Real-Time Inventory Tracking
- **Multi-Database Support**: Connectors for **Google Cloud Firestore**, **Supabase PostgreSQL**, and local SQLite (`integrations/inventory_connectors.py`).
- **Threshold Alerts**: Compares live stock levels against low-stock threshold values and recommends reorder batch sizes.
- **Automated Reordering**: One-click and voice-commanded replenishment with audit logging.

### 3. 🔔 Reporting & Automated Multi-Channel Notifications
- **Multi-Channel Dispatcher**: Sends consolidated daily briefs via **Slack**, **Email (SendGrid/SMTP)**, and **WhatsApp Business API (Twilio)** (`integrations/notification_connectors.py`).
- **Scheduled Morning Reports**: Automated daily briefing triggered every morning at 08:00 AM via **Google Cloud Scheduler** (`/api/cron/daily-report`).

### 4. 🧩 Modular Extensibility
- **💰 Expense Tracking & P&L Analysis** (`modules/expense_tracker.py`): Tracks daily operational expenses (COGS, OpEx, Marketing, Supplies), calculates gross margins and net profit.
- **👥 Employee Tasks & Shift Management** (`modules/employee_tasks.py`): Allocates shift rosters, monitors task completion rates, and computes team productivity metrics.
- **⭐ Customer Feedback & Sentiment** (`modules/customer_feedback.py`): Ingests reviews, computes Net Promoter Score (NPS), and extracts actionable recommendations.

### 5. 🏢 Strict Multi-Tenancy & User Authentication
- **Tenant Data Isolation**: Complete data separation per tenant (`X-Tenant-ID` header or Bearer token).
- **Pre-Seeded Sample Businesses**:
  - `acme-electronics`: Consumer electronics retail & accessories.
  - `beancrafters-cafe`: Artisanal coffee roastery & cafe supplies.
  - `nova-apparel`: Sustainable streetwear & fashion retail.
- **User Authentication**: Salted SHA-256 password hashing with Bearer auth token sessions (`/api/auth/login`, `/api/auth/register`, `/api/auth/me`).

---

## 🛠️ Quickstart (Local Development)

### 1. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 2. Run the Application
```bash
python main.py
```
Open your browser at **`http://localhost:8080`** to access the web dashboard and interact with the agent.

### 3. Run Automated Tests
```bash
python -m pytest tests/ -v
```

---

## ☁️ Deployment Guide

### A. Deploy Agent to Google Cloud Run

#### Using PowerShell (Windows):
```powershell
.\deploy.ps1 -ProjectId YOUR_GCP_PROJECT_ID -Region us-central1
```

#### Using Bash (Linux / macOS / Cloud Shell):
```bash
chmod +x deploy.sh
./deploy.sh YOUR_GCP_PROJECT_ID us-central1
```

---

### B. Configure Google Cloud Scheduler (Automated Daily Briefing)

Google Cloud Scheduler invokes the `/api/cron/daily-report` endpoint every morning at 8:00 AM.

#### Using PowerShell:
```powershell
.\cloud_scheduler\setup_scheduler.ps1 -ProjectId YOUR_GCP_PROJECT_ID -Region us-central1
```

#### Using Bash:
```bash
chmod +x cloud_scheduler/setup_scheduler.sh
./cloud_scheduler/setup_scheduler.sh YOUR_GCP_PROJECT_ID us-central1
```

---

## 📋 Comprehensive API Endpoints

| Category | Endpoint | Method | Description |
| :--- | :--- | :---: | :--- |
| **Health** | `/health` | `GET` | Container health probe |
| **Auth** | `/api/auth/login` | `POST` | User login (returns Bearer auth token) |
| **Auth** | `/api/auth/register` | `POST` | Register new user account |
| **Auth** | `/api/auth/me` | `GET` | Get authenticated user profile |
| **Tenants** | `/api/tenants` | `GET` | List all registered tenants |
| **Tenants** | `/api/tenants` | `POST` | Register a new business tenant |
| **Agent** | `/api/chat` | `POST` | Conversational agent assistant |
| **Automation** | `/api/cron/daily-report` | `POST` | Cloud Scheduler morning trigger & dispatch |
| **Operations** | `/api/sales/summary` | `GET` | Daily sales totals & top sellers |
| **Operations** | `/api/inventory/status` | `GET` | Stock levels & low-stock alerts |
| **Operations** | `/api/inventory/reorder` | `POST` | Reorder product inventory |
| **Operations** | `/api/orders/create` | `POST` | Record a customer sales order |
| **Operations** | `/api/products/add` | `POST` | Add product to tenant catalog |
| **Operations** | `/api/briefing` | `GET` | Synthesized executive daily briefing |
| **Operations** | `/api/forecast` | `GET` | 7-day/30-day demand forecast |
| **Operations** | `/api/tasks` | `GET` / `POST` | Manage operational action items |
| **Operations** | `/api/export/csv` | `GET` | Export operational data to CSV |
| **Expenses** | `/api/expenses/log` | `POST` | Log operational expense |
| **Expenses** | `/api/expenses/summary` | `GET` | P&L summary, COGS, and gross margin |
| **Employees** | `/api/employees/shifts/schedule` | `POST` | Schedule staff shift |
| **Employees** | `/api/employees/productivity` | `GET` | Staff task completion & productivity |
| **Feedback** | `/api/feedback/review` | `POST` | Ingest customer feedback review |
| **Feedback** | `/api/feedback/report` | `GET` | Net Promoter Score (NPS) & sentiment |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) &copy; 2026 amodxyz. All rights reserved.
