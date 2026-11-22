def test_login_me_refresh(client, admin_headers):
    me = client.get("/api/v1/auth/me", headers=admin_headers)
    assert me.status_code == 200 and me.json()["role"] == "admin"
    login = client.post("/api/v1/auth/login", json={"email": "admin@test.io", "password": "Password!2026"}).json()
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 200
    # refresh tokens cannot be used as access tokens
    bad = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login['refresh_token']}"})
    assert bad.status_code == 401


def test_bad_login_is_rejected_and_audited(client, admin_headers):
    response = client.post("/api/v1/auth/login", json={"email": "admin@test.io", "password": "wrong"})
    assert response.status_code == 401
    logs = client.get("/api/v1/admin/audit-logs?action=auth.login_failed", headers=admin_headers).json()
    assert logs["total"] == 1


def test_unauthenticated_and_rbac(client, readonly_headers):
    assert client.get("/api/v1/businesses").status_code == 401
    assert client.get("/api/v1/businesses", headers=readonly_headers).status_code == 200
    created = client.post("/api/v1/businesses", json={"name": "Nope Co"}, headers=readonly_headers)
    assert created.status_code == 403


def test_create_business_scores_and_dedupes(client, operator_headers):
    payload = {"name": "ABC Construction Inc.", "city": "San Fernando", "phone": "0917 555 0101",
               "email": "abc@gmail.com", "facebook": "facebook.com/abc"}
    response = client.post("/api/v1/businesses", json=payload, headers=operator_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["slug"] == "abc-construction-inc"
    assert body["phone"] == "639175550101"
    assert body["status"] == "scored" and body["generate_candidate"] is True and body["score"] >= 90

    duplicate = client.post("/api/v1/businesses", json={**payload, "name": "abc construction"},
                            headers=operator_headers)
    assert duplicate.status_code == 409 and duplicate.json()["error"] == "duplicate_business"


def test_import_csv_and_filters(client, operator_headers):
    csv = (
        "business_name,city,phone,email,website\n"
        "Glow Beauty Salon,Baguio,0917 555 0107,glow@gmail.com,\n"
        "Glow Beauty Salon,Baguio,0917 555 0107,glow@gmail.com,\n"
        "Online Corp,Makati,0917 555 0110,info@online.ph,https://online.ph\n"
        ",Nowhere,,,\n"
    )
    run = client.post("/api/v1/businesses/import", files={"file": ("batch.csv", csv, "text/csv")},
                      headers=operator_headers)
    assert run.status_code == 201, run.text
    assert run.json() | {"errors": None} == run.json() | {
        "total_records": 4, "created_count": 2, "duplicate_count": 1, "error_count": 1, "errors": None}

    candidates = client.get("/api/v1/businesses?generate_candidate=true", headers=operator_headers).json()
    assert [b["name"] for b in candidates["items"]] == ["Glow Beauty Salon"]
    search = client.get("/api/v1/businesses?q=online", headers=operator_headers).json()
    assert search["total"] == 1 and search["items"][0]["generate_candidate"] is False


def test_profile_and_archive(client, operator_headers):
    business = client.post("/api/v1/businesses", json={"name": "Bella Vista Dental Clinic", "city": "Malolos",
                                                       "phone": "09175550103"}, headers=operator_headers).json()
    profile = client.post(f"/api/v1/businesses/{business['id']}/profile", headers=operator_headers).json()
    assert profile["industry"] == "dental" and profile["category"] == "medical"
    updated = client.patch(f"/api/v1/businesses/{business['id']}/profile",
                           json={"services": ["Braces", "Cleaning"]}, headers=operator_headers).json()
    assert updated["services"] == ["Braces", "Cleaning"] and updated["source"] == "manual"

    assert client.delete(f"/api/v1/businesses/{business['id']}", headers=operator_headers).status_code == 204
    archived = client.get(f"/api/v1/businesses/{business['id']}", headers=operator_headers).json()
    assert archived["status"] == "archived" and archived["generate_candidate"] is False
    listing = client.get("/api/v1/businesses", headers=operator_headers).json()
    assert listing["total"] == 0


def test_admin_user_management(client, admin_headers, operator_headers):
    created = client.post("/api/v1/admin/users", json={"email": "ops2@test.io", "password": "LongPassword1",
                                                       "role": "operator"}, headers=admin_headers)
    assert created.status_code == 201
    assert client.get("/api/v1/admin/users", headers=operator_headers).status_code == 403
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    self_demote = client.patch(f"/api/v1/admin/users/{me['id']}", json={"role": "readonly"}, headers=admin_headers)
    assert self_demote.status_code == 422
