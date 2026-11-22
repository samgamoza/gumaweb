"""Industry knowledge base driving classification, scoring, templates and copy.

This is the deterministic (Phase 1) substitute for the Industry/Service/Brand
agents. AI agents (Phase 2) consume and enrich the same structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndustrySpec:
    key: str
    label: str
    category: str  # template master category (06-template-factory)
    keywords: tuple[str, ...]
    services: tuple[tuple[str, str], ...]  # (name, description)
    target_audience: str
    brand_tone: str
    value: int  # 0-100 commercial value used by opportunity scoring
    schema_type: str  # schema.org LocalBusiness subtype
    faq: tuple[tuple[str, str], ...] = field(default_factory=tuple)


CATALOG: dict[str, IndustrySpec] = {
    spec.key: spec
    for spec in [
        IndustrySpec(
            "construction", "Construction", "construction",
            ("construction", "builders", "builder", "contractor", "contractors", "engineering", "roofing",
             "renovation", "steel", "concrete"),
            (("General Construction", "Residential and commercial building projects managed end to end."),
             ("Renovation & Remodeling", "Upgrades for kitchens, bathrooms, and full interiors."),
             ("Roofing", "Roof installation, repair, and waterproofing."),
             ("Carpentry", "Custom woodwork, cabinets, and structural framing."),
             ("Project Management", "Planning, permits, scheduling, and site supervision.")),
            "residential and commercial property owners", "professional", 85, "HomeAndConstructionBusiness",
            (("Do you handle building permits?", "We can guide you through the permit requirements for your project and coordinate with the relevant offices."),
             ("Do you offer free estimates?", "Contact us with your project details and we will arrange an assessment and quotation."),),
        ),
        IndustrySpec(
            "plumbing", "Plumbing", "construction",
            ("plumbing", "plumber", "plumbers", "drainage", "septic", "declogging"),
            (("Leak Repairs", "Fast detection and repair of leaking pipes and fixtures."),
             ("Pipe Installation", "New water lines and replacement of old piping."),
             ("Drain Cleaning", "Clearing blocked sinks, toilets, and main drains."),
             ("Water Heater Service", "Installation and maintenance of water heaters.")),
            "homes and businesses", "dependable", 75, "Plumber",
            (("Do you handle emergency repairs?", "Call us directly and we will advise on the fastest available schedule."),),
        ),
        IndustrySpec(
            "electrical", "Electrical Services", "construction",
            ("electrical", "electrician", "electric", "wiring", "solar"),
            (("Electrical Wiring", "Safe installation and rewiring for homes and offices."),
             ("Troubleshooting", "Diagnosis and repair of electrical faults."),
             ("Lighting Installation", "Indoor and outdoor lighting setups."),
             ("Maintenance", "Preventive checks for electrical systems.")),
            "homes and businesses", "dependable", 75, "Electrician",
        ),
        IndustrySpec(
            "restaurant", "Restaurant", "restaurant",
            ("restaurant", "grill", "kitchen", "bistro", "eatery", "diner", "cafe", "coffee", "bakery",
             "carinderia", "lechon", "pizza", "bbq", "food", "kainan", "tea"),
            (("Dine-In", "Enjoy freshly prepared dishes in a welcoming setting."),
             ("Takeout", "Order ahead and pick up your favorites."),
             ("Catering", "Food packages for parties, offices, and events."),
             ("Private Events", "Reserve space for celebrations and gatherings.")),
            "local diners and families", "warm", 60, "Restaurant",
            (("Do you accept reservations?", "Yes, call us to reserve a table, especially for large groups."),
             ("Do you offer catering?", "Contact us with your event date and headcount for catering options."),),
        ),
        IndustrySpec(
            "medical_clinic", "Medical Clinic", "medical",
            ("clinic", "medical", "health", "diagnostic", "diagnostics", "laboratory", "hospital", "pediatric",
             "maternity", "physician", "doctor"),
            (("General Consultation", "Check-ups and consultations for patients of all ages."),
             ("Laboratory Services", "Routine diagnostic tests and screenings."),
             ("Preventive Care", "Vaccinations and annual physical exams."),
             ("Medical Certificates", "Fit-to-work and school medical certificates.")),
            "patients and families", "caring", 90, "MedicalClinic",
            (("Do I need an appointment?", "Walk-ins are welcome, but booking ahead helps reduce waiting time."),
             ("Do you accept HMO?", "Please contact us to confirm which HMO providers are accredited."),),
        ),
        IndustrySpec(
            "dental", "Dental Clinic", "medical",
            ("dental", "dentist", "dentistry", "orthodontic", "orthodontics", "smile"),
            (("Dental Check-ups", "Routine examinations and cleaning."),
             ("Tooth Extraction", "Safe and comfortable extractions."),
             ("Orthodontics", "Braces and teeth alignment treatments."),
             ("Cosmetic Dentistry", "Whitening, veneers, and smile makeovers.")),
            "patients and families", "caring", 90, "Dentist",
            (("How often should I visit the dentist?", "Most patients benefit from a check-up and cleaning every six months."),),
        ),
        IndustrySpec(
            "legal", "Law Firm", "legal",
            ("law", "legal", "attorney", "attorneys", "lawyer", "lawyers", "notary", "notarial"),
            (("Legal Consultation", "Advice on your legal concerns and options."),
             ("Corporate Law", "Business registration, contracts, and compliance."),
             ("Family Law", "Annulment, custody, and estate matters."),
             ("Notarial Services", "Notarization of documents and affidavits.")),
            "individuals and businesses", "authoritative", 95, "LegalService",
            (("How do I schedule a consultation?", "Call or send us a message to set a consultation schedule."),),
        ),
        IndustrySpec(
            "accounting", "Accounting Firm", "legal",
            ("accounting", "accountant", "accountants", "cpa", "bookkeeping", "tax", "audit", "payroll"),
            (("Bookkeeping", "Accurate, up-to-date financial records."),
             ("Tax Compliance", "Preparation and filing of tax returns."),
             ("Business Registration", "Assistance with registration requirements."),
             ("Payroll Services", "Payroll processing and statutory contributions.")),
            "small and medium businesses", "professional", 85, "AccountingService",
        ),
        IndustrySpec(
            "education", "School", "education",
            ("school", "academy", "learning", "tutorial", "tutorials", "review", "college", "institute",
             "montessori", "preschool", "training"),
            (("Academic Programs", "Structured programs that build strong foundations."),
             ("Tutoring", "Personalized support for students."),
             ("Enrichment Classes", "Skills development beyond the classroom."),
             ("Enrollment Assistance", "Guidance through admission requirements.")),
            "students and parents", "encouraging", 70, "EducationalOrganization",
            (("When is enrollment?", "Contact us for the current enrollment schedule and requirements."),),
        ),
        IndustrySpec(
            "beauty", "Beauty & Wellness", "beauty",
            ("salon", "spa", "beauty", "barber", "barbershop", "nails", "nail", "aesthetic", "aesthetics",
             "massage", "wellness", "lashes"),
            (("Hair Services", "Cuts, color, and styling."),
             ("Nail Care", "Manicure and pedicure services."),
             ("Skin Care", "Facials and skin treatments."),
             ("Massage", "Relaxing massage and body treatments.")),
            "local clients", "friendly", 65, "BeautySalon",
            (("Do you accept walk-ins?", "Walk-ins are welcome; booking ahead guarantees your preferred time."),),
        ),
        IndustrySpec(
            "resort", "Resort & Hospitality", "resort",
            ("resort", "hotel", "inn", "lodge", "beach", "villa", "villas", "hostel", "pension", "staycation"),
            (("Accommodation", "Comfortable rooms for couples, families, and groups."),
             ("Day Tours", "Day-use access to our facilities."),
             ("Events & Functions", "Venue packages for weddings and celebrations."),
             ("Amenities", "Pools, dining, and leisure facilities.")),
            "travelers and families", "inviting", 90, "Resort",
            (("How do I book?", "Contact us with your preferred dates to check availability."),),
        ),
        IndustrySpec(
            "retail", "Retail Store", "retail",
            ("store", "shop", "trading", "mart", "minimart", "hardware", "boutique", "supply", "supplies",
             "merchandise", "pharmacy", "sari-sari"),
            (("In-Store Shopping", "Browse our selection in person."),
             ("Bulk Orders", "Volume pricing for businesses and resellers."),
             ("Delivery", "Delivery within our service area."),
             ("Special Orders", "Request items not currently in stock.")),
            "local shoppers", "friendly", 60, "Store",
        ),
        IndustrySpec(
            "auto_repair", "Auto Repair", "general",
            ("auto", "automotive", "motor", "motors", "car", "vulcanizing", "talyer", "motorcycle", "tire",
             "casa"),
            (("Preventive Maintenance", "Oil changes and scheduled maintenance."),
             ("Engine Repair", "Diagnosis and repair of engine problems."),
             ("Tire Services", "Tire replacement, vulcanizing, and alignment."),
             ("Aircon Service", "Car aircon cleaning and repair.")),
            "vehicle owners", "dependable", 70, "AutoRepair",
        ),
        IndustrySpec(
            "general", "Local Business", "general",
            (),
            (("Products & Services", "Quality offerings for our community."),
             ("Customer Support", "Friendly assistance when you need it."),
             ("Consultation", "Talk to us about what you need.")),
            "local customers", "friendly", 50, "LocalBusiness",
        ),
    ]
}

GENERAL = CATALOG["general"]

# Broad words that appear in many industries ("Dental Clinic", "Auto Supply Shop") weigh half,
# so the specific keyword decides.
GENERIC_KEYWORDS = frozenset({"clinic", "shop", "store", "supply", "supplies", "center", "food", "health",
                              "services", "trading", "kitchen", "review", "training"})

# Common FAQ entries applied to every industry (target: 10-20 entries per site).
COMMON_FAQ: tuple[tuple[str, str], ...] = (
    ("Where are you located?", "We serve customers in {city}{province_suffix}. Contact us for directions."),
    ("How can I contact {name}?", "You can reach us through the contact details on this website or the contact form."),
    ("What services do you offer?", "We offer {service_list}. Contact us to discuss your needs."),
    ("What are your business hours?", "Please contact us to confirm our current business hours."),
    ("How do I request a quotation?", "Send us a message through the contact form with your requirements."),
    ("Which areas do you serve?", "We primarily serve {city} and nearby areas."),
    ("What payment methods do you accept?", "Contact us to confirm the payment options currently available."),
    ("How soon can you respond to inquiries?", "We aim to respond to messages as soon as possible during business hours."),
)


def get_industry(key: str | None) -> IndustrySpec:
    return CATALOG.get(key or "", GENERAL)


def classify(name: str, hint: str | None = None, description: str | None = None) -> tuple[IndustrySpec, float]:
    """Return (industry, confidence). Explicit hints win, then keyword matches on name/description."""
    import re

    if hint:
        hint_key = re.sub(r"[^a-z0-9]+", "_", hint.lower()).strip("_")
        if hint_key in CATALOG:
            return CATALOG[hint_key], 0.95
        hint_tokens = set(re.findall(r"[a-z]+", hint.lower()))
        for spec in CATALOG.values():
            if hint_tokens & set(spec.keywords):
                return spec, 0.9

    text = f"{name} {description or ''}".lower()
    tokens = set(re.findall(r"[a-z\-]+", text))
    best: tuple[IndustrySpec, float] | None = None
    for spec in CATALOG.values():
        hits = sum(0.5 if t in GENERIC_KEYWORDS else 1.0 for t in tokens & set(spec.keywords))
        if hits and (best is None or hits > best[1]):
            best = (spec, hits)
    if best:
        return best[0], min(0.85, 0.6 + 0.1 * best[1])
    return GENERAL, 0.3
