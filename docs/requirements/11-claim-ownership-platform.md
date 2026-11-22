# Claim Ownership Platform

## Objective

Convert generated websites into customers.

---

# Core Philosophy

The website is the acquisition vehicle.

---

# Claim Flow

```text
Website Published
        ↓
Business Visits Site
        ↓
Claim Request
        ↓
Verification
        ↓
Ownership Transfer
        ↓
Customer Activation
```

---

# Claim Banner

Displayed on generated websites.

Example:

```text
Own this business?

Claim this website
and manage it for free.
```

---

# Claim Service

Responsibilities:

```yaml
claim_request:
verification:
ownership_assignment:
audit_logging:
```

---

# Verification Methods

## Email

```text
Verification Link
```

---

## SMS

```text
One Time Password
```

---

## Business Identity

Possible verification:

- business registration
- official domain
- social page ownership

---

# Claim Database

```sql
claims

claim_id
business_id
user_id
status
created_at
verified_at
```

---

# Ownership Transfer

Upon verification:

```text
Website
      ↓
Customer Account
      ↓
Admin Portal
```

---

# Abuse Protection

Checks:

```yaml
rate_limit:
duplicate_claim:
risk_score:
manual_review:
```
