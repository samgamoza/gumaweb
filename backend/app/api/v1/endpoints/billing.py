from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSession
from app.models import Plan
from app.schemas.customer import PlanRead
from app.services.customer_service import BillingService

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get("/plans", response_model=list[PlanRead], summary="Public plan catalog")
def list_plans(db: DbSession) -> list[Plan]:
    return BillingService(db).list_plans()
