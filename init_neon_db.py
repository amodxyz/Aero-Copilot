import os
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_Oo5qGZlQtLT9@ep-young-haze-ae82sn7j-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

def init_postgres(force_reseed=True):
    print(f"Connecting to Neon PostgreSQL...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    if force_reseed:
        print("Dropping existing tables if any...")
        tables = [
            "customer_reviews", "employee_shifts", "expenses", "audit_logs",
            "daily_tasks", "order_items", "sales_orders", "products",
            "auth_tokens", "users", "tenants"
        ]
        for t in tables:
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")

    print("Creating tables in Neon PostgreSQL...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            industry VARCHAR(128) NOT NULL,
            currency VARCHAR(16) NOT NULL DEFAULT 'USD',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id VARCHAR(64) PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            full_name VARCHAR(255) NOT NULL,
            role VARCHAR(32) NOT NULL CHECK(role IN ('OWNER', 'MANAGER', 'STAFF')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token VARCHAR(128) PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            sku VARCHAR(64) NOT NULL,
            name VARCHAR(255) NOT NULL,
            category VARCHAR(128) NOT NULL,
            stock_quantity INTEGER NOT NULL DEFAULT 0,
            low_stock_threshold INTEGER NOT NULL DEFAULT 10,
            unit_price NUMERIC(12,2) NOT NULL DEFAULT 0.00,
            cost_price NUMERIC(12,2) NOT NULL DEFAULT 0.00,
            last_restocked_date DATE,
            PRIMARY KEY (tenant_id, sku)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sales_orders (
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            order_id VARCHAR(64) NOT NULL,
            order_date DATE NOT NULL,
            customer_name VARCHAR(255) NOT NULL,
            total_amount NUMERIC(12,2) NOT NULL DEFAULT 0.00,
            payment_status VARCHAR(32) NOT NULL,
            fulfillment_status VARCHAR(32) NOT NULL,
            PRIMARY KEY (tenant_id, order_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            order_id VARCHAR(64) NOT NULL,
            sku VARCHAR(64) NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price NUMERIC(12,2) NOT NULL,
            subtotal NUMERIC(12,2) NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_tasks (
            task_id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            title VARCHAR(512) NOT NULL,
            priority VARCHAR(32) NOT NULL CHECK(priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
            due_date DATE NOT NULL,
            status VARCHAR(32) NOT NULL CHECK(status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED')),
            assigned_to VARCHAR(128) NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            expense_id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            expense_date DATE NOT NULL,
            category VARCHAR(128) NOT NULL,
            description TEXT NOT NULL,
            amount NUMERIC(12,2) NOT NULL,
            payment_method VARCHAR(64) NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS employee_shifts (
            shift_id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            employee_name VARCHAR(128) NOT NULL,
            shift_date DATE NOT NULL,
            start_time VARCHAR(32) NOT NULL,
            end_time VARCHAR(32) NOT NULL,
            role VARCHAR(64) NOT NULL,
            hourly_rate NUMERIC(12,2) NOT NULL,
            status VARCHAR(32) NOT NULL CHECK(status IN ('SCHEDULED', 'COMPLETED', 'ABSENT', 'SWAPPED'))
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customer_reviews (
            review_id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            customer_name VARCHAR(128) NOT NULL,
            rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
            feedback_text TEXT NOT NULL,
            review_date DATE NOT NULL,
            source VARCHAR(64) NOT NULL DEFAULT 'Google Reviews'
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id SERIAL PRIMARY KEY,
            tenant_id VARCHAR(64) NOT NULL,
            action VARCHAR(255) NOT NULL,
            details TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)

    print("Populating multi-tenant seed data into Neon PostgreSQL...")
    today = datetime.date.today().isoformat()
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    now_iso = datetime.datetime.now().isoformat()

    # 1. Tenants
    tenants = [
        ("acme-electronics", "Acme Electronics Corp", "Consumer Electronics", "USD", now_iso),
        ("beancrafters-cafe", "BeanCrafters Coffee Roastery", "Food & Beverage", "USD", now_iso),
        ("nova-apparel", "Nova Urban Apparel", "Fashion & Retail", "USD", now_iso),
    ]
    cur.executemany("INSERT INTO tenants (tenant_id, name, industry, currency, created_at) VALUES (%s, %s, %s, %s, %s)", tenants)

    # 2. Users (SHA-256 hashed passwords)
    import hashlib
    def hash_pwd(p): return hashlib.sha256(p.encode()).hexdigest()

    users = [
        ("usr_acme_1", "acme-electronics", "owner@acme.com", hash_pwd("acme123"), "Alex Mercer", "OWNER", now_iso),
        ("usr_bean_1", "beancrafters-cafe", "manager@beancrafters.com", hash_pwd("bean123"), "Maya Lin", "MANAGER", now_iso),
        ("usr_nova_1", "nova-apparel", "staff@nova.com", hash_pwd("nova123"), "Sam Rivera", "STAFF", now_iso),
    ]
    cur.executemany("INSERT INTO users (user_id, tenant_id, email, password_hash, full_name, role, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)", users)

    # 3. Products
    products = [
        ("acme-electronics", "SKU-101", "Ergonomic Mechanical Keyboard", "Electronics", 8, 15, 129.99, 65.00, yesterday),
        ("acme-electronics", "SKU-102", "Noise-Canceling Wireless Headset", "Electronics", 4, 10, 199.99, 95.00, yesterday),
        ("acme-electronics", "SKU-103", "4K Ultra-HD Monitor Stand", "Accessories", 42, 20, 49.99, 18.50, today),
        ("acme-electronics", "SKU-104", "USB-C Multi-Port Hub (8-in-1)", "Accessories", 3, 12, 59.99, 22.00, yesterday),
        ("acme-electronics", "SKU-105", "Smart LED Desk Lamp w/ Qi Charger", "Smart Home", 18, 15, 79.99, 32.00, today),
        ("beancrafters-cafe", "COF-201", "Single-Origin Ethiopian Yirgacheffe (1kg)", "Coffee Beans", 6, 18, 34.50, 14.00, yesterday),
        ("beancrafters-cafe", "COF-202", "Organic Colombian Dark Roast (1kg)", "Coffee Beans", 2, 20, 29.00, 11.50, yesterday),
        ("beancrafters-cafe", "COF-203", "Ceramic Pour-Over Dripper Set", "Brewing Gear", 35, 15, 42.00, 16.00, today),
        ("beancrafters-cafe", "COF-204", "Artisanal Vanilla Syrup (750ml)", "Syrups", 4, 12, 18.99, 6.50, yesterday),
        ("beancrafters-cafe", "COF-205", "Cold Brew Filter Bags (50-pack)", "Accessories", 50, 15, 15.00, 4.20, today),
        ("nova-apparel", "APP-301", "Heavyweight Oversized Organic Hoodie", "Hoodies", 5, 25, 89.00, 32.00, yesterday),
        ("nova-apparel", "APP-302", "Vintage Washed Boxy Graphic Tee", "T-Shirts", 3, 20, 38.00, 12.00, yesterday),
        ("nova-apparel", "APP-303", "Minimalist Corduroy Cap", "Headwear", 60, 20, 28.00, 8.50, today),
        ("nova-apparel", "APP-304", "Recycled Canvas Everyday Tote Bag", "Accessories", 45, 15, 24.50, 7.00, today),
    ]
    cur.executemany("INSERT INTO products (tenant_id, sku, name, category, stock_quantity, low_stock_threshold, unit_price, cost_price, last_restocked_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", products)

    # 4. Sales Orders
    orders = [
        ("acme-electronics", "ORD-5001", today, "Acme Solutions Corp", 519.96, "PAID", "DELIVERED"),
        ("acme-electronics", "ORD-5002", today, "TechNova Labs", 389.97, "PAID", "PROCESSING"),
        ("acme-electronics", "ORD-5003", today, "David Chen", 179.98, "PAID", "SHIPPED"),
        ("beancrafters-cafe", "COF-9001", today, "The Daily Grind Espresso Bar", 690.00, "PAID", "DELIVERED"),
        ("beancrafters-cafe", "COF-9002", today, "Blue Sky Bakery & Cafe", 232.00, "PAID", "PROCESSING"),
        ("beancrafters-cafe", "COF-9003", today, "Emma Watson", 53.49, "PAID", "SHIPPED"),
        ("nova-apparel", "APP-7001", today, "Urban Trend Boutique", 890.00, "PAID", "DELIVERED"),
        ("nova-apparel", "APP-7002", today, "Liam Miller", 127.00, "PAID", "PROCESSING"),
    ]
    cur.executemany("INSERT INTO sales_orders (tenant_id, order_id, order_date, customer_name, total_amount, payment_status, fulfillment_status) VALUES (%s, %s, %s, %s, %s, %s, %s)", orders)

    # 5. Order Items
    order_items = [
        ("acme-electronics", "ORD-5001", "SKU-101", 4, 129.99, 519.96),
        ("acme-electronics", "ORD-5002", "SKU-102", 1, 199.99, 199.99),
        ("acme-electronics", "ORD-5002", "SKU-104", 1, 59.99, 59.99),
        ("acme-electronics", "ORD-5002", "SKU-101", 1, 129.99, 129.99),
        ("acme-electronics", "ORD-5003", "SKU-104", 3, 59.99, 179.97),
        ("beancrafters-cafe", "COF-9001", "COF-201", 20, 34.50, 690.00),
        ("beancrafters-cafe", "COF-9002", "COF-202", 8, 29.00, 232.00),
        ("beancrafters-cafe", "COF-9003", "COF-201", 1, 34.50, 34.50),
        ("beancrafters-cafe", "COF-9003", "COF-204", 1, 18.99, 18.99),
        ("nova-apparel", "APP-7001", "APP-301", 10, 89.00, 890.00),
        ("nova-apparel", "APP-7002", "APP-301", 1, 89.00, 89.00),
        ("nova-apparel", "APP-7002", "APP-302", 1, 38.00, 38.00),
    ]
    cur.executemany("INSERT INTO order_items (tenant_id, order_id, sku, quantity, unit_price, subtotal) VALUES (%s, %s, %s, %s, %s, %s)", order_items)

    # 6. Tasks
    tasks = [
        ("acme-electronics", "Authorize PO for Keyboards (SKU-101) & Multi-Port Hubs", "CRITICAL", today, "PENDING", "Business Owner"),
        ("acme-electronics", "Verify packing slips for ORD-5002 batch", "MEDIUM", today, "PENDING", "Fulfillment Ops"),
        ("beancrafters-cafe", "Order green coffee shipment for Colombian Dark Roast", "CRITICAL", today, "PENDING", "Head Roaster"),
        ("beancrafters-cafe", "Calibrate commercial batch roaster temperature sensors", "HIGH", today, "IN_PROGRESS", "Maintenance"),
        ("nova-apparel", "Confirm autumn restock delivery with knitwear manufacturer", "CRITICAL", today, "PENDING", "Production Lead"),
        ("nova-apparel", "Update lookbook photography for corduroy caps", "LOW", today, "PENDING", "Marketing"),
    ]
    cur.executemany("INSERT INTO daily_tasks (tenant_id, title, priority, due_date, status, assigned_to) VALUES (%s, %s, %s, %s, %s, %s)", tasks)

    # 7. Expenses
    expenses = [
        ("acme-electronics", today, "Inventory", "Restock component packaging & anti-static bubble wrap", 145.50, "CREDIT_CARD"),
        ("acme-electronics", today, "Software", "G Suite & Cloud Server hosting", 85.00, "BANK_TRANSFER"),
        ("acme-electronics", yesterday, "Shipping", "FedEx Express priority freight batch", 320.00, "CREDIT_CARD"),
        ("beancrafters-cafe", today, "Supplies", "Oat milk & almond milk wholesale carton pallet", 280.00, "BANK_TRANSFER"),
        ("beancrafters-cafe", today, "Maintenance", "Espresso machine head group gasket replacement", 95.00, "CASH"),
        ("beancrafters-cafe", yesterday, "Marketing", "Instagram local neighborhood coffee boost campaign", 50.00, "CREDIT_CARD"),
        ("nova-apparel", today, "Packaging", "Biodegradable mailing satchels & branded tissue", 180.00, "CREDIT_CARD"),
        ("nova-apparel", today, "Production", "Screen printing inks & embroidery thread spool", 240.00, "BANK_TRANSFER"),
        ("nova-apparel", yesterday, "Utilities", "Showroom boutique electricity & high-speed WiFi", 195.00, "BANK_TRANSFER"),
    ]
    cur.executemany("INSERT INTO expenses (tenant_id, expense_date, category, description, amount, payment_method) VALUES (%s, %s, %s, %s, %s, %s)", expenses)

    # 8. Employee Shifts
    shifts = [
        ("acme-electronics", "Liam Vance", today, "08:00", "16:30", "Inventory Lead", 24.50, "SCHEDULED"),
        ("acme-electronics", "Chloe Bennett", today, "10:00", "18:00", "QA Technician", 22.00, "SCHEDULED"),
        ("beancrafters-cafe", "Marcus Aurel", today, "06:00", "14:00", "Head Barista", 21.00, "COMPLETED"),
        ("beancrafters-cafe", "Sofia Gomez", today, "12:00", "20:00", "Barista & Register", 18.50, "SCHEDULED"),
        ("nova-apparel", "Kai Tanaka", today, "09:30", "18:00", "Store Associate", 19.50, "SCHEDULED"),
        ("nova-apparel", "Elena Rostova", today, "11:00", "19:30", "Visual Merchandiser", 23.00, "SCHEDULED"),
    ]
    cur.executemany("INSERT INTO employee_shifts (tenant_id, employee_name, shift_date, start_time, end_time, role, hourly_rate, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", shifts)

    # 9. Customer Reviews
    reviews = [
        ("acme-electronics", "David K.", 5, "Fastest shipping ever! The mechanical keyboard has amazing tactile switches.", today, "Google Reviews"),
        ("acme-electronics", "Rachel W.", 4, "Noise cancellation on the headset is great, but earmuffs get warm after 4 hours.", yesterday, "Trustpilot"),
        ("beancrafters-cafe", "Jason M.", 5, "Best Ethiopian pour-over in the city. Incredible floral notes and friendly staff!", today, "Google Reviews"),
        ("beancrafters-cafe", "Claire B.", 2, "Coffee was lukewarm and waited 15 mins during morning rush.", today, "Yelp"),
        ("beancrafters-cafe", "Tom H.", 5, "Obsessed with their cold brew beans. Reordering every 2 weeks!", yesterday, "Google Reviews"),
        ("nova-apparel", "Zoe P.", 5, "The heavyweight hoodie quality is unreal. Thick, super comfortable.", today, "Shopify Reviews"),
        ("nova-apparel", "Lucas S.", 4, "Great fit on the corduroy cap, color slightly darker than pictured.", yesterday, "Instagram Direct"),
    ]
    cur.executemany("INSERT INTO customer_reviews (tenant_id, customer_name, rating, feedback_text, review_date, source) VALUES (%s, %s, %s, %s, %s, %s)", reviews)

    # 10. Audit log
    cur.execute("INSERT INTO audit_logs (tenant_id, action, details) VALUES (%s, %s, %s)", (
        "system", "DATABASE_INITIALIZATION", "Neon PostgreSQL multi-tenant database initialized and seeded successfully."
    ))

    # Verify counts
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
    tables = [r[0] for r in cur.fetchall()]
    print(f"\nCreated {len(tables)} tables in Neon PostgreSQL:")
    for t in sorted(tables):
        cur.execute(f"SELECT COUNT(*) FROM {t};")
        cnt = cur.fetchone()[0]
        print(f"  ? {t}: {cnt} records")

    cur.close()
    conn.close()
    print("\n Neon PostgreSQL Database Ready!")

if __name__ == '__main__':
    init_postgres(force_reseed=True)
