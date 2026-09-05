"""
Multi-Tenant Productivity Agent Core Engine.
Integrates Gemini LLM with tenant-scoped tool calling, and local rule fallback.
"""

import os
import json
import re
import datetime
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

from tools import (
    get_daily_sales_summary,
    get_inventory_alerts,
    reorder_inventory,
    search_products,
    list_daily_tasks,
    create_operational_task,
    generate_daily_briefing,
    forecast_sales_demand,
    analyze_customer_feedback,
    trigger_operational_webhook_alert,
    create_sales_order,
    update_task_status,
    add_new_product,
    AGENT_TOOLS_REGISTRY,
    DEFAULT_TENANT
)

load_dotenv()

SYSTEM_INSTRUCTION = """
You are 'Aero', an executive AI Personal Productivity Assistant deployed on Cloud Run to manage daily operations for business owners across multiple tenants.
You assist with:
1. Daily sales performance tracking, order summaries, and top-selling revenue metrics.
2. Real-time inventory monitoring, identifying low-stock alerts, and placing restock orders.
3. Generating daily morning operational briefings.
4. Managing operational tasks and action items.
5. Creating customer sales orders and updating stock in real time.
6. Forecasting 7-day and 30-day sales demand and stockout risks.
7. Analyzing customer feedback and dispatching webhook notifications.

Response Formatting Guidelines:
- Always format outputs with clean, executive-grade visual hierarchy.
- For Demand Forecasting & Velocity:
  Group items by Risk Tier:
  🔴 **CRITICAL STOCKOUT RISK (< 7 Days of Supply)**: Include Current Stock, Daily Burn, Stockout In, and Recommended Restock quantity with Estimated Cost.
  🟡 **MEDIUM WATCHLIST (7 - 14 Days of Supply)**
  🟢 **STABLE & HEALTHY INVENTORY (> 14 Days of Supply)**
  Always conclude with proactive Suggested Next Actions.
- For Low Stock Alerts: Highlight units remaining, safety threshold, and 1-click reorder recommendation.
- Always scope all actions and queries strictly to the active tenant.
"""


def format_forecast_reply(forecast_data: Dict[str, Any], tenant_id: str) -> str:
    forecasts = forecast_data.get("forecasts", [])
    if not forecasts:
        return f"📈 **Demand Forecast [{tenant_id}]:** No active catalog products found for forecasting."

    high_risk = [f for f in forecasts if f.get("stockout_risk") == "HIGH"]
    medium_risk = [f for f in forecasts if f.get("stockout_risk") == "MEDIUM"]
    stable = [f for f in forecasts if f.get("stockout_risk") == "LOW"]

    lines = [
        f"📈 **Demand Velocity & Stockout Risk Forecast [{tenant_id}]**",
        "*Calculated from live POS telemetry (Stripe/Square/Shopify) & inventory safety buffers:*\n"
    ]

    if high_risk:
        lines.append("🔴 **CRITICAL STOCKOUT RISK (< 7 Days of Supply):**")
        for f in high_risk:
            days_val = f.get("days_until_stockout", 0)
            days_str = f"~{days_val} day{'s' if days_val != 1 else ''}"
            rec_units = f.get("recommended_reorder_units") or max(20, f.get("threshold", 10) * 2)
            est_cost = f.get("estimated_reorder_cost", 0.0)
            cost_str = f" *(Est. ${est_cost:.2f})*" if est_cost > 0 else ""
            lines.append(
                f"• 🚨 **{f['name']}** (`{f['sku']}`)\n"
                f"   ↳ **Stock:** `{f['current_stock']} units` | **Velocity:** `~{f['daily_velocity']} units/day` | **Stockout In:** **{days_str}**\n"
                f"   ↳ ⚡ *Recommended Restock:* **`{rec_units} units`**{cost_str}"
            )
        lines.append("")

    if medium_risk:
        lines.append("🟡 **MEDIUM WATCHLIST (7 - 14 Days of Supply):**")
        for f in medium_risk:
            lines.append(
                f"• ⚠️ **{f['name']}** (`{f['sku']}`): **{f['current_stock']} units** (~{f['daily_velocity']}/day • stockout in ~{f['days_until_stockout']} days)"
            )
        lines.append("")

    if stable:
        lines.append("🟢 **STABLE & HEALTHY INVENTORY (> 14 Days of Supply):**")
        for f in stable:
            lines.append(
                f"• ✅ **{f['name']}** (`{f['sku']}`): **{f['current_stock']} units** in stock (~{f['daily_velocity']}/day • buffer for ~{f['days_until_stockout']} days)"
            )
        lines.append("")

    if high_risk:
        top_rec = high_risk[0]
        top_sku = top_rec.get("sku", "SKU-104")
        top_qty = top_rec.get("recommended_reorder_units", 30)
        lines.append(
            f"💡 **Suggested Next Action:**\n"
            f"• Reply `Reorder {top_qty} units of {top_sku}` to trigger instant replenishment purchase order.\n"
            f"• Reply `Send morning digest to Slack` to broadcast this risk alert to your team."
        )

    return "\n".join(lines)


