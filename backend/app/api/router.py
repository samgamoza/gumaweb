from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    analytics,
    auth,
    automation,
    billing,
    businesses,
    claims,
    customer,
    discovery,
    domains,
    engagement,
    health,
    outreach,
    pipeline,
    presence,
    public,
    templates,
    websites,
)

api_router = APIRouter()
for module in (auth, businesses, templates, websites, claims, customer, engagement, outreach, billing, analytics, admin,
               public, health):
    api_router.include_router(module.router)
api_router.include_router(automation.router)
api_router.include_router(automation.gateway)
api_router.include_router(presence.router)
api_router.include_router(discovery.router)
api_router.include_router(pipeline.router)
api_router.include_router(domains.router)
api_router.include_router(domains.edge)
