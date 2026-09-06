"""
Expense Monitoring & P&L Analysis Module.
Enables business owners to log daily operational expenses, track cost categories,
compute Cost of Goods Sold (COGS), Gross Margins, and Net Profit per tenant.
"""

import datetime
from typing import List, Dict, Any, Optional
from database import query_all, query_one, execute_mutation, get_db_connection


class ExpenseTracker:
    """Manages tenant-isolated operational expenses, COGS, and financial analytics."""

    def __init__(self, tenant_id: str = "acme-electronics"):
        self.tenant_id = tenant_id

    def log_expense(
        self,
        category: str,
        description: str,
        amount: float,
        date: Optional[str] = None,
        payment_method: str = "CREDIT_CARD"
    ) -> Dict[str, Any]:
        """Logs an operational expense for the active tenant."""
        expense_date = date or datetime.date.today().isoformat()
        amount_float = round(float(amount), 2)
        category_clean = category.strip().title()

        execute_mutation(
            """
            INSERT INTO expenses (tenant_id, date, category, description, amount, payment_method)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (self.tenant_id, expense_date, category_clean, description.strip(), amount_float, payment_method)
        )

        return {
            "success": True,
            "tenant_id": self.tenant_id,
            "date": expense_date,
            "category": category_clean,
            "description": description.strip(),
            "amount": amount_float,
            "payment_method": payment_method
        }

    def get_expenses(self, date: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists expenses for the tenant, optionally filtered by date and category."""
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM expenses WHERE tenant_id = ?"
        params: List[Any] = [self.tenant_id]

        if date:
            query += " AND date = ?"
            params.append(date)

        if category:
            query += " AND category = ?"
            params.append(category.strip().title())

        query += " ORDER BY date DESC, expense_id DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_financial_summary(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Calculates comprehensive P&L for the tenant:
        Gross Revenue, COGS, Gross Profit, Total OpEx, Net Profit, and Profit Margin (%).
        """
        today_iso = datetime.date.today().isoformat()
        s_date = start_date or today_iso
        e_date = end_date or today_iso

        # 1. Fetch Gross Sales Revenue in range
        sales_query = """
            SELECT COALESCE(SUM(total_amount), 0.0) as total_revenue, COUNT(*) as order_count
            FROM sales_orders
            WHERE tenant_id = ? AND order_date >= ? AND order_date <= ? AND payment_status = 'PAID'
        """
        sales_data = query_one(sales_query, (self.tenant_id, s_date, e_date)) or {"total_revenue": 0.0, "order_count": 0}
        gross_revenue = round(float(sales_data["total_revenue"]), 2)
        order_count = int(sales_data["order_count"])

        # 2. Fetch Cost of Goods Sold (COGS)
        cogs_query = """
            SELECT COALESCE(SUM(oi.quantity * p.cost_price), 0.0) as total_cogs
            FROM order_items oi
            JOIN sales_orders so ON oi.tenant_id = so.tenant_id AND oi.order_id = so.order_id
            JOIN products p ON oi.tenant_id = p.tenant_id AND oi.sku = p.sku
            WHERE oi.tenant_id = ? AND so.order_date >= ? AND so.order_date <= ? AND so.payment_status = 'PAID'
        """
        cogs_data = query_one(cogs_query, (self.tenant_id, s_date, e_date)) or {"total_cogs": 0.0}
        total_cogs = round(float(cogs_data["total_cogs"]), 2)

        # 3. Fetch Operational Expenses by Category
        expense_query = """
            SELECT category, SUM(amount) as category_total
            FROM expenses
            WHERE tenant_id = ? AND date >= ? AND date <= ?
            GROUP BY category
            ORDER BY category_total DESC
        """
        expense_rows = query_all(expense_query, (self.tenant_id, s_date, e_date))
        category_breakdown = {row["category"]: round(row["category_total"], 2) for row in expense_rows}
        total_opex = round(sum(category_breakdown.values()), 2)

        # 4. Compute Financial Metrics
        gross_profit = round(gross_revenue - total_cogs, 2)
        net_profit = round(gross_profit - total_opex, 2)
        gross_margin_pct = round((gross_profit / gross_revenue * 100), 1) if gross_revenue > 0 else 0.0
        net_margin_pct = round((net_profit / gross_revenue * 100), 1) if gross_revenue > 0 else 0.0

        return {
            "tenant_id": self.tenant_id,
            "period": {"start_date": s_date, "end_date": e_date},
            "order_count": order_count,
            "gross_revenue": gross_revenue,
            "cogs": total_cogs,
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin_pct,
            "total_operating_expenses": total_opex,
            "net_profit": net_profit,
            "net_margin_pct": net_margin_pct,
            "expense_categories": category_breakdown
        }
