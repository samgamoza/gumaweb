from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    analytics,
    auth,
    billing,
    businesses,
    claims,
    customer,
    health,
    outreach,
    public,
    templates,
    websites,
)

api_router = APIRouter()
for module in (auth, businesses, templates, websites, claims, customer, outreach, billing, analytics, admin,
               public, health):
    api_router.include_router(module.router)
