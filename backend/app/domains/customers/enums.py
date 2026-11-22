from enum import StrEnum


class UserRole(StrEnum):
    """RBAC roles from 19-security-compliance."""

    ADMIN = "admin"
    OPERATOR = "operator"
    CUSTOMER = "customer"
    READONLY = "readonly"


STAFF_ROLES = (UserRole.ADMIN, UserRole.OPERATOR)


class CustomerStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CHURNED = "churned"
