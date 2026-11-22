"""End-to-end MVP flow: discover → generate → publish → claim → verify → customer portal."""

import re

from app.services.providers import providers


def _verification_token() -> str:
    message = providers.email.outbox[-1]  # type: ignore[attr-defined]
    return re.search(r"token=([\w-]+)", message.text).group(1)


def test_templates_seeded(client, admin_headers):
    templates = client.get("/api/v1/templates", headers=admin_headers).json()
    assert len(templates) == 14
    components = client.get("/api/v1/templates/components", headers=admin_headers).json()
    assert {"hero-modern", "services-cards", "faq-standard", "contact-split"} <= {c["slug"] for c in components}


def test_generate_and_publish(client, admin_headers, published_site, sites_dir):
    website = published_site["website"]
    assert website["status"] == "published" and website["version"] == 1
    assert website["subdomain"] == "santos-plumbing-services"
    assert website["quality_score"] == 100

    blueprint = client.get(f"/api/v1/websites/{website['id']}/blueprint", headers=admin_headers).json()["blueprint"]
    # plumbing businesses are spread deterministically across the plumbing-capable templates
    assert blueprint["template"]["slug"] in {"plumbing-modern-v1", "contractor-modern-v1"}
    slugs = [p["slug"] for p in blueprint["pages"]]
    assert slugs[0] == "home" and {"about", "services", "faq", "contact"} <= set(slugs)

    home = (sites_dir / website["subdomain"] / "index.html").read_text(encoding="utf-8")
    assert "Trusted Plumbing Services in Angeles City" in home and "Claim this website" in home
    assert (sites_dir / website["subdomain"] / "sitemap.xml").exists()

    deployments = client.get(f"/api/v1/websites/{website['id']}/deployments", headers=admin_headers).json()
    assert deployments[0]["status"] == "succeeded" and deployments[0]["file_count"] >= 8

    business = client.get(f"/api/v1/businesses/{published_site['business']['id']}", headers=admin_headers).json()
    assert business["status"] == "published"

    again = client.post("/api/v1/websites/generate", json={"business_id": business["id"]}, headers=admin_headers)
    assert again.status_code == 409


def test_claim_email_flow_to_customer_portal(client, published_site, sites_dir):
    subdomain = published_site["website"]["subdomain"]
    info = client.get(f"/api/v1/public/sites/{subdomain}").json()
    assert info["business_name"] == "Santos Plumbing Services" and info["masked_email"].startswith("s*")

    started = client.post("/api/v1/claims", json={
        "subdomain": subdomain, "claimant_name": "Jose Santos", "claimant_email": "santos.plumbing@gmail.com"})
    assert started.status_code == 201, started.text
    assert started.json()["status"] == "pending_verification"

    token = _verification_token()
    missing_password = client.post("/api/v1/claims/verify", json={"token": token})
    assert missing_password.status_code == 422 and missing_password.json()["error"] == "password_required"

    verified = client.post("/api/v1/claims/verify", json={"token": token, "password": "OwnerPass!2026"})
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "approved"
    headers = {"Authorization": f"Bearer {verified.json()['tokens']['access_token']}"}

    # Token is single use
    assert client.post("/api/v1/claims/verify", json={"token": token}).status_code == 404

    dashboard = client.get("/api/v1/customer/dashboard", headers=headers).json()
    assert dashboard["plan"]["code"] == "free"
    assert dashboard["website"]["version"] == 2  # republished without the claim banner
    home = (sites_dir / subdomain / "index.html").read_text(encoding="utf-8")
    assert "Claim this website" not in home

    # Second claim is refused
    again = client.post("/api/v1/claims", json={
        "subdomain": subdomain, "claimant_name": "Someone", "claimant_email": "x@gmail.com"})
    assert again.status_code == 409

    # Customer edits content -> site republished
    edit = client.put("/api/v1/customer/content", headers=headers, json={
        "section_key": "hero", "updates": {"headline": "Angeles City's Friendly Plumbers"}})
    assert edit.status_code == 200, edit.text
    assert "Angeles City&#39;s Friendly Plumbers" in (sites_dir / subdomain / "index.html").read_text(encoding="utf-8")
    hero = next(b for b in edit.json() if b["section_key"] == "hero")
    assert hero["source"] == "customer"

    bad = client.put("/api/v1/customer/content", headers=headers, json={
        "section_key": "hero", "updates": {"headline": ""}})
    assert bad.status_code == 422

    # Profile update syncs contact info
    profile = client.put("/api/v1/customer/profile", headers=headers, json={"phone": "0918 777 1234"})
    assert profile.status_code == 200 and profile.json()["business"]["phone"] == "639187771234"
    assert "+639187771234" in (sites_dir / subdomain / "contact" / "index.html").read_text(encoding="utf-8")

    # Upgrade plan
    upgraded = client.post("/api/v1/customer/subscription", headers=headers, json={"plan": "professional"})
    assert upgraded.status_code == 200 and upgraded.json()["plan_code"] == "professional"
    assert client.get("/api/v1/customer/subscription", headers=headers).json()["plan_code"] == "professional"

    # Customers cannot reach staff APIs
    assert client.get("/api/v1/businesses", headers=headers).status_code == 403


