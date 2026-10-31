from fastapi import HTTPException, Header, Security, Depends
from typing import Optional, Dict, Any
from backend.database import get_connection

class LicensingAndSecurity:
    """
    Independent Module Licensing & Security Gate.
    Enforces tenant access and module permissions:
    - Customer A: Attendance Enabled, Product Counting Disabled
    - Customer B: Attendance Disabled, Product Counting Enabled
    - Customer C: Both Enabled
    """
    @staticmethod
    def get_tenant_permissions(tenant_id: str = "default") -> Dict[str, Any]:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT tenant_id, company_name, attendance_enabled, counting_enabled, max_cameras FROM tenants WHERE tenant_id = ?", (tenant_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return {
            "tenant_id": "default",
            "company_name": "Default Facility",
            "attendance_enabled": 1,
            "counting_enabled": 1,
            "max_cameras": 8
        }

    @staticmethod
    def require_module_permission(module_name: str, tenant_id: str = "default"):
        """
        Validates whether the customer's license permits access to the requested module.
        Raises 403 Forbidden if the module is disabled.
        """
        perms = LicensingAndSecurity.get_tenant_permissions(tenant_id)
        if module_name == "attendance" and not perms.get("attendance_enabled"):
            raise HTTPException(
                status_code=403,
                detail="License Restriction: 'AiCam Attendance' module is not active for this account."
            )
        elif module_name == "counting" and not perms.get("counting_enabled"):
            raise HTTPException(
                status_code=403,
                detail="License Restriction: 'AiCam Product Counting' module is not active for this account."
            )
        return True
