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

Always scope all actions and queries strictly to the active tenant.
"""


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

    def process_message(self, user_message: str, chat_history: Optional[List[Dict[str, str]]] = None, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
        """Processes a user request scoped to a specific business tenant."""
        clean_input = user_message.strip().lower()
        if clean_input in ("1", "2", "3", "4", "5", "6", "7") or clean_input.startswith(("option 1", "option 2", "option 3", "option 4", "option 5", "option 6", "option 7")):
            return self._process_with_rule_engine(user_message, tenant_id)

        if self.client:
            try:
                return self._process_with_gemini(user_message, chat_history, tenant_id)
            except Exception as e:
                print(f"[Agent] Gemini error: {e}. Falling back to rule engine.")

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

            reply_text = summary_response.text or ""
            if f"[{tenant_id}]" not in reply_text and tenant_id not in reply_text:
                reply_text = f"📊 **Operations Report [{tenant_id}]**\n\n" + reply_text

            return {
                "tenant_id": tenant_id,
                "reply": reply_text,
                "tool_calls": tool_calls_executed,
                "engine": "gemini-cloud",
                "timestamp": datetime.datetime.now().isoformat()
            }

        final_text = response.text or "Request processed."
        if f"[{tenant_id}]" not in final_text and tenant_id not in final_text:
            final_text = f"⚡ **Aero Copilot [{tenant_id}]**\n\n" + final_text

        return {
            "tenant_id": tenant_id,
            "reply": final_text,
            "tool_calls": [],
            "engine": "gemini-cloud",
            "timestamp": datetime.datetime.now().isoformat()
        }

    def _process_with_rule_engine(self, user_message: str, tenant_id: str = DEFAULT_TENANT) -> Dict[str, Any]:
        msg = user_message.lower().strip()
        clean_msg = re.sub(r"[^\w\s\-]", "", msg).strip()
        tool_calls_executed = []
        reply = ""

        # 1. Numbered Menu Selections
        if clean_msg in ("1", "option 1", "opt 1") or clean_msg.startswith("1 "):
            sales = get_daily_sales_summary(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "get_daily_sales_summary", "args": {"tenant_id": tenant_id}, "result": sales})
            reply = f"💰 **Sales Report for [{tenant_id}] ({sales['date']})**\n\n"
            reply += f"- **Total Revenue:** ${sales['total_revenue']:.2f}\n"
            reply += f"- **Total Orders:** {sales['total_orders']}\n"
            reply += f"- **Average Order Value (AOV):** ${sales['average_order_value']:.2f}\n\n"
            if sales["top_selling_products"]:
                reply += "**Top Sellers Today:**\n"
                for item in sales["top_selling_products"]:
                    reply += f"- `{item['sku']}` {item['name']}: **{item['units_sold']} units** (${item['total_revenue']:.2f})\n"

        elif clean_msg in ("2", "option 2", "opt 2") or clean_msg.startswith("2 "):
            inv = get_inventory_alerts(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "get_inventory_alerts", "args": {"tenant_id": tenant_id}, "result": inv})
            if inv["low_stock_count"] == 0:
                reply = f"✅ **Inventory Status [{tenant_id}]:** All products are above safe threshold levels."
            else:
                reply = f"⚠️ **Low Stock Alert [{tenant_id}]: {inv['low_stock_count']} items require reordering**\n\n"
                for item in inv["critical_alerts"]:
                    reply += f"- **{item['name']}** (`{item['sku']}`): **{item['current_stock']} left** (Threshold: {item['threshold']}) ➔ Recommend reordering **{item['recommended_reorder']} units** (Est. ${item['estimated_reorder_cost']:.2f})\n"

        elif clean_msg in ("3", "option 3", "opt 3") or clean_msg.startswith("3 "):
            forecast_data = forecast_sales_demand(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "forecast_sales_demand", "args": {"tenant_id": tenant_id}, "result": forecast_data})
            reply = f"📈 **Demand Forecast [{tenant_id}] (Next 7 & 30 Days)**\n\n"
            for f in forecast_data["forecasts"][:5]:
                risk_badge = "🔴 High Risk" if f["stockout_risk"] == "HIGH" else ("🟡 Medium" if f["stockout_risk"] == "MEDIUM" else "🟢 Stable")
                reply += f"- **{f['name']}** (`{f['sku']}`): Stock: **{f['current_stock']}** | Velocity: ~{f['daily_velocity']}/day | Stockout In: **~{f['days_until_stockout']} days** ({risk_badge})\n"

        elif clean_msg in ("4", "option 4", "opt 4") or clean_msg.startswith("4 "):
            inv = get_inventory_alerts(tenant_id=tenant_id)
            if inv["critical_alerts"]:
                top_item = inv["critical_alerts"][0]
                res = reorder_inventory(sku=top_item["sku"], quantity=top_item["recommended_reorder"], tenant_id=tenant_id)
                tool_calls_executed.append({"tool": "reorder_inventory", "args": {"sku": top_item["sku"], "quantity": top_item["recommended_reorder"], "tenant_id": tenant_id}, "result": res})
                reply = f"✅ **Purchase Order Executed [{tenant_id}]:** Reordered **{res['units_ordered']} units** of **{res['product_name']}** (`{res['sku']}`). New Stock: **{res['new_stock']} units**."
            else:
                reply = "Please specify SKU to reorder (e.g. `Reorder 25 units of SKU-101`)."

        elif clean_msg in ("5", "option 5", "opt 5") or clean_msg.startswith("5 "):
            brief = generate_daily_briefing(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "generate_daily_briefing", "args": {"tenant_id": tenant_id}, "result": brief})
            sales = brief["sales_summary"]
            inv = brief["inventory_status"]
            tasks = brief["pending_tasks"]
            reply = f"🌅 **Daily Executive Briefing [{tenant_id}] ({brief['briefing_date']})**\n\n"
            reply += f"**📊 Sales:** Revenue **${sales['total_revenue']:.2f}** ({sales['total_orders']} orders)\n"
            reply += f"**⚠️ Inventory:** {inv['low_stock_count']} item(s) low on stock.\n"
            reply += f"**📋 Tasks:** {tasks['total_tasks']} action items pending."

        elif clean_msg in ("6", "option 6", "opt 6") or clean_msg.startswith("6 "):
            feedback_data = analyze_customer_feedback(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "analyze_customer_feedback", "args": {"tenant_id": tenant_id}, "result": feedback_data})
            reply = f"⭐ **Customer Feedback [{tenant_id}]:** Rating {feedback_data['average_rating']}/5.0 ({feedback_data['satisfaction_rate']} satisfaction)."

        elif clean_msg in ("7", "option 7", "opt 7") or clean_msg.startswith("7 "):
            webhook_res = trigger_operational_webhook_alert(channel="slack", tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "trigger_operational_webhook_alert", "args": {"channel": "slack", "tenant_id": tenant_id}, "result": webhook_res})
            reply = f"🚀 **Webhook Dispatched [{tenant_id}]:** Alert sent to **#slack**."

        # 2. Demand Forecasting & Velocity (High priority keyword match)
        elif any(k in msg for k in ["forecast", "demand", "velocity", "stockout risk", "predict", "future sales"]):
            forecast_data = forecast_sales_demand(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "forecast_sales_demand", "args": {"tenant_id": tenant_id}, "result": forecast_data})
            reply = f"📈 **Demand Forecast & Stockout Velocity [{tenant_id}]**\n\n"
            for f in forecast_data["forecasts"][:5]:
                risk_badge = "🔴 High Risk" if f["stockout_risk"] == "HIGH" else ("🟡 Medium Risk" if f["stockout_risk"] == "MEDIUM" else "🟢 Stable")
                reply += f"- **{f['name']}** (`{f['sku']}`): Stock: **{f['current_stock']}** | Velocity: ~{f['daily_velocity']}/day | Stockout In: **~{f['days_until_stockout']} days** ({risk_badge})\n"

        # 3. Customer Reviews & Feedback
        elif any(k in msg for k in ["review", "feedback", "rating", "satisfaction", "sentiment", "customer sentiment"]):
            feedback_data = analyze_customer_feedback(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "analyze_customer_feedback", "args": {"tenant_id": tenant_id}, "result": feedback_data})
            reply = f"⭐ **Customer Sentiment & Feedback [{tenant_id}]**\n"
            reply += f"- **Average Rating:** {feedback_data['average_rating']}/5.0 ({feedback_data['satisfaction_rate']} positive satisfaction)\n"
            reply += f"- **Summary:** {feedback_data.get('summary', 'Recent customer reviews show strong fulfillment satisfaction.')}"

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

        # 6. Reorder & Restock Stock
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
            sales = brief["sales_summary"]
            inv = brief["inventory_status"]
            tasks = brief["pending_tasks"]
            reply = f"🌅 **Daily Executive Briefing [{tenant_id}] ({brief['briefing_date']})**\n\n"
            reply += f"**📊 Sales:** Revenue **${sales['total_revenue']:.2f}** ({sales['total_orders']} orders)\n"
            reply += f"**⚠️ Inventory:** {inv['low_stock_count']} item(s) low on stock.\n"
            reply += f"**📋 Tasks:** {tasks['total_tasks']} action items pending."

        # 8. Low Stock & Inventory Thresholds
        elif any(k in msg for k in ["inventory", "stock", "low stock", "catalog", "warehouse", "threshold", "safety stock"]):
            inv = get_inventory_alerts(tenant_id=tenant_id)
            tool_calls_executed.append({"tool": "get_inventory_alerts", "args": {"tenant_id": tenant_id}, "result": inv})
            if inv["low_stock_count"] == 0:
                reply = f"✅ **Inventory [{tenant_id}]:** All items are above safe levels."
            else:
                reply = f"⚠️ **Low Stock Alert [{tenant_id}]: {inv['low_stock_count']} items require reordering**\n"
                for item in inv["critical_alerts"]:
                    reply += f"- **{item['name']}** (`{item['sku']}`): **{item['current_stock']} left** (Safe Min: {item['threshold']})\n"

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
            reply = f"💰 **Sales Report for [{tenant_id}] ({sales['date']})**\n- Revenue: **${sales['total_revenue']:.2f}** ({sales['total_orders']} orders, AOV: ${sales['average_order_value']:.2f})"

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
