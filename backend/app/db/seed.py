"""Idempotent seed data: plan catalog, templates/components, first admin, demo businesses.

Demo businesses are fictional and use reserved example domains / test numbers.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.domains.billing.plans import PLAN_CATALOG
from app.models import Plan
from app.schemas.business import BusinessCreate
from app.services.auth_service import AuthService
from app.services.business_service import BusinessService
from app.services.support import SYSTEM
from app.services.template_service import TemplateService

logger = logging.getLogger("gumaweb.seed")

DEMO_BUSINESSES = [
    {"name": "ABC Construction", "city": "San Fernando", "province": "Pampanga", "phone": "0917 555 0101",
     "email": "abcconstruction.demo@gmail.com", "facebook": "facebook.com/abcconstruction.demo"},
    {"name": "Santos Plumbing Services", "city": "Angeles City", "province": "Pampanga",
     "phone": "0917 555 0102", "industry": "plumbing", "facebook": "facebook.com/santosplumbing.demo"},
    {"name": "Bella Vista Dental Clinic", "city": "Malolos", "province": "Bulacan", "phone": "0917 555 0103",
     "email": "bellavista.demo@yahoo.com"},
    {"name": "Lola Nena's Kitchen", "city": "Tarlac City", "province": "Tarlac", "phone": "0917 555 0104",
     "facebook": "facebook.com/lolanenaskitchen.demo"},
    {"name": "Reyes & Cruz Law Office", "city": "Quezon City", "province": "Metro Manila",
     "phone": "0917 555 0105", "email": "reyescruz.demo@gmail.com"},
    {"name": "Bright Minds Learning Center", "city": "Olongapo", "province": "Zambales",
     "phone": "0917 555 0106", "email": "brightminds.demo@gmail.com"},
    {"name": "Glow Beauty Salon & Spa", "city": "Baguio", "province": "Benguet", "phone": "0917 555 0107",
     "facebook": "facebook.com/glowbeauty.demo"},
    {"name": "Coral Bay Beach Resort", "city": "Subic", "province": "Zambales", "phone": "0917 555 0108",
     "email": "coralbay.demo@gmail.com", "facebook": "facebook.com/coralbay.demo"},
    {"name": "Mabuhay Hardware & Trading", "city": "Cabanatuan", "province": "Nueva Ecija",
     "phone": "0917 555 0109"},
    {"name": "Already Online Corp", "city": "Makati", "province": "Metro Manila", "phone": "0917 555 0110",
     "website": "https://example.com", "email": "info@example.com"},
]


def seed_plans(db: Session) -> int:
    created = 0
    for spec in PLAN_CATALOG:
        plan = db.get(Plan, spec["code"])
        if plan is None:
            db.add(Plan(**spec))
            created += 1
        else:
            for key, value in spec.items():
                setattr(plan, key, value)
    db.commit()
    return created


def seed_all(db: Session, settings: Settings, demo: bool = False) -> dict[str, int]:
    result = {"plans_created": seed_plans(db)}
    sync = TemplateService(db, settings).sync_from_disk(SYSTEM)
    result["templates_created"] = sync.templates_created
    result["components"] = sync.components_registered
    AuthService(db).ensure_admin(settings.first_admin_email, settings.first_admin_password)
    if demo:
        service = BusinessService(db, settings)
        created = 0
        for data in DEMO_BUSINESSES:
            try:
                service.create(BusinessCreate(**data), SYSTEM)
                created += 1
            except Exception as exc:  # duplicates on re-run
                logger.info("skip demo business %s: %s", data["name"], exc)
                db.rollback()
        result["demo_businesses_created"] = created
    return result
