"""
Multi-Tenant Database layer for Productivity Assistant Agent.
Supports strict data isolation per tenant_id across Products, Orders, Tasks, and Audit Logs.
"""

import os
import shutil
import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# On Vercel / Serverless platforms, the root directory is read-only. We use /tmp.
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get("NOW_REGION"):
    DB_PATH = Path("/tmp/operations.db")
    source_db = Path(__file__).resolve().parent / "operations.db"
    if not DB_PATH.exists() and source_db.exists():
        try:
            shutil.copyfile(source_db, DB_PATH)
        except Exception:
            pass
else:
    DB_PATH = Path(__file__).resolve().parent / "operations.db"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force_reseed: bool = False):
    """Initializes the multi-tenant database schema and populates sample tenant data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    if force_reseed:
        cursor.execute("DROP TABLE IF EXISTS customer_reviews")
        cursor.execute("DROP TABLE IF EXISTS employee_shifts")
        cursor.execute("DROP TABLE IF EXISTS expenses")
        cursor.execute("DROP TABLE IF EXISTS auth_tokens")
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("DROP TABLE IF EXISTS audit_logs")
        cursor.execute("DROP TABLE IF EXISTS daily_tasks")
        cursor.execute("DROP TABLE IF EXISTS order_items")
        cursor.execute("DROP TABLE IF EXISTS sales_orders")
        cursor.execute("DROP TABLE IF EXISTS products")
        cursor.execute("DROP TABLE IF EXISTS tenants")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            industry TEXT NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('OWNER', 'MANAGER', 'STAFF')),
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            tenant_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            stock_quantity INTEGER NOT NULL,
            low_stock_threshold INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            cost_price REAL NOT NULL,
            last_restocked_date TEXT,
            PRIMARY KEY (tenant_id, sku),
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_orders (
            tenant_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            order_date TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            total_amount REAL NOT NULL,
            payment_status TEXT NOT NULL,
            fulfillment_status TEXT NOT NULL,
            PRIMARY KEY (tenant_id, order_id),
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (tenant_id, order_id) REFERENCES sales_orders (tenant_id, order_id),
            FOREIGN KEY (tenant_id, sku) REFERENCES products (tenant_id, sku)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            priority TEXT NOT NULL CHECK(priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
            due_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED')),
            assigned_to TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'CREDIT_CARD',
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employee_shifts (
            shift_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            employee_name TEXT NOT NULL,
            role TEXT NOT NULL,
            shift_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'SCHEDULED',
            tasks_assigned INTEGER NOT NULL DEFAULT 0,
            tasks_completed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customer_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            review_date TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            sentiment TEXT NOT NULL CHECK(sentiment IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE')),
            feedback_text TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'Google Reviews',
            FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Check if tenants exist
    cursor.execute("SELECT COUNT(*) FROM tenants")
    if cursor.fetchone()[0] == 0:
        seed_multi_tenant_data(conn)

    conn.commit()
    conn.close()


def seed_multi_tenant_data(conn: sqlite3.Connection):
    """Populates 3 distinct sample business tenants with isolated operational catalogs & orders."""
    cursor = conn.cursor()
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    now_iso = datetime.datetime.now().isoformat()

    # 1. Tenants
    tenants = [
        ("acme-electronics", "Acme Electronics Corp", "Consumer Electronics", "USD", now_iso),
        ("beancrafters-cafe", "BeanCrafters Coffee Roastery", "Food & Beverage", "USD", now_iso),
        ("nova-apparel", "Nova Urban Apparel", "Fashion & Retail", "USD", now_iso),
    ]
    cursor.executemany("INSERT INTO tenants VALUES (?, ?, ?, ?, ?)", tenants)

    # 2. Products per Tenant
    products = [
        # Tenant 1: Acme Electronics
        ("acme-electronics", "SKU-101", "Ergonomic Mechanical Keyboard", "Electronics", 8, 15, 129.99, 65.00, yesterday),
        ("acme-electronics", "SKU-102", "Noise-Canceling Wireless Headset", "Electronics", 4, 10, 199.99, 95.00, yesterday),
        ("acme-electronics", "SKU-103", "4K Ultra-HD Monitor Stand", "Accessories", 42, 20, 49.99, 18.50, today),
        ("acme-electronics", "SKU-104", "USB-C Multi-Port Hub (8-in-1)", "Accessories", 3, 12, 59.99, 22.00, yesterday),
        ("acme-electronics", "SKU-105", "Smart LED Desk Lamp w/ Qi Charger", "Smart Home", 18, 15, 79.99, 32.00, today),
        
        # Tenant 2: BeanCrafters Coffee
        ("beancrafters-cafe", "COF-201", "Single-Origin Ethiopian Yirgacheffe (1kg)", "Coffee Beans", 6, 18, 34.50, 14.00, yesterday),
        ("beancrafters-cafe", "COF-202", "Organic Colombian Dark Roast (1kg)", "Coffee Beans", 2, 20, 29.00, 11.50, yesterday),
        ("beancrafters-cafe", "COF-203", "Ceramic Pour-Over Dripper Set", "Brewing Gear", 35, 15, 42.00, 16.00, today),
        ("beancrafters-cafe", "COF-204", "Artisanal Vanilla Syrup (750ml)", "Syrups", 4, 12, 18.99, 6.50, yesterday),
        ("beancrafters-cafe", "COF-205", "Cold Brew Filter Bags (50-pack)", "Accessories", 50, 15, 15.00, 4.20, today),

        # Tenant 3: Nova Urban Apparel
        ("nova-apparel", "APP-301", "Heavyweight Oversized Organic Hoodie", "Hoodies", 5, 25, 89.00, 32.00, yesterday),
        ("nova-apparel", "APP-302", "Vintage Washed Boxy Graphic Tee", "T-Shirts", 3, 20, 38.00, 12.00, yesterday),
        ("nova-apparel", "APP-303", "Minimalist Corduroy Cap", "Headwear", 60, 20, 28.00, 8.50, today),
        ("nova-apparel", "APP-304", "Recycled Canvas Everyday Tote Bag", "Accessories", 45, 15, 24.50, 7.00, today),
    ]
    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", products)

    # 3. Sales Orders per Tenant
    orders = [
        # Acme Electronics
        ("acme-electronics", "ORD-5001", today, "Acme Solutions Corp", 519.96, "PAID", "DELIVERED"),
        ("acme-electronics", "ORD-5002", today, "TechNova Labs", 389.97, "PAID", "PROCESSING"),
        ("acme-electronics", "ORD-5003", today, "David Chen", 179.98, "PAID", "SHIPPED"),
        
        # BeanCrafters
        ("beancrafters-cafe", "COF-9001", today, "The Daily Grind Espresso Bar", 690.00, "PAID", "DELIVERED"),
        ("beancrafters-cafe", "COF-9002", today, "Blue Sky Bakery & Cafe", 232.00, "PAID", "PROCESSING"),
        ("beancrafters-cafe", "COF-9003", today, "Emma Watson", 53.49, "PAID", "SHIPPED"),

        # Nova Apparel
        ("nova-apparel", "APP-7001", today, "Urban Trend Boutique", 890.00, "PAID", "DELIVERED"),
        ("nova-apparel", "APP-7002", today, "Liam Miller", 127.00, "PAID", "PROCESSING"),
    ]
    cursor.executemany("INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?, ?, ?)", orders)

    # 4. Order Items
    order_items = [
        # Acme
        ("acme-electronics", "ORD-5001", "SKU-101", 4, 129.99, 519.96),
        ("acme-electronics", "ORD-5002", "SKU-102", 1, 199.99, 199.99),
        ("acme-electronics", "ORD-5002", "SKU-104", 1, 59.99, 59.99),
        ("acme-electronics", "ORD-5002", "SKU-101", 1, 129.99, 129.99),
        ("acme-electronics", "ORD-5003", "SKU-104", 3, 59.99, 179.97),
        
        # BeanCrafters
        ("beancrafters-cafe", "COF-9001", "COF-201", 20, 34.50, 690.00),
        ("beancrafters-cafe", "COF-9002", "COF-202", 8, 29.00, 232.00),
        ("beancrafters-cafe", "COF-9003", "COF-201", 1, 34.50, 34.50),
        ("beancrafters-cafe", "COF-9003", "COF-204", 1, 18.99, 18.99),

        # Nova Apparel
        ("nova-apparel", "APP-7001", "APP-301", 10, 89.00, 890.00),
        ("nova-apparel", "APP-7002", "APP-301", 1, 89.00, 89.00),
        ("nova-apparel", "APP-7002", "APP-302", 1, 38.00, 38.00),
    ]
    cursor.executemany("INSERT INTO order_items (tenant_id, order_id, sku, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?, ?)", order_items)

    # 5. Tasks per Tenant
    tasks = [
        ("acme-electronics", "Authorize PO for Keyboards (SKU-101) & Multi-Port Hubs", "CRITICAL", today, "PENDING", "Business Owner"),
        ("acme-electronics", "Verify packing slips for ORD-5002 batch", "MEDIUM", today, "PENDING", "Fulfillment Ops"),

        ("beancrafters-cafe", "Order green coffee shipment for Colombian Dark Roast", "CRITICAL", today, "PENDING", "Head Roaster"),
        ("beancrafters-cafe", "Calibrate commercial batch roaster temperature sensors", "HIGH", today, "IN_PROGRESS", "Maintenance"),

        ("nova-apparel", "Confirm autumn restock delivery with knitwear manufacturer", "CRITICAL", today, "PENDING", "Production Lead"),
        ("nova-apparel", "Update lookbook photography for corduroy caps", "LOW", today, "PENDING", "Marketing"),
    ]
    cursor.executemany("INSERT INTO daily_tasks (tenant_id, title, priority, due_date, status, assigned_to) VALUES (?, ?, ?, ?, ?, ?)", tasks)

    # 6. Expenses per Tenant
    expenses = [
        # Acme Electronics
        ("acme-electronics", today, "Inventory", "Restock component packaging & anti-static bubble wrap", 145.50, "CREDIT_CARD"),
        ("acme-electronics", today, "Software", "G Suite & Cloud Server hosting", 85.00, "BANK_TRANSFER"),
        ("acme-electronics", yesterday, "Shipping", "FedEx Express priority shipping batch", 120.00, "CREDIT_CARD"),

        # BeanCrafters Cafe
        ("beancrafters-cafe", today, "Supplies", "Organic whole milk & oat milk delivery (50L)", 95.00, "CREDIT_CARD"),
        ("beancrafters-cafe", today, "Inventory", "Biodegradable take-out cups & lids (1000ct)", 160.00, "BANK_TRANSFER"),
        ("beancrafters-cafe", yesterday, "Maintenance", "Espresso machine water filter replacement", 75.00, "CREDIT_CARD"),

        # Nova Apparel
        ("nova-apparel", today, "Marketing", "Instagram / TikTok influencer ad placement", 250.00, "CREDIT_CARD"),
        ("nova-apparel", today, "Supplies", "Custom branded tissue paper & mailer polybags", 110.00, "CREDIT_CARD"),
        ("nova-apparel", yesterday, "Logistics", "Local courier deliveries", 65.00, "CREDIT_CARD"),
    ]
    cursor.executemany("INSERT INTO expenses (tenant_id, date, category, description, amount, payment_method) VALUES (?, ?, ?, ?, ?, ?)", expenses)

    # 7. Employee Shifts per Tenant
    shifts = [
        # Acme Electronics
        ("acme-electronics", "Alice Cooper", "Support Lead", today, "09:00", "17:00", "SCHEDULED", 3, 2),
        ("acme-electronics", "Bob Martinez", "Warehouse Tech", today, "08:00", "16:00", "SCHEDULED", 4, 3),

        # BeanCrafters Cafe
        ("beancrafters-cafe", "Clara Oswald", "Head Barista", today, "06:30", "14:30", "SCHEDULED", 5, 4),
        ("beancrafters-cafe", "Dan Lewis", "Roaster Assistant", today, "08:00", "16:00", "SCHEDULED", 3, 2),

        # Nova Apparel
        ("nova-apparel", "Emma Watson", "Store Manager", today, "10:00", "18:00", "SCHEDULED", 4, 3),
        ("nova-apparel", "Frank Wright", "Inventory Specialist", today, "09:00", "17:00", "SCHEDULED", 3, 1),
    ]
    cursor.executemany("INSERT INTO employee_shifts (tenant_id, employee_name, role, shift_date, start_time, end_time, status, tasks_assigned, tasks_completed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", shifts)

    # 8. Customer Reviews per Tenant
    reviews = [
        # Acme Electronics
        ("acme-electronics", today, "Marcus Brody", 5, "POSITIVE", "The mechanical keyboard arrived within 24 hours. Phenomenal tactile switch quality!", "Google Reviews"),
        ("acme-electronics", today, "Sarah Jenkins", 4, "POSITIVE", "Headset audio is crystal clear. Setup was effortless.", "Shopify"),
        ("acme-electronics", yesterday, "Tech Enthusiast", 2, "NEGATIVE", "USB hub runs slightly warm under heavy multi-monitor load.", "Amazon"),

        # BeanCrafters Cafe
        ("beancrafters-cafe", today, "Liam Neeson", 5, "POSITIVE", "The Ethiopian Yirgacheffe pour-over is floral and rich. Best roaster in town.", "Google Reviews"),
        ("beancrafters-cafe", today, "Sophie Turner", 5, "POSITIVE", "Fresh beans and super friendly staff. My morning go-to spot.", "Yelp"),

        # Nova Apparel
        ("nova-apparel", today, "Oliver Queen", 5, "POSITIVE", "Oversized hoodie is heavyweight, soft, and fits true to size.", "Shopify"),
        ("nova-apparel", yesterday, "Rachel Green", 3, "NEUTRAL", "Cap style is great, but shipping took 4 days instead of 2.", "Google Reviews"),
    ]
    cursor.executemany("INSERT INTO customer_reviews (tenant_id, review_date, customer_name, rating, sentiment, feedback_text, source) VALUES (?, ?, ?, ?, ?, ?, ?)", reviews)

    # 9. Seed Users
    users = [
        ("usr-001", "acme-electronics", "owner@acme.com", hash_password("acme123"), "Alex Mercer", "OWNER", now_iso),
        ("usr-002", "beancrafters-cafe", "roaster@beancrafters.com", hash_password("coffee123"), "Elena Rostova", "OWNER", now_iso),
        ("usr-003", "nova-apparel", "manager@nova.com", hash_password("nova123"), "Marcus Vance", "MANAGER", now_iso),
        ("usr-004", "acme-electronics", "amod@solution4u.com", hash_password("mypassword123"), "Amod", "OWNER", now_iso),
    ]
    cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", users)

    # 10. Audit Logs
    cursor.execute(
        "INSERT INTO audit_logs (tenant_id, action, details, created_at) VALUES (?, ?, ?, ?)",
        ("acme-electronics", "SYSTEM_INIT", "Multi-tenant database initialized with sample business data", now_iso)
    )


# ---------------- Neon PostgreSQL Cloud Database Bridge ---------------- #

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_Oo5qGZlQtLT9@ep-young-haze-ae82sn7j-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

def get_postgres_connection():
    """Returns an active connection to Neon PostgreSQL cloud database."""
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        return conn
    except Exception:
        return None


# ---------------- Authentication & Security Helpers ---------------- #

def hash_password(password: str) -> str:
    import hashlib
    # Standard SHA-256 with static application salt for secure zero-dependency hashing
    salt = "aero_productivity_salt_2026"
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def register_user(tenant_id: str, email: str, password: str, full_name: str, role: str = "OWNER") -> Dict[str, Any]:
    """Registers a new user tied to a tenant across Neon PostgreSQL and SQLite."""
    import secrets
    email_clean = email.strip().lower()
    now_iso = datetime.datetime.now().isoformat()
    expires_at = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
    pwd_hash = hash_password(password)
    user_id = f"usr-{secrets.token_hex(4)}"
    token = secrets.token_urlsafe(32)

    # 1. Write to Neon PostgreSQL if connected
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = pg_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM users WHERE LOWER(email) = %s", (email_clean,))
            if cur.fetchone():
                pg_conn.close()
                return {"success": False, "error": f"Email '{email_clean}' is already registered."}
            cur.execute(
                "INSERT INTO users (user_id, tenant_id, email, password_hash, full_name, role, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (user_id, tenant_id, email_clean, pwd_hash, full_name.strip(), role.upper(), now_iso)
            )
            cur.execute(
                "INSERT INTO auth_tokens (token, user_id, tenant_id, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)",
                (token, user_id, tenant_id, now_iso, expires_at)
            )
            pg_conn.close()
        except Exception as e:
            print(f"[Database] Postgres register sync error: {e}")

    # 2. Sync to local SQLite
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email_clean,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, tenant_id, email_clean, pwd_hash, full_name.strip(), role.upper(), now_iso)
        )
        cursor.execute("INSERT INTO auth_tokens VALUES (?, ?, ?, ?, ?)", (token, user_id, tenant_id, now_iso, expires_at))
        conn.commit()
    conn.close()

    return {
        "success": True,
        "token": token,
        "user": {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email_clean,
            "full_name": full_name,
            "role": role.upper()
        }
    }


def authenticate_user(email: str, password: str) -> Dict[str, Any]:
    """Validates user credentials and issues a session auth token across Neon PostgreSQL and SQLite."""
    import secrets
    email_clean = email.strip().lower()
    pwd_hash = hash_password(password)
    now_iso = datetime.datetime.now().isoformat()
    expires_at = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
    token = secrets.token_urlsafe(32)

    # 1. Try Neon PostgreSQL First (Global across all Vercel Lambdas)
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = pg_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM users WHERE LOWER(email) = %s AND password_hash = %s", (email_clean, pwd_hash))
            user = cur.fetchone()
            if user:
                user_dict = dict(user)
                cur.execute(
                    "INSERT INTO auth_tokens (token, user_id, tenant_id, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)",
                    (token, user_dict["user_id"], user_dict["tenant_id"], now_iso, expires_at)
                )
                pg_conn.close()
                return {
                    "success": True,
                    "token": token,
                    "user": {
                        "user_id": user_dict["user_id"],
                        "tenant_id": user_dict["tenant_id"],
                        "email": user_dict["email"],
                        "full_name": user_dict["full_name"],
                        "role": user_dict["role"]
                    }
                }
            pg_conn.close()
        except Exception as e:
            print(f"[Database] Postgres auth check error: {e}")

    # 2. Check local SQLite fallback
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE LOWER(email) = ? AND password_hash = ?", (email_clean, pwd_hash))
    user = cursor.fetchone()
    if not user:
        conn.close()
        return {"success": False, "error": "Invalid email or password."}

    user_dict = dict(user)
    cursor.execute("INSERT INTO auth_tokens VALUES (?, ?, ?, ?, ?)", (token, user_dict["user_id"], user_dict["tenant_id"], now_iso, expires_at))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "token": token,
        "user": {
            "user_id": user_dict["user_id"],
            "tenant_id": user_dict["tenant_id"],
            "email": user_dict["email"],
            "full_name": user_dict["full_name"],
            "role": user_dict["role"]
        }
    }


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Resolves an auth token to user session data from Neon PG or SQLite."""
    if not token:
        return None
    
    # 1. Check Neon PG
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = pg_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("""
                SELECT u.user_id, u.tenant_id, u.email, u.full_name, u.role, t.name as tenant_name
                FROM auth_tokens at
                JOIN users u ON at.user_id = u.user_id
                JOIN tenants t ON u.tenant_id = t.tenant_id
                WHERE at.token = %s
            """, (token,))
            row = cur.fetchone()
            pg_conn.close()
            if row:
                return dict(row)
        except Exception:
            pass

    # 2. Check SQLite
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.user_id, u.tenant_id, u.email, u.full_name, u.role, t.name as tenant_name
        FROM auth_tokens at
        JOIN users u ON at.user_id = u.user_id
        JOIN tenants t ON u.tenant_id = t.tenant_id
        WHERE at.token = ?
    """, (token,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def revoke_token(token: str) -> bool:
    """Revokes and removes an active auth session token upon logout."""
    if not token:
        return False
    
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            cur = pg_conn.cursor()
            cur.execute("DELETE FROM auth_tokens WHERE token = %s", (token,))
            pg_conn.close()
        except Exception:
            pass

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()
    return True


def reset_user_password(email: str, new_password: str) -> Dict[str, Any]:
    """Resets the password for a user (or auto-provisions if new) in Neon PG and SQLite."""
    import secrets
    email_clean = email.strip().lower()
    pwd_hash = hash_password(new_password)
    now_iso = datetime.datetime.now().isoformat()
    expires_at = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
    token = secrets.token_urlsafe(32)
    user_id = f"usr-{secrets.token_hex(4)}"
    tenant_id = "acme-electronics"
    full_name = email_clean.split("@")[0].replace(".", " ").title()

    # 1. Update or Auto-Provision in Neon PostgreSQL (Persistent globally)
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = pg_conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM users WHERE LOWER(email) = %s", (email_clean,))
            user = cur.fetchone()
            if user:
                user_dict = dict(user)
                cur.execute("UPDATE users SET password_hash = %s WHERE LOWER(email) = %s", (pwd_hash, email_clean))
                cur.execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_dict["user_id"],))
                cur.execute(
                    "INSERT INTO auth_tokens (token, user_id, tenant_id, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)",
                    (token, user_dict["user_id"], user_dict["tenant_id"], now_iso, expires_at)
                )
                user_id = user_dict["user_id"]
                tenant_id = user_dict["tenant_id"]
                full_name = user_dict["full_name"]
            else:
                cur.execute(
                    "INSERT INTO users (user_id, tenant_id, email, password_hash, full_name, role, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (user_id, tenant_id, email_clean, pwd_hash, full_name, "OWNER", now_iso)
                )
                cur.execute(
                    "INSERT INTO auth_tokens (token, user_id, tenant_id, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)",
                    (token, user_id, tenant_id, now_iso, expires_at)
                )
            pg_conn.close()
        except Exception as e:
            print(f"[Database] Postgres password reset error: {e}")

    # 2. Also update / sync local SQLite
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (email_clean,))
    user = cursor.fetchone()
    if user:
        u_dict = dict(user)
        user_id = u_dict["user_id"]
        tenant_id = u_dict["tenant_id"]
        full_name = u_dict["full_name"]
        cursor.execute("UPDATE users SET password_hash = ? WHERE LOWER(email) = ?", (pwd_hash, email_clean))
        cursor.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
    else:
        cursor.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, tenant_id, email_clean, pwd_hash, full_name, "OWNER", now_iso)
        )
    cursor.execute("INSERT INTO auth_tokens VALUES (?, ?, ?, ?, ?)", (token, user_id, tenant_id, now_iso, expires_at))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "token": token,
        "message": "Password updated successfully. Signed in.",
        "user": {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email_clean,
            "full_name": full_name,
            "role": "OWNER"
        }
    }


# ---------------- Multi-Tenant Helpers ---------------- #

def create_tenant(tenant_id: str, name: str, industry: str = "General Retail", currency: str = "USD") -> Dict[str, Any]:
    """Registers a new business tenant with initial sample inventory."""
    conn = get_db_connection()
    cursor = conn.cursor()
    tid_clean = tenant_id.strip().lower().replace(" ", "-")
    now_iso = datetime.datetime.now().isoformat()

    cursor.execute("SELECT * FROM tenants WHERE tenant_id = ?", (tid_clean,))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "error": f"Tenant '{tid_clean}' already exists."}

    cursor.execute("INSERT INTO tenants VALUES (?, ?, ?, ?, ?)", (tid_clean, name.strip(), industry.strip(), currency, now_iso))
    
    # Add initial starter product for new tenant
    cursor.execute(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tid_clean, "SKU-001", "Starter Flagship Product", "General", 25, 10, 49.99, 20.00, now_iso)
    )

    cursor.execute(
        "INSERT INTO daily_tasks (tenant_id, title, priority, due_date, status, assigned_to) VALUES (?, ?, ?, ?, ?, ?)",
        (tid_clean, "Review initial product catalog & configure restock thresholds", "HIGH", datetime.date.today().isoformat(), "PENDING", "Business Owner")
    )

    cursor.execute(
        "INSERT INTO audit_logs (tenant_id, action, details, created_at) VALUES (?, ?, ?, ?)",
        (tid_clean, "TENANT_CREATED", f"Created tenant {name} ({tid_clean})", now_iso)
    )

    conn.commit()
    conn.close()
    return {"success": True, "tenant_id": tid_clean, "name": name, "industry": industry}


def list_all_tenants() -> List[Dict[str, Any]]:
    return query_all("SELECT * FROM tenants ORDER BY name ASC")


def create_order_with_items(tenant_id: str, customer_name: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Creates an order strictly isolated to a tenant."""
    conn = get_db_connection()
    cursor = conn.cursor()
    today_iso = datetime.date.today().isoformat()
    now_iso = datetime.datetime.now().isoformat()
    
    cursor.execute("SELECT COUNT(*) FROM sales_orders WHERE tenant_id = ?", (tenant_id,))
    count = cursor.fetchone()[0]
    order_id = f"ORD-{5000 + count + 1}"

    total_amount = 0.0
    inserted_items = []

    for item in items:
        sku = item["sku"].strip().upper()
        qty = int(item["quantity"])
        
        cursor.execute("SELECT * FROM products WHERE tenant_id = ? AND sku = ?", (tenant_id, sku))
        prod = cursor.fetchone()
        if not prod:
            conn.close()
            return {"success": False, "error": f"Product SKU '{sku}' not found in your tenant catalog."}
        
        if prod["stock_quantity"] < qty:
            conn.close()
            return {"success": False, "error": f"Insufficient stock for {prod['name']} (Only {prod['stock_quantity']} left)."}

        unit_price = prod["unit_price"]
        subtotal = round(unit_price * qty, 2)
        total_amount += subtotal

        cursor.execute(
            "INSERT INTO order_items (tenant_id, order_id, sku, quantity, unit_price, subtotal) VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, order_id, sku, qty, unit_price, subtotal)
        )

        new_stock = prod["stock_quantity"] - qty
        cursor.execute(
            "UPDATE products SET stock_quantity = ? WHERE tenant_id = ? AND sku = ?",
            (new_stock, tenant_id, sku)
        )

        inserted_items.append({
            "sku": sku,
            "product_name": prod["name"],
            "quantity": qty,
            "unit_price": unit_price,
            "subtotal": subtotal
        })

    total_amount = round(total_amount, 2)
    cursor.execute(
        "INSERT INTO sales_orders VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tenant_id, order_id, today_iso, customer_name, total_amount, "PAID", "PROCESSING")
    )

    cursor.execute(
        "INSERT INTO audit_logs (tenant_id, action, details, created_at) VALUES (?, ?, ?, ?)",
        (tenant_id, "CREATE_ORDER", f"Created order {order_id} for {customer_name} (${total_amount})", now_iso)
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "tenant_id": tenant_id,
        "order_id": order_id,
        "customer_name": customer_name,
        "total_amount": total_amount,
        "items": inserted_items
    }


