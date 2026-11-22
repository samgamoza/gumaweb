from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    analytics,
    auth,
    billing,
    businesses,
    claims,
    customer,
    domains,
    engagement,
    guma_os,
    health,
    outreach,
    presence,
    public,
    templates,
    websites,
)

api_router = APIRouter()
for module in (auth, businesses, templates, websites, claims, customer, engagement, outreach, billing, analytics, admin,
               public, health):
    api_router.include_router(module.router)
api_router.include_router(guma_os.router)
api_router.include_router(guma_os.gateway)
api_router.include_router(presence.router)
api_router.include_router(domains.router)
api_router.include_router(domains.edge)
