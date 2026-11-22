# Platform Architecture

## High-Level Design

```text
Business Discovery
        ↓
Business Intelligence
        ↓
Template Factory
        ↓
Content Generation
        ↓
Image Factory
        ↓
QA Validation
        ↓
Website Publishing
        ↓
Claim Platform
        ↓
Customer Portal
```

---

# Core Services

## Discovery Service

Responsible for collecting target businesses.

## Intelligence Service

Responsible for classifying businesses.

## Factory Service

Responsible for website creation.

## Publishing Service

Responsible for deployment.

## Claim Service

Responsible for ownership transfer.

## Outreach Service

Responsible for customer acquisition.

---

## Design Principles

### Static First

Generate static websites.

### AI Assisted

Use AI for decisions.

Avoid AI for repetitive rendering.

### Cost Optimized

Minimize token usage.

Maximize template reuse.

### Horizontal Scale

Every service is independently scalable.
