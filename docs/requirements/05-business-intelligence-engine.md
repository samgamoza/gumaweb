# Business Intelligence Engine

## Objective

Transform sparse business data into structured profiles.

---

## Example Input

```yaml
name: ABC Construction
city: San Fernando
```

---

## Example Output

```yaml
industry: construction

services:
  - roofing
  - remodeling

target_audience: residential

brand_tone: professional

template: construction-v3
```

---

## AI Agents

### Industry Agent

Determines business category.

### Service Agent

Infers likely services.

### Brand Agent

Creates visual voice profile.

### SEO Agent

Generates market keywords.

---

## Output Schema

```json
{
  "industry": "",
  "services": [],
  "keywords": [],
  "brand_voice": ""
}
```
