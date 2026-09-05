"""
Employee Shift & Operational Task Tracking Module.
Enables business owners to manage staff assignments, track shift schedules,
monitor daily task completion rates, and calculate employee productivity metrics.
"""

import datetime
from typing import List, Dict, Any, Optional
from database import query_all, query_one, execute_mutation, get_db_connection


class EmployeeTaskManager:
    """Manages shift rosters, staff operational task assignments, and completion metrics."""

    def __init__(self, tenant_id: str = "acme-electronics"):
        self.tenant_id = tenant_id

    def schedule_shift(
        self,
        employee_name: str,
        role: str,
        shift_date: Optional[str] = None,
        start_time: str = "08:00",
        end_time: str = "17:00"
    ) -> Dict[str, Any]:
        """Schedules an employee shift for the tenant."""
        s_date = shift_date or datetime.date.today().isoformat()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO employee_shifts (tenant_id, employee_name, role, shift_date, start_time, end_time, status, tasks_assigned, tasks_completed)
            VALUES (?, ?, ?, ?, ?, ?, 'SCHEDULED', 0, 0)
            """,
            (self.tenant_id, employee_name.strip(), role.strip(), s_date, start_time, end_time)
        )
        shift_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return {
            "success": True,
            "tenant_id": self.tenant_id,
            "shift_id": shift_id,
            "employee_name": employee_name.strip(),
            "role": role.strip(),
            "shift_date": s_date,
            "hours": f"{start_time} - {end_time}"
        }

    def list_shifts(self, shift_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves shifts for the tenant."""
        query = "SELECT * FROM employee_shifts WHERE tenant_id = ?"
        params: List[Any] = [self.tenant_id]
        if shift_date:
            query += " AND shift_date = ?"
            params.append(shift_date)
        query += " ORDER BY shift_date DESC, start_time ASC"
        return query_all(query, tuple(params))

    def get_productivity_report(self) -> Dict[str, Any]:
        """
        Aggregates tasks completed vs pending by assignee/employee,
        calculating overall team productivity and overdue items.
        """
        today_iso = datetime.date.today().isoformat()
        
        # Get tasks by assignee
        tasks = query_all("SELECT * FROM daily_tasks WHERE tenant_id = ?", (self.tenant_id,))
        assignee_stats: Dict[str, Dict[str, int]] = {}

        total_tasks = len(tasks)
        completed_tasks = 0
        overdue_tasks = 0

        for t in tasks:
            assignee = t.get("assigned_to", "Unassigned")
            if assignee not in assignee_stats:
                assignee_stats[assignee] = {"assigned": 0, "completed": 0, "in_progress": 0, "pending": 0}

            status = t.get("status", "PENDING")
            assignee_stats[assignee]["assigned"] += 1

            if status == "COMPLETED":
                completed_tasks += 1
                assignee_stats[assignee]["completed"] += 1
            elif status == "IN_PROGRESS":
                assignee_stats[assignee]["in_progress"] += 1
            else:
                assignee_stats[assignee]["pending"] += 1
                if t.get("due_date") and t["due_date"] < today_iso:
                    overdue_tasks += 1

        overall_completion_rate = round((completed_tasks / total_tasks * 100), 1) if total_tasks > 0 else 0.0

        return {
            "tenant_id": self.tenant_id,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "overdue_tasks": overdue_tasks,
            "team_completion_rate_pct": overall_completion_rate,
            "assignee_breakdown": assignee_stats
        }
