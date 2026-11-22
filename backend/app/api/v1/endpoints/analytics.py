from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import AppSettings, DbSession, StaffReader
from app.schemas.analytics import PlatformOverview, WebsiteAnalytics
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/overview", response_model=PlatformOverview, summary="Platform KPIs and acquisition funnel")
def overview(_: StaffReader, db: DbSession, settings: AppSettings) -> PlatformOverview:
    return AnalyticsService(db, settings).overview()


@router.get("/websites/{website_id}", response_model=WebsiteAnalytics)
def website_analytics(website_id: uuid.UUID, _: StaffReader, db: DbSession, settings: AppSettings,
                      days: int = Query(30, ge=1, le=365)) -> WebsiteAnalytics:
    return AnalyticsService(db, settings).website_stats(website_id, days)


@router.get("/timeseries", response_model=list[dict[str, Any]], summary="Daily factory and acquisition counts")
def timeseries(_: StaffReader, db: DbSession, settings: AppSettings,
               days: int = Query(30, ge=7, le=180)) -> list[dict[str, Any]]:
    return AnalyticsService(db, settings).timeseries(days)


@router.get("/templates", response_model=list[dict[str, Any]], summary="Sites, claims and quality per template")
def templates(_: StaffReader, db: DbSession, settings: AppSettings) -> list[dict[str, Any]]:
    return AnalyticsService(db, settings).template_performance()


@router.get("/industries", response_model=list[dict[str, Any]], summary="Pipeline breakdown by industry")
def industries(_: StaffReader, db: DbSession, settings: AppSettings) -> list[dict[str, Any]]:
    return AnalyticsService(db, settings).industry_breakdown()


@router.get("/ai", response_model=dict[str, Any], summary="AI usage: calls, tokens, latency, acceptance")
def ai_usage(_: StaffReader, db: DbSession, settings: AppSettings) -> dict[str, Any]:
    return AnalyticsService(db, settings).ai_usage()
