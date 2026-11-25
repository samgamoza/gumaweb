"""BusinessDiscovery + BusinessProfile application services."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.registry import get_profiler_agent
from app.core.config import Settings
from app.core.exceptions import ConflictError, ValidationFailedError
from app.domains.audit.actions import AuditAction
from app.domains.business_discovery import normalization as norm
from app.domains.business_discovery.enums import BusinessStatus, DiscoveryRunStatus, DiscoverySource
from app.domains.business_discovery.lifecycle import advance
from app.domains.business_discovery.scoring import ScoringInput, score_business
from app.domains.business_discovery.sources import InvalidRecord, RawBusinessRecord, SourceItem
from app.domains.business_profile.enums import ProfileSource
from app.domains.business_profile.industry_catalog import classify, get_industry
from app.domains.business_profile.profiler import ProfileInput
from app.models import Business, BusinessProfile, DiscoveryRun
from app.repositories.repositories import BusinessProfileRepository, BusinessRepository, DiscoveryRunRepository
from app.schemas.business import BusinessCreate, BusinessFilters, BusinessProfileUpdate, BusinessUpdate
from app.services.support import Actor, EventType, audit, record_event

MAX_IMPORT_ERRORS_STORED = 100


class BusinessService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.businesses = BusinessRepository(db)
        self.runs = DiscoveryRunRepository(db)

    # --- Normalize / deduplicate ---------------------------------------------------
    def _normalized(self, data: dict[str, Any]) -> dict[str, Any]:
        out = {k: norm.clean_text(v) if isinstance(v, str) else v for k, v in data.items()}
        out["phone"] = norm.normalize_phone(out.get("phone"), self.settings.default_country_code)
        out["email"] = norm.normalize_email(out.get("email"))
        out["website"] = norm.normalize_url(out.get("website"))
        out["facebook"] = norm.normalize_url(out.get("facebook"))
        if out.get("google_business_url"):
            out["google_business_url"] = norm.normalize_url(out["google_business_url"])
        if out.get("industry"):
            out["industry"] = out["industry"].lower()
        return out

    def _unique_slug(self, name: str, city: str | None) -> str:
        base = norm.slugify(name, max_length=50)
        candidates = [base] + ([norm.slugify(f"{base}-{city}", 58)] if city else [])
        candidates += [f"{candidates[-1][:58]}-{n}" for n in range(2, 500)]
        for candidate in candidates:
            if not self.businesses.slug_exists(candidate):
                return candidate
        raise ConflictError("Could not allocate a unique slug")

    # --- Commands -------------------------------------------------------------------
    def create(self, data: BusinessCreate, actor: Actor, run: DiscoveryRun | None = None,
               commit: bool = True) -> Business:
        fields = self._normalized(data.model_dump(exclude={"source", "source_ref"}))
        dedupe_key = norm.build_dedupe_key(fields["name"], fields.get("city"), fields.get("phone"))
        if self.businesses.by_dedupe_key(dedupe_key):
            raise ConflictError(f"Business '{fields['name']}' already exists", code="duplicate_business")
        business = Business(
            **fields,
            slug=self._unique_slug(fields["name"], fields.get("city")),
            dedupe_key=dedupe_key,
            source=data.source,
            source_ref=data.source_ref,
            discovery_run_id=run.id if run else None,
            status=BusinessStatus.DISCOVERED,
        )
        self.businesses.add(business)
        self._apply_score(business)
        record_event(self.db, EventType.BUSINESS_DISCOVERED, "business", business.id,
                     {"source": data.source.value})
        if commit:
            audit(self.db, actor, AuditAction.BUSINESS_CREATED, "business", business.id)
            self.db.commit()
        return business

    def import_records(self, records: Iterable[SourceItem], source: DiscoverySource, actor: Actor, *,
                       on_created: Callable[[Business, RawBusinessRecord], None] | None = None) -> DiscoveryRun:
        """Import a batch as one DiscoveryRun. `on_created` runs inside each new business's savepoint
        (e.g. to record contact provenance), so a failure there rolls back that business only."""
        run = self.runs.add(DiscoveryRun(source=source, started_by=actor.user_id, errors=[]))
        self.db.commit()
        errors: list[dict[str, Any]] = []
        try:
            for index, record in enumerate(records, start=1):
                run.total_records += 1
                if isinstance(record, InvalidRecord):
                    run.error_count += 1
                    if len(errors) < MAX_IMPORT_ERRORS_STORED:
                        errors.append({"row": index, "error": record.error})
                    continue
                try:
                    with self.db.begin_nested():
                        payload = BusinessCreate(**{**record.__dict__, "source": source})
                        business = self.create(payload, actor, run=run, commit=False)
                        if on_created is not None:
                            on_created(business, record)
                    run.created_count += 1
                except ConflictError:
                    run.duplicate_count += 1
                except (ValueError, IntegrityError) as exc:
                    run.error_count += 1
                    if len(errors) < MAX_IMPORT_ERRORS_STORED:
                        errors.append({"row": index, "error": str(exc)[:300]})
            run.status = DiscoveryRunStatus.COMPLETED
        except Exception as exc:  # malformed file etc.
            run.status = DiscoveryRunStatus.FAILED
            errors.append({"row": None, "error": str(exc)[:300]})
        run.errors = errors
        run.finished_at = datetime.now(UTC)
        audit(self.db, actor, AuditAction.BUSINESS_IMPORTED, "discovery_run", run.id,
              {"created": run.created_count, "duplicates": run.duplicate_count, "errors": run.error_count})
        self.db.commit()
        return run

    def record_failed_run(self, source: DiscoverySource, actor: Actor, error: str) -> DiscoveryRun:
        """A run that never got records (the source itself failed), so failures stay visible in history."""
        now = datetime.now(UTC)
        run = self.runs.add(DiscoveryRun(source=source, started_by=actor.user_id, status=DiscoveryRunStatus.FAILED,
                                         errors=[{"row": None, "error": error[:300]}], finished_at=now))
        audit(self.db, actor, AuditAction.BUSINESS_IMPORTED, "discovery_run", run.id, {"failed": error[:300]})
        self.db.commit()
        return run

    def update(self, business: Business, data: BusinessUpdate, actor: Actor) -> Business:
        changes = self._normalized(data.model_dump(exclude_unset=True))
        for field, value in changes.items():
            setattr(business, field, value)
        new_key = norm.build_dedupe_key(business.name, business.city, business.phone)
        if new_key != business.dedupe_key:
            existing = self.businesses.by_dedupe_key(new_key)
            if existing and existing.id != business.id:
                raise ConflictError("Another business with the same name, city and phone exists")
            business.dedupe_key = new_key
        self._apply_score(business)
        audit(self.db, actor, AuditAction.BUSINESS_UPDATED, "business", business.id, {"fields": list(changes)})
        self.db.commit()
        return business

    def archive(self, business: Business, actor: Actor) -> None:
        business.status = BusinessStatus.ARCHIVED
        business.generate_candidate = False
        audit(self.db, actor, AuditAction.BUSINESS_ARCHIVED, "business", business.id)
        self.db.commit()

    def rescore(self, business: Business) -> Business:
        self._apply_score(business)
        self.db.commit()
        return business

    def _apply_score(self, business: Business) -> None:
        industry = business.profile.industry if business.profile else None
        spec = get_industry(industry) if industry else classify(business.name, business.industry,
                                                                business.description)[0]
        result = score_business(
            ScoringInput(
                website=business.website, email=business.email, phone=business.phone,
                facebook=business.facebook, industry_value=spec.value,
            ),
            threshold=self.settings.score_generate_threshold,
        )
        business.score = result.score
        business.generate_candidate = result.generate_candidate and business.status != BusinessStatus.ARCHIVED
        business.score_breakdown = result.as_dict()
        business.scored_at = datetime.now(UTC)
        business.status = advance(business.status, BusinessStatus.SCORED)
        record_event(self.db, EventType.BUSINESS_SCORED, "business", business.id, {"score": result.score})

    # --- Queries --------------------------------------------------------------------
    def list(self, filters: BusinessFilters, page: int, page_size: int):
        return self.businesses.paginate(self.businesses.filtered(filters), page, page_size)


class ProfileService:
    """Business Intelligence Engine application service."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.profiles = BusinessProfileRepository(db)

    def ensure(self, business: Business, force: bool = False) -> BusinessProfile:
        profile = self.profiles.for_business(business.id)
        if profile and (not force or profile.source == ProfileSource.MANUAL):
            return profile
        result = get_profiler_agent(self.settings).run(
            ProfileInput(name=business.name, city=business.city, province=business.province,
                         industry_hint=business.industry, description=business.description)
        ).output
        if profile is None:
            profile = BusinessProfile(business=business)
            self.db.add(profile)
        profile.industry = result.industry
        profile.category = result.category
        profile.services = result.services
        profile.keywords = result.keywords
        profile.local_keywords = result.local_keywords
        profile.target_audience = result.target_audience
        profile.brand_tone = result.brand_tone
        profile.brand_voice = result.brand_voice
        profile.tagline = result.tagline
        profile.confidence = result.confidence
        profile.source = ProfileSource.RULE_BASED
        business.industry = business.industry or result.industry
        business.status = advance(business.status, BusinessStatus.PROFILED)
        self.db.flush()
        return profile

    def update(self, business: Business, data: BusinessProfileUpdate) -> BusinessProfile:
        profile = self.ensure(business)
        changes = data.model_dump(exclude_unset=True)
        if "services" in changes:
            services = [s.strip() for s in changes["services"] if s and s.strip()]
            if not services:
                raise ValidationFailedError("At least one service is required")
            changes["services"] = services
        for field, value in changes.items():
            setattr(profile, field, value)
        profile.source = ProfileSource.MANUAL
        self.db.commit()
        return profile
