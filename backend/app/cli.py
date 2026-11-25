"""Operational commands (also used by Kubernetes Jobs/CronJobs).

    python -m app.cli seed [--demo]
    python -m app.cli sync-templates
    python -m app.cli create-admin EMAIL PASSWORD
    python -m app.cli generate [--limit N] [--publish]     # synchronous factory batch (small runs)
    python -m app.cli enqueue [--limit N] [--no-publish]   # queue a factory batch for the workers
    python -m app.cli worker [--once]                      # factory worker: jobs + event outbox relay
    python -m app.cli dispatch-outreach
    python -m app.cli suppress add|remove|list [VALUE] [--domain] [--reason R] [--note TEXT]
    python -m app.cli backfill-prospects                   # build the sales CRM from history (idempotent)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.seed import seed_all
from app.db.session import SessionLocal
from app.domains.outreach.suppression import SuppressionKind, SuppressionReason
from app.domains.website_factory.enums import WebsiteStatus
from app.models import Business, Website
from app.schemas.website import GenerateBatchRequest
from app.services.auth_service import AuthService
from app.services.crm_service import CrmService
from app.services.outreach_service import OutreachService
from app.services.prospect_service import ProspectService
from app.services.publishing_service import PublishingService
from app.services.support import SYSTEM
from app.services.suppression_service import SuppressionService
from app.services.template_service import TemplateService
from app.services.website_service import WebsiteService
from app.workers.factory_worker import FactoryWorker
from app.workflows.website_generation import WebsiteGenerationWorkflow

logger = logging.getLogger("gumaweb.cli")


def cmd_generate(limit: int, publish: bool) -> dict[str, int]:
    """Factory batch: generate (and optionally publish) sites for top-scoring candidates."""
    settings = get_settings()
    stats = {"generated": 0, "published": 0, "failed": 0}
    with SessionLocal() as db:
        has_site = select(Website.business_id)
        ids = db.scalars(
            select(Business.id)
            .where(Business.generate_candidate.is_(True), Business.id.not_in(has_site))
            .order_by(Business.score.desc())
            .limit(limit)
        ).all()
        for business_id in ids:
            try:
                business = db.get(Business, business_id)
                website = WebsiteGenerationWorkflow(db, settings).run(business)
                stats["generated"] += 1
                if publish and (website.quality_report or {}).get("publishable"):
                    PublishingService(db, settings).publish(website, SYSTEM)
                    stats["published"] += 1
                db.commit()
            except Exception:
                logger.exception("generation failed for %s", business_id)
                db.rollback()
                stats["failed"] += 1
        if publish:
            # Retry sites generated earlier whose publish failed or was deferred.
            pending = db.scalars(
                select(Website).where(Website.status == WebsiteStatus.BLUEPRINT_READY).limit(limit)
            ).all()
            for website in pending:
                if not (website.quality_report or {}).get("publishable"):
                    continue
                try:
                    PublishingService(db, settings).publish(website, SYSTEM)
                    db.commit()
                    stats["published"] += 1
                except Exception:
                    logger.exception("publish failed for %s", website.subdomain)
                    db.rollback()
                    stats["failed"] += 1
    return stats


def cmd_suppress(db: Session, args: argparse.Namespace) -> object:
    service = SuppressionService(db)
    kind = SuppressionKind.DOMAIN if args.domain else SuppressionKind.EMAIL
    if args.action == "list":
        return [{"kind": s.kind.value, "value": s.value, "reason": s.reason, "note": s.note,
                 "created_at": s.created_at} for s in service.list()]
    if args.action == "check":
        match = service.match(args.value)
        return {"email": args.value, "suppressed": match is not None,
                "matched": f"{match.kind.value}:{match.value}" if match else None}
    if args.action == "add":
        entry, created = service.add(kind, args.value, args.reason, SYSTEM, note=args.note)
        return {"added": created, "kind": entry.kind.value, "value": entry.value}
    return {"removed": service.remove(kind, args.value, SYSTEM)}


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    parser = argparse.ArgumentParser(prog="gumaweb")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed")
    seed.add_argument("--demo", action="store_true", help="also create fictional demo businesses")
    sub.add_parser("sync-templates")
    admin = sub.add_parser("create-admin")
    admin.add_argument("email")
    admin.add_argument("password")
    gen = sub.add_parser("generate")
    gen.add_argument("--limit", type=int, default=100)
    gen.add_argument("--publish", action="store_true")
    sub.add_parser("dispatch-outreach")
    sub.add_parser("rescore-leads", help="backfill/refresh lead scores without firing alerts (nightly)")
    sub.add_parser("backfill-prospects", help="build sales CRM prospects and timelines from history (idempotent)")
    mail = sub.add_parser("mail-bootstrap", help="first-run setup of a fresh Stalwart mail server")
    mail.add_argument("--hostname", required=True, help="the mail server's public name, e.g. mail.gumaweb.io")
    mail.add_argument("--domain", required=True, help="the platform's own mail domain, e.g. gumaweb.io")
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--limit", type=int, default=1000)
    enqueue.add_argument("--no-publish", action="store_true")
    suppress = sub.add_parser("suppress", help="manage the do-not-contact list (email or whole domain)")
    suppress.add_argument("action", choices=["add", "remove", "list", "check"])
    suppress.add_argument("value", nargs="?", help="email address, or a domain with --domain")
    suppress.add_argument("--domain", action="store_true", help="VALUE is a whole domain")
    suppress.add_argument("--reason", default=SuppressionReason.REQUESTED.value,
                          choices=[r.value for r in SuppressionReason])
    suppress.add_argument("--note")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true", help="drain due jobs, relay events, then exit")
    args = parser.parse_args(argv)
    if args.command == "suppress" and args.action != "list" and not args.value:
        parser.error(f"suppress {args.action} needs a VALUE")

    if args.command == "worker":
        factory_worker = FactoryWorker(SessionLocal, settings)
        if not args.once:
            factory_worker.run_forever()
            return 0
        result: object = {"jobs": factory_worker.drain(), "events_relayed": factory_worker.relay_events(),
                          "automations": factory_worker.automation_tick()}
    elif args.command == "enqueue":
        with SessionLocal() as db:
            result = WebsiteService(db, settings).enqueue_batch(
                GenerateBatchRequest(limit=args.limit, publish=not args.no_publish)).model_dump()
    elif args.command == "mail-bootstrap":
        import os

        from app.services.mail_provider import bootstrap_stalwart

        user, _, secret = os.environ.get("STALWART_RECOVERY_ADMIN", "").partition(":")
        if not secret:
            print("Set STALWART_RECOVERY_ADMIN=admin:<password> (the same value given to the Stalwart container)")
            return 2
        created = bootstrap_stalwart(settings.stalwart_url, user, secret, hostname=args.hostname,
                                     default_domain=args.domain)
        result = {**created, "next": "Set STALWART_USERNAME/STALWART_SECRET to these values, MAIL_PROVIDER=stalwart, "
                                     "restart Stalwart, and remove STALWART_RECOVERY_ADMIN."}
    elif args.command == "generate":
        result = cmd_generate(args.limit, args.publish)
    else:
        with SessionLocal() as db:
            if args.command == "seed":
                result = seed_all(db, settings, demo=args.demo)
            elif args.command == "sync-templates":
                result = TemplateService(db, settings).sync_from_disk(SYSTEM).model_dump()
            elif args.command == "rescore-leads":
                result = {"rescored": CrmService(db, settings).rescore_all()}
            elif args.command == "suppress":
                result = cmd_suppress(db, args)
            elif args.command == "backfill-prospects":
                result = vars(ProspectService(db).backfill())
            elif args.command == "create-admin":
                user = AuthService(db).ensure_admin(args.email, args.password)
                result = {"admin": user.email}
            else:
                result = OutreachService(db, settings).dispatch_due().model_dump()
    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
