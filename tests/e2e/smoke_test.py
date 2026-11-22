"""Post-deploy smoke test against a running GumaWeb stack (docker compose or Kubernetes).

    python tests/e2e/smoke_test.py --api http://localhost:8000 \
        --email admin@gumaweb.io --password 'ChangeMe!2026'

Creates one uniquely named business, generates + publishes its site, checks the
public endpoints, then archives the business. Exits non-zero on the first failure.
Only depends on httpx (installed with the backend requirements).
"""

from __future__ import annotations

import argparse
import sys
import uuid

import httpx


def check(condition: bool, message: str) -> None:
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    # Generous timeout: with AI enabled, synchronous generation waits on local inference.
    with httpx.Client(base_url=f"{args.api.rstrip('/')}/api/v1", timeout=300) as api:
        check(api.get("/health/ready").status_code == 200, "API ready (database reachable)")
        login = api.post("/auth/login", json={"email": args.email, "password": args.password})
        check(login.status_code == 200, "staff login")
        api.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

        check(len(api.get("/templates").json()) > 0, "templates seeded")
        suffix = uuid.uuid4().hex[:6]
        business = api.post("/businesses", json={
            "name": f"Smoke Test Bakery {suffix}", "city": "Angeles City", "phone": "0917 555 0199",
            "email": f"smoke-{suffix}@gmail.com",
        })
        check(business.status_code == 201, "create business")
        business_id = business.json()["id"]
        check(business.json()["generate_candidate"], "business scored as generate candidate")

        website = api.post("/websites/generate", json={"business_id": business_id, "publish": True})
        check(website.status_code == 201 and website.json()["status"] == "published", "generate + publish site")
        subdomain = website.json()["subdomain"]

        info = api.get(f"/public/sites/{subdomain}")
        check(info.status_code == 200 and not info.json()["is_claimed"], "public claim page data")
        if website.json()["url"]:
            page = httpx.get(website.json()["url"], timeout=30, follow_redirects=True)
            check(page.status_code == 200 and "Claim this website" in page.text, "published site served")

        check(api.get("/analytics/overview").status_code == 200, "analytics overview")
        api.delete(f"/businesses/{business_id}")
        api.post(f"/websites/{website.json()['id']}/unpublish")
        print("Smoke test completed.")


if __name__ == "__main__":
    main()
