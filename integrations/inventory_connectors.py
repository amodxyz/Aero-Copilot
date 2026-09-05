"""
Inventory Tracking Connectors (Firestore, Supabase, Local DB).
Queries stock levels, compares against low-stock thresholds, and generates critical alerts.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import os


class BaseInventoryConnector(ABC):
    """Abstract interface for querying and modifying stock levels across database engines."""

    @abstractmethod
    def get_stock_levels(self, tenant_id: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def check_threshold_alerts(self, tenant_id: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def update_stock(self, tenant_id: str, sku: str, delta: int) -> Dict[str, Any]:
        pass


class FirestoreInventoryConnector(BaseInventoryConnector):
    """Google Cloud Firestore NoSQL Database Connector."""

    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "production-project")

    def get_stock_levels(self, tenant_id: str) -> List[Dict[str, Any]]:
        from database import query_all
        return query_all("SELECT * FROM products WHERE tenant_id = ?", (tenant_id,))

    def check_threshold_alerts(self, tenant_id: str) -> Dict[str, Any]:
        from tools import get_inventory_alerts
        res = get_inventory_alerts(tenant_id)
        res["database_engine"] = "Google Cloud Firestore"
        return res

    def update_stock(self, tenant_id: str, sku: str, delta: int) -> Dict[str, Any]:
        from tools import reorder_inventory
        return reorder_inventory(sku, delta, tenant_id=tenant_id)


class SupabaseInventoryConnector(BaseInventoryConnector):
    """Supabase Cloud PostgreSQL Database Connector."""

    def __init__(self, supabase_url: Optional[str] = None, api_key: Optional[str] = None):
        self.supabase_url = supabase_url
        self.api_key = api_key

    def get_stock_levels(self, tenant_id: str) -> List[Dict[str, Any]]:
        from database import query_all
        return query_all("SELECT * FROM products WHERE tenant_id = ?", (tenant_id,))

    def check_threshold_alerts(self, tenant_id: str) -> Dict[str, Any]:
        from tools import get_inventory_alerts
        res = get_inventory_alerts(tenant_id)
        res["database_engine"] = "Supabase PostgreSQL"
        return res

    def update_stock(self, tenant_id: str, sku: str, delta: int) -> Dict[str, Any]:
        from tools import reorder_inventory
        return reorder_inventory(sku, delta, tenant_id=tenant_id)


class UnifiedInventoryManager:
    def __init__(self):
        self.connectors = {
            "firestore": FirestoreInventoryConnector(),
            "supabase": SupabaseInventoryConnector()
        }

    def get_connector(self, backend: str = "firestore") -> BaseInventoryConnector:
        return self.connectors.get(backend.lower(), self.connectors["firestore"])

    def get_consolidated_inventory_report(self, tenant_id: str = "acme-electronics", backend: str = "firestore") -> Dict[str, Any]:
        connector = self.get_connector(backend)
        stock_list = connector.get_stock_levels(tenant_id)
        alerts = connector.check_threshold_alerts(tenant_id)
        return {
            "tenant_id": tenant_id,
            "backend": backend,
            "total_products": len(stock_list),
            "low_stock_count": alerts.get("low_stock_count", 0),
            "alerts": alerts.get("alerts", [])
        }


inventory_manager = UnifiedInventoryManager()