def format_inventory_alerts_reply(inv: Dict[str, Any], tenant_id: str) -> str:
    if inv["low_stock_count"] == 0:
        return f"✅ **Inventory Health [{tenant_id}]:** All products are above safe threshold levels."

    lines = [
        f"⚠️ **Low Stock Alert [{tenant_id}]: {inv['low_stock_count']} item(s) require replenishment**",
        "*Safety threshold analysis against active catalog buffer levels:*\n"
    ]
    for item in inv["critical_alerts"]:
        rec = item.get("recommended_reorder", 25)
        cost = item.get("estimated_reorder_cost", 0.0)
        cost_str = f" *(Est. ${cost:.2f})*" if cost > 0 else ""
        lines.append(
            f"• 🚨 **{item['name']}** (`{item['sku']}`)\n"
            f"   ↳ **Current Stock:** `{item['current_stock']} units` (Safety Min: `{item['threshold']}`)\n"
            f"   ↳ ⚡ *Recommended Reorder:* **`{rec} units`**{cost_str}"
        )

    top = inv["critical_alerts"][0]
    lines.append(f"\n💡 **Quick Action:** Reply `Reorder {top['recommended_reorder']} units of {top['sku']}` to auto-order now.")
    return "\n".join(lines)


def format_daily_sales_reply(sales: Dict[str, Any], tenant_id: str) -> str:
    lines = [
        f"💰 **Daily Sales Report [{tenant_id}] ({sales['date']})**",
        f"• **Gross Revenue:** **${sales['total_revenue']:.2f}**",
        f"• **Orders Processed:** **{sales['total_orders']} transactions**",
        f"• **Average Order Value (AOV):** **${sales['average_order_value']:.2f}**\n"
    ]
    if sales.get("top_selling_products"):
        lines.append("🏆 **Top Performing Products Today:**")
        for item in sales["top_selling_products"]:
            lines.append(f"• `{item['sku']}` **{item['name']}**: **{item['units_sold']} units** (${item['total_revenue']:.2f})")
    return "\n".join(lines)


def format_daily_briefing_reply(brief: Dict[str, Any], tenant_id: str) -> str:
    sales = brief["sales_summary"]
    inv = brief["inventory_status"]
    tasks = brief["pending_tasks"]
    return (
        f"🌅 **Executive Morning Briefing [{tenant_id}] ({brief['briefing_date']})**\n\n"
        f"📊 **Financial Performance:** Gross Revenue **${sales['total_revenue']:.2f}** across **{sales['total_orders']} orders** (AOV: ${sales['average_order_value']:.2f})\n"
        f"⚠️ **Inventory Telemetry:** **{inv['low_stock_count']} item(s)** below safety thresholds requiring restock.\n"
        f"📋 **Action Items Queue:** **{tasks['total_tasks']} task(s)** pending fulfillment today.\n\n"
        f"💡 *Tip: Reply '3' to view demand forecast velocity or '4' to auto-replenish low stock.*"
    )


