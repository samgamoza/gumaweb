"""Offline fixture discovery for tests and local demos: fictional listings, no network.

Ported from guma_os `ph-fixtures.ts`. Every listing is invented: 555 phone numbers and `.example`
websites (a reserved TLD), so nothing downstream, such as website enrichment, can ever reach a real
business from fixture data.
"""

from __future__ import annotations

from app.domains.business_discovery.providers.base import DiscoveredBusiness, DiscoveryQuery


def _b(name: str, category: str, city: str, province: str, phone: str, website: str | None, rating: float,
       reviews: int, n: int) -> DiscoveredBusiness:
    return DiscoveredBusiness(name=name, source="fixture", category=category, city=city, province=province,
                              phone=phone, website=website, rating=rating, review_count=reviews,
                              place_id=f"fixture:{n}")


FIXTURE_BUSINESSES: tuple[DiscoveredBusiness, ...] = (
    _b("Aurora Dental Studio", "Dental Clinic", "Quezon City", "Metro Manila", "+63 2 555 0147", None, 4.8, 214, 1),
    _b("Kanto Freestyle Breakfast", "Restaurant", "Makati", "Metro Manila", "+63 2 555 0192", None, 4.6, 512, 2),
    _b("Cebu Auto Kings", "Auto Repair", "Cebu City", "Cebu", "+63 32 555 0110", None, 4.5, 98, 3),
    _b("Bloom and Co. Salon", "Salon", "Taguig", "Metro Manila", "+63 2 555 0165", "https://bloomandco.example",
       4.7, 176, 4),
    _b("Davao Sunrise Bakery", "Bakery", "Davao City", "Davao del Sur", "+63 82 555 0133", None, 4.4, 143, 5),
    _b("Iloilo Fit Hub", "Fitness Gym", "Iloilo City", "Iloilo", "+63 33 555 0178", "https://iloilofit.example",
       4.3, 64, 6),
    _b("Pasig VetCare Clinic", "Veterinary Clinic", "Pasig", "Metro Manila", "+63 2 555 0121", None, 4.6, 121, 7),
    _b("Baguio Brew Coffee", "Coffee Shop", "Baguio", "Benguet", "+63 74 555 0144", None, 4.5, 208, 8),
    _b("CDO Hardware Depot", "Hardware Store", "Cagayan de Oro", "Misamis Oriental", "+63 88 555 0155", None,
       4.1, 33, 9),
    _b("Bacolod Sweet Escape", "Bakery", "Bacolod", "Negros Occidental", "+63 34 555 0166", None, 4.4, 89, 10),
    _b("QC Print Express", "Printing Services", "Quezon City", "Metro Manila", "+63 2 555 0199", None, 4.2, 52, 11),
    _b("Southside Pharmacy", "Pharmacy", "Davao City", "Davao del Sur", "+63 82 555 0157", None, 4.0, 44, 12),
)


class FixtureDiscoveryProvider:
    id = "fixture"
    name = "Fixture (fictional sample listings)"

    def __init__(self, data: tuple[DiscoveredBusiness, ...] = FIXTURE_BUSINESSES) -> None:
        self.data = data

    def discover(self, query: DiscoveryQuery) -> list[DiscoveredBusiness]:
        category = (query.category or "").lower()
        city = (query.city or "").lower()
        free = (query.query or "").lower()

        def wanted(b: DiscoveredBusiness) -> bool:
            if free:
                return free in f"{b.name} {b.category} {b.city}".lower()
            return (not category or category in (b.category or "").lower()) and (
                not city or city in (b.city or "").lower())

        return [b for b in self.data if wanted(b)][: query.limit]
