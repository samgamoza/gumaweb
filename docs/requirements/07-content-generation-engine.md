# Content Generation Engine

## Objective

Generate business-specific content while maintaining low inference costs and high consistency.

The engine should enhance templates, not create websites from scratch.

---

# Design Principles

## Template First

Templates define structure.

AI generates content only.

```text
Template
     +
Business Profile
     +
AI Content
     =
Website
```

---

## Cost Optimization

Avoid repeated generation.

Use caching.

Store generated content.

```yaml
content_cache:
  hero_text:
  about_section:
  faq_items:
  seo_description:
```

---

# Service Architecture

```text
Business Profile
          ↓
Content Request
          ↓
Prompt Builder
          ↓
LLM Router
          ↓
Content Validator
          ↓
Content Cache
          ↓
Website Builder
```

---

# AI Models

## Primary

```yaml
model: qwen-coder
```

Responsibilities:

- business copywriting
- page content
- faq generation
- service descriptions

---

## Secondary

```yaml
model: deepseek
```

Responsibilities:

- review
- rewriting
- compression

---

# Hero Content Generation

## Input

```yaml
industry: plumbing

city: angeles city

services:
  - repairs
  - installations
```

---

## Output

```yaml
headline: Trusted Plumbing Services in Angeles City

subheadline: Fast and reliable plumbing solutions
  for homes and businesses.

cta: Request a Free Consultation
```

---

# About Page Generator

Produces:

```yaml
company_story:
mission_statement:
service_summary:
```

---

# FAQ Generator

Produces:

```yaml
faq:
  - question:
    answer:

  - question:
    answer:
```

Target:

10–20 FAQ entries.

---

# SEO Content Generator

Produces:

```yaml
page_title:
meta_description:

keywords:

local_keywords:
```

---

# Review Pipeline

```text
Generation
      ↓
Grammar Check
      ↓
Duplicate Detection
      ↓
AI Rewrite
      ↓
Approval
```

---

# Content Quality Rules

Minimum requirements:

```yaml
grammar_score: 95

seo_score: 85

readability: 80

spam_score: <10
```