class ProductivityAgent:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.client = None
        self._init_gemini_client()

    def _init_gemini_client(self):
        if self.api_key:
            try:
                from google import genai
                from google.genai import types
                self.client = genai.Client(api_key=self.api_key)
                self.types = types
            except Exception as e:
                print(f"[Agent] Failed to initialize Google GenAI SDK: {e}. Falling back to rule-based engine.")
                self.client = None

    def process_message(self, user_message: str, chat_history: Optional[List[Dict[str, Any]]] = None, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
        try:
            if not user_message or not user_message.strip():
                return self._process_with_rule_engine(user_message, tenant_id)

            if self.client:
                try:
                    return self._process_with_gemini(user_message, chat_history, tenant_id)
                except Exception as e:
                    print(f"[Agent] Gemini error: {e}. Falling back to rule engine.")

            return self._process_with_rule_engine(user_message, tenant_id)
        except Exception as err:
            print(f"[Agent] Fatal process error: {err}")
            return self._process_with_rule_engine(user_message, tenant_id)

    def _process_with_gemini(self, user_message: str, chat_history: Optional[List[Dict[str, str]]], tenant_id: str) -> Dict[str, Any]:
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        
        # Tools definitions
        tools_list = [
            get_daily_sales_summary,
            get_inventory_alerts,
            reorder_inventory,
            search_products,
            list_daily_tasks,
            create_operational_task,
            generate_daily_briefing,
            forecast_sales_demand,
            analyze_customer_feedback,
            trigger_operational_webhook_alert,
            create_sales_order,
            update_task_status,
            add_new_product,
        ]

        system_with_tenant = f"{SYSTEM_INSTRUCTION}\nActive Business Tenant: [{tenant_id}]. Always include the tenant tag [{tenant_id}] in the report header."
        config = self.types.GenerateContentConfig(
            system_instruction=system_with_tenant,
            temperature=0.2,
            tools=tools_list,
        )

        response = self.client.models.generate_content(
            model=model_name,
            contents=f"[{tenant_id}] {user_message}",
            config=config,
        )

        tool_calls_executed = []
        if response.function_calls:
            for function_call in response.function_calls:
                fn_name = function_call.name
                fn_args = dict(function_call.args) if function_call.args else {}
                fn_args["tenant_id"] = tenant_id
                
                if fn_name in AGENT_TOOLS_REGISTRY:
                    tool_fn = AGENT_TOOLS_REGISTRY[fn_name]
                    tool_result = tool_fn(**fn_args)
                    tool_calls_executed.append({
                        "tool": fn_name,
                        "args": fn_args,
                        "result": tool_result
                    })

            tool_outputs_text = json.dumps([tc["result"] for tc in tool_calls_executed])
            summary_prompt = f"User asked: {user_message}\n\nTool execution results for tenant [{tenant_id}]:\n{tool_outputs_text}\n\nProvide an executive summary and include the header [{tenant_id}]."
            
            summary_response = self.client.models.generate_content(
                model=model_name,
                contents=summary_prompt,
                config=self.types.GenerateContentConfig(
                    system_instruction=system_with_tenant,
                    temperature=0.3
                )
            )
            final_text = summary_response.text
        else:
            final_text = response.text or "I processed your request, but have no additional details."

        return {
            "tenant_id": tenant_id,
            "reply": final_text,
            "tool_calls": tool_calls_executed,
            "engine": "gemini-cloud",
            "timestamp": datetime.datetime.now().isoformat()
        }

    def _process_with_rule_engine(self, user_message: str, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
        msg = (user_message or "").strip().lower()
        clean_msg = re.sub(r"[^\w\s\-]", "", msg).strip()
        tool_calls_executed = []
        reply = ""

        # 1. Numbered Menu Selections
        if clean_msg in ("1", "option 1", "opt 1") or clean_msg.startswith("1 "):
            sales = get_daily_sales_summary(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "get_daily_sales_summary", "args": {"tenant_id": tenant_id}, "result": sales})
            reply = format_daily_sales_reply(sales, tenant_id)

        elif clean_msg in ("2", "option 2", "opt 2") or clean_msg.startswith("2 "):
            inv = get_inventory_alerts(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "get_inventory_alerts", "args": {"tenant_id": tenant_id}, "result": inv})
            reply = format_inventory_alerts_reply(inv, tenant_id)

        elif clean_msg in ("3", "option 3", "opt 3") or clean_msg.startswith("3 "):
            forecast_data = forecast_sales_demand(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "forecast_sales_demand", "args": {"tenant_id": tenant_id}, "result": forecast_data})
            reply = format_forecast_reply(forecast_data, tenant_id)

        elif clean_msg in ("4", "option 4", "opt 4") or clean_msg.startswith("4 "):
            inv = get_inventory_alerts(tenant_id=tenant_id)
            if inv["critical_alerts"]:
                top_item = inv["critical_alerts"][0]
                res = reorder_inventory(sku=top_item["sku"], quantity=top_item["recommended_reorder"], tenant_id=tenant_id)
                tool_calls_executed.append({"tool": "reorder_inventory", "args": {"sku": top_item["sku"], "quantity": top_item["recommended_reorder"], "tenant_id": tenant_id}, "result": res})
                reply = f"✅ **Purchase Order Executed [{tenant_id}]:** Reordered **{res['units_ordered']} units** of **{res['product_name']}** (`{res['sku']}`). New Stock: **{res['new_stock']} units** (${res['total_cost']:.2f})."
            else:
                reply = "Please specify SKU to reorder (e.g. `Reorder 25 units of SKU-101`)."

        elif clean_msg in ("5", "option 5", "opt 5") or clean_msg.startswith("5 "):
            brief = generate_daily_briefing(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "generate_daily_briefing", "args": {"tenant_id": tenant_id}, "result": brief})
            reply = format_daily_briefing_reply(brief, tenant_id)

        elif clean_msg in ("6", "option 6", "opt 6") or clean_msg.startswith("6 "):
            feedback_data = analyze_customer_feedback(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "analyze_customer_feedback", "args": {"tenant_id": tenant_id}, "result": feedback_data})
            reply = f"⭐ **Customer Sentiment & Feedback [{tenant_id}]:** Rating **{feedback_data['average_rating']}/5.0** ({feedback_data['satisfaction_rate']} positive satisfaction).\nSummary: {feedback_data.get('summary', 'Strong customer fulfillment ratings.')}"

        elif clean_msg in ("7", "option 7", "opt 7") or clean_msg.startswith("7 "):
            webhook_res = trigger_operational_webhook_alert(channel="slack", tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "trigger_operational_webhook_alert", "args": {"channel": "slack", "tenant_id": tenant_id}, "result": webhook_res})
            reply = f"🚀 **Webhook Dispatched [{tenant_id}]:** Alert sent to **#slack**."

        # 2. Demand Forecasting & Velocity (High priority keyword match)
        elif any(k in msg for k in ["forecast", "demand", "velocity", "stockout risk", "predict", "future sales"]):
            forecast_data = forecast_sales_demand(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "forecast_sales_demand", "args": {"tenant_id": tenant_id}, "result": forecast_data})
            reply = format_forecast_reply(forecast_data, tenant_id)

        # 3. Customer Reviews & Feedback
        elif any(k in msg for k in ["review", "feedback", "rating", "satisfaction", "sentiment", "customer sentiment"]):
            feedback_data = analyze_customer_feedback(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "analyze_customer_feedback", "args": {"tenant_id": tenant_id}, "result": feedback_data})
            reply = f"⭐ **Customer Sentiment & Feedback [{tenant_id}]:** Rating **{feedback_data['average_rating']}/5.0** ({feedback_data['satisfaction_rate']} positive satisfaction).\nSummary: {feedback_data.get('summary', 'Strong customer fulfillment ratings.')}"

        # 4. Webhook Dispatch & Slack Alerts
        elif any(k in msg for k in ["webhook", "slack", "dispatch", "send alert", "notify slack"]):
            channel = "slack"
            webhook_res = trigger_operational_webhook_alert(channel=channel, message=user_message, tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "trigger_operational_webhook_alert", "args": {"channel": channel, "tenant_id": tenant_id}, "result": webhook_res})
            reply = f"🚀 **Webhook Dispatched [{tenant_id}]:** Operational alert sent to **#{channel}**."

        # 5. Create / Record New Order
        elif any(k in msg for k in ["create order", "new order", "record order", "record sale", "buying", "buys", "place order"]):
            sku_match = re.search(r"([A-Za-z]+-\d+)", user_message)
            sku = sku_match.group(1).upper() if sku_match else "SKU-101"
            nums = re.findall(r"\b\d+\b", user_message)
            qty = 1
            if nums:
                sku_num = sku.split("-")[-1]
                other_nums = [int(n) for n in nums if n != sku_num]
                if other_nums:
                    qty = other_nums[0]
            
            cust_match = re.search(r"(?:for|from|client)\s+([A-Za-z0-9\s]+?)(?:\s+buying|\s+buying|\s+for|\.|$)", user_message, re.IGNORECASE)
            customer = cust_match.group(1).strip() if cust_match else "Client"

            order_res = create_sales_order(customer_name=customer, sku=sku, quantity=qty, tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "create_sales_order", "args": {"customer_name": customer, "sku": sku, "quantity": qty, "tenant_id": tenant_id}, "result": order_res})
            if order_res.get("success"):
                reply = f"🎉 **Order Created [{tenant_id}]:** `{order_res['order_id']}` for **{order_res['customer_name']}** ({qty}x {sku}) totaling **${order_res['total_amount']:.2f}**."
            else:
                reply = f"❌ **Order Failed:** {order_res.get('error', 'Error creating order')}"

        # 6. Add / Register New Product
        elif any(k in msg for k in ["add product", "create product", "new product", "register product"]):
            sku_match = re.search(r"([A-Za-z]+-\d+)", user_message)
            sku = sku_match.group(1).upper() if sku_match else f"SKU-{datetime.datetime.now().strftime('%M%S')}"
            
            # Extract product name
            name_match = re.search(r"(?:product|named|name)\s+([A-Za-z0-9\s\-]+?)(?:\s+with|\s+category|\s+stock|\s+price|\.|$)", user_message, re.IGNORECASE)
            name = name_match.group(1).strip() if name_match else f"Product {sku}"
            if name.upper() == sku:
                name = f"Item {sku}"

            res = add_new_product(
                sku=sku,
                name=name,
                category="General",
                stock_quantity=25,
                low_stock_threshold=10,
                unit_price=49.99,
                cost_price=20.00,
                tenant_id=tenant_id
            )
            tool_calls_executed.append({"tool": "add_new_product", "args": {"sku": sku, "name": name, "tenant_id": tenant_id}, "result": res})
            if res.get("success"):
                reply = f"📦 **Product Registered [{tenant_id}]:** Added **{name}** (`{sku}`) with 25 initial units @ ${49.99:.2f}."
            else:
                reply = f"❌ **Product Registration Failed:** {res.get('error', 'Error adding product')}"

        # 7. Reorder & Restock Stock
        elif any(k in msg for k in ["reorder", "restock", "purchase order", "replenish"]):
            sku_match = re.search(r"([A-Za-z]+-\d+)", user_message)
            sku = sku_match.group(1).upper() if sku_match else None
            nums = re.findall(r"\b\d+\b", user_message)
            qty = 20
            if sku:
                sku_num = sku.split("-")[-1]
                other_nums = [int(n) for n in nums if n != sku_num]
                if other_nums:
                    qty = other_nums[0]
            if sku:
                res = reorder_inventory(sku=sku, quantity=qty, tenant_id=tenant_id)
                tool_calls_executed.append({"tool": "reorder_inventory", "args": {"sku": sku, "quantity": qty, "tenant_id": tenant_id}, "result": res})
                if res.get("success"):
                    reply = f"✅ **Purchase Order Executed [{tenant_id}]:** Reordered **{res['units_ordered']} units** of **{res['product_name']}** (`{res['sku']}`). New Stock: **{res['new_stock']} units** (${res['total_cost']:.2f})."
                else:
                    reply = f"❌ **Reorder Failed:** {res.get('error', 'Error')}"
            else:
                reply = "Please specify SKU to reorder (e.g. `Reorder 25 units of SKU-101`)."

        # 7. Daily Executive Briefing
        elif any(k in msg for k in ["briefing", "morning brief", "overview", "standup", "digest"]):
            brief = generate_daily_briefing(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "generate_daily_briefing", "args": {"tenant_id": tenant_id}, "result": brief})
            reply = format_daily_briefing_reply(brief, tenant_id)

        # 8. Low Stock & Inventory Thresholds
        elif any(k in msg for k in ["inventory", "stock", "low stock", "catalog", "warehouse", "threshold", "safety stock"]):
            inv = get_inventory_alerts(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "get_inventory_alerts", "args": {"tenant_id": tenant_id}, "result": inv})
            reply = format_inventory_alerts_reply(inv, tenant_id)

        # 9. Tasks & Action Items
        elif any(k in msg for k in ["task", "todo", "schedule", "action item"]):
            tasks_data = list_daily_tasks(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "list_daily_tasks", "args": {"tenant_id": tenant_id}, "result": tasks_data})
            reply = f"📋 **Today's Operational Tasks for [{tenant_id}] ({tasks_data['total_tasks']} total)**\n"
            for t in tasks_data["tasks"]:
                reply += f"- **[{t['priority']}]** {t['title']} ({t['status']})\n"

        # 10. Sales & Revenue Telemetry
        elif any(k in msg for k in ["sale", "revenue", "income", "money", "sold", "earnings", "pos telemetry"]):
            sales = get_daily_sales_summary(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "get_daily_sales_summary", "args": {"tenant_id": tenant_id}, "result": sales})
            reply = format_daily_sales_reply(sales, tenant_id)

        # Default Help
        else:
            reply = (
                f"👋 Hello! I am your **Productivity & Operations Assistant** for business tenant **[{tenant_id}]**.\n\n"
                "Type a number or prompt to begin:\n"
                "1. 📊 **Daily Sales**: *'1'* or *'Show sales summary'*\n"
                "2. 📦 **Inventory Alerts**: *'2'* or *'Low stock alerts'*\n"
                "3. 📈 **Demand Forecast**: *'3'* or *'Forecast demand'*\n"
                "4. ⚡ **Automate Restock**: *'4'* or *'Reorder SKU-101'*\n"
                "5. 🌅 **Executive Briefing**: *'5'* or *'Morning briefing'*\n"
                "6. ⭐ **Customer Feedback**: *'6'* or *'Customer reviews'*\n"
                "7. 🔔 **Webhook Dispatch**: *'7'* or *'Send alert to Slack'*"
            )

        return {
            "tenant_id": tenant_id,
            "reply": reply,
            "tool_calls": tool_calls_executed,
            "engine": "local-rule-engine",
            "timestamp": datetime.datetime.now().isoformat()
        }


agent_instance = ProductivityAgent()
