# Website Assembly Pipeline

## Objective

Convert business profiles into production-ready static websites.

---

# Workflow

```text
Business Profile
         ↓
Template Selection
         ↓
Component Selection
         ↓
Content Injection
         ↓
Image Assignment
         ↓
SEO Generation
         ↓
Quality Validation
         ↓
Build Website
```

---

# Assembly Engine

## Inputs

```yaml
business_profile:
template:
content:
images:
seo:
```

---

## Outputs

```yaml
website:
status:
artifact_path:
score:
```

---

# Template Resolution

Example:

```yaml
industry: plumbing

template: plumbing-modern-v2
```

---

# Component Resolution

```yaml
components: hero-modern-2
  services-grid-1
  faq-standard-1
  cta-premium-1
```

---

# Page Generation

Standard Pages

```yaml
home:
about:
services:
faq:
contact:
```

Optional Pages

```yaml
projects:
gallery:
pricing:
team:
```

---

# Build System

Recommended:

```yaml
framework: astro
```

Output:

```yaml
static_html:

optimized_assets:

sitemap:

rss:
```

---

# Build Validation

Checks:

```yaml
pages_exist:
layout_valid:
asset_valid:
seo_valid:
```