def _clean_dict_row(row: Any) -> Dict[str, Any]:
    """Cleans DB row dictionary converting Decimal and date types for JSON serialization."""
    from decimal import Decimal
    if not row:
        return {}
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            d[k] = v.isoformat()
    return d


def query_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    # 1. Try Neon PostgreSQL
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = pg_conn.cursor(cursor_factory=RealDictCursor)
            pg_query = query.replace("?", "%s")
            cur.execute(pg_query, params)
            rows = cur.fetchall()
            pg_conn.close()
            return [_clean_dict_row(r) for r in rows]
        except Exception:
            try:
                pg_conn.close()
            except Exception:
                pass

    # 2. SQLite Fallback
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [_clean_dict_row(row) for row in rows]


def query_one(query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    # 1. Try Neon PostgreSQL
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            from psycopg2.extras import RealDictCursor
            cur = pg_conn.cursor(cursor_factory=RealDictCursor)
            pg_query = query.replace("?", "%s")
            cur.execute(pg_query, params)
            row = cur.fetchone()
            pg_conn.close()
            return _clean_dict_row(row) if row else None
        except Exception:
            try:
                pg_conn.close()
            except Exception:
                pass

    # 2. SQLite Fallback
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    row = cursor.fetchone()
    conn.close()
    return _clean_dict_row(row) if row else None


def execute_mutation(query: str, params: tuple = ()) -> int:
    rowcount = 0
    # 1. Try Neon PostgreSQL
    pg_conn = get_postgres_connection()
    if pg_conn:
        try:
            cur = pg_conn.cursor()
            pg_query = query.replace("?", "%s")
            cur.execute(pg_query, params)
            rowcount = cur.rowcount
            pg_conn.close()
        except Exception:
            try:
                pg_conn.close()
            except Exception:
                pass

    # 2. Sync to local SQLite
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        if rowcount <= 0:
            rowcount = cursor.rowcount
        conn.close()
    except Exception:
        pass

    return rowcount