def test_regeneration_preserves_customer_content(client, admin_headers, published_site):
    website_id = published_site["website"]["id"]
    client.put(f"/api/v1/websites/{website_id}/content", headers=admin_headers, json={
        "section_key": "about", "updates": {"company_story": "Family-run since we opened our doors."},
        "republish": False})
    regenerated = client.post(f"/api/v1/websites/{website_id}/regenerate", json={}, headers=admin_headers)
    assert regenerated.status_code == 200 and regenerated.json()["version"] == 2
    blocks = {b["section_key"]: b for b in client.get(f"/api/v1/websites/{website_id}/content",
                                                      headers=admin_headers).json()}
    assert blocks["about"]["content"]["company_story"] == "Family-run since we opened our doors."

    reset = client.post(f"/api/v1/websites/{website_id}/regenerate", json={"reset_content": True},
                        headers=admin_headers)
    assert reset.status_code == 200
    blocks = {b["section_key"]: b for b in client.get(f"/api/v1/websites/{website_id}/content",
                                                      headers=admin_headers).json()}
    assert blocks["about"]["source"] == "template"


def test_high_risk_claim_goes_to_manual_review(client, admin_headers, published_site):
    subdomain = published_site["website"]["subdomain"]
    client.post("/api/v1/claims", json={
        "subdomain": subdomain, "claimant_name": "Rival", "claimant_email": "rival@mailinator.com"})
    token = _verification_token()
    verified = client.post("/api/v1/claims/verify", json={"token": token, "password": "RivalPass!2026"}).json()
    assert verified["status"] == "manual_review" and verified["tokens"] is None

    pending = client.get("/api/v1/claims?status_filter=manual_review", headers=admin_headers).json()
    assert pending["total"] == 1
    claim_id = pending["items"][0]["id"]
    rejected = client.post(f"/api/v1/claims/{claim_id}/reject", json={"notes": "No proof"}, headers=admin_headers)
    assert rejected.json()["status"] == "rejected"


def test_business_identity_claim_approved_by_staff(client, admin_headers, published_site):
    subdomain = published_site["website"]["subdomain"]
    client.post("/api/v1/claims", json={
        "subdomain": subdomain, "claimant_name": "Jose", "claimant_email": "jose@santos.ph",
        "method": "business_identity", "evidence": {"dti_registration": "1234567"}})
    verified = client.post("/api/v1/claims/verify",
                           json={"token": _verification_token(), "password": "OwnerPass!2026"}).json()
    assert verified["status"] == "manual_review"
    approved = client.post(f"/api/v1/claims/{verified['claim_id']}/approve", json={}, headers=admin_headers)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    login = client.post("/api/v1/auth/login", json={"email": "jose@santos.ph", "password": "OwnerPass!2026"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/customer/dashboard", headers=headers).status_code == 200


def test_sms_otp_attempts_are_limited(client, published_site, settings):
    subdomain = published_site["website"]["subdomain"]
    started = client.post("/api/v1/claims", json={
        "subdomain": subdomain, "claimant_name": "Jose", "claimant_email": "jose2@gmail.com",
        "claimant_phone": "0917 555 0102", "method": "sms"}).json()
    otp = re.search(r"\d{6}", providers.sms.outbox[-1][1]).group(0)  # type: ignore[attr-defined]
    wrong = "000000" if otp != "000000" else "111111"
    for _ in range(settings.claim_max_verification_attempts):
        assert client.post("/api/v1/claims/verify",
                           json={"claim_id": started["claim_id"], "otp": wrong}).status_code == 422
    locked = client.post("/api/v1/claims/verify", json={"claim_id": started["claim_id"], "otp": otp,
                                                        "password": "OwnerPass!2026"})
    assert locked.status_code == 403


def test_claim_rate_limit_and_honeypot(client, published_site, settings):
    subdomain = published_site["website"]["subdomain"]
    bot = client.post("/api/v1/claims", json={"subdomain": subdomain, "claimant_name": "Bot",
                                              "claimant_email": "bot@gmail.com", "website": "spam"})
    assert bot.status_code == 422
    statuses = [
        client.post("/api/v1/claims", json={"subdomain": subdomain, "claimant_name": "Spam",
                                            "claimant_email": f"s{i}@gmail.com"}).status_code
        for i in range(settings.claim_rate_limit_per_hour + 1)
    ]
    assert statuses[-1] == 429


def test_unpublish(client, admin_headers, published_site, sites_dir):
    website = published_site["website"]
    response = client.post(f"/api/v1/websites/{website['id']}/unpublish", headers=admin_headers)
    assert response.json()["status"] == "unpublished"
    assert not (sites_dir / website["subdomain"]).exists()
    assert client.get(f"/api/v1/public/sites/{website['subdomain']}").status_code == 404
