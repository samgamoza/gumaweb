# API Specifications

## Objective

Expose platform functionality through APIs.

---

# API Gateway

```text
api.gumaweb.io
```

---

# Authentication

```yaml
oauth2:
jwt:
api_keys:
```

---

# Business API

## Get Business

```http
GET /api/businesses/{id}
```

---

## Create Business

```http
POST /api/businesses
```

---

# Website API

## Generate Website

```http
POST /api/websites/generate
```

---

## Regenerate Website

```http
POST /api/websites/{id}/regenerate
```

---

## Get Website

```http
GET /api/websites/{id}
```

---

# Claim API

## Start Claim

```http
POST /api/claims
```

---

## Verify Claim

```http
POST /api/claims/verify
```

---

# Customer API

## Dashboard

```http
GET /api/customer/dashboard
```

---

## Update Content

```http
PUT /api/customer/content
```

---

# Outreach API

## Send Campaign

```http
POST /api/outreach/campaign
```

---

# Event System

Every major operation emits events.

Example:

```yaml
website_generated:
website_published:
claim_started:
claim_completed:
customer_upgraded:
```
