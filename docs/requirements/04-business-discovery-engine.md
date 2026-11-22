# Business Discovery Engine

## Objective

Identify businesses that:

- Lack websites
- Have reachable contact information
- Are currently active

---

## Inputs

### Business Directories

- DTI
- Chamber directories
- Yellow Pages

### Search Engines

- Google Business Profiles

### Social Media

- Facebook Pages

---

## Pipeline

```text
Crawl
 ↓
Normalize
 ↓
Deduplicate
 ↓
Enrich
 ↓
Score
```

---

## Database Record

```json
{
  "business_id": "",
  "name": "",
  "industry": "",
  "city": "",
  "phone": "",
  "email": "",
  "facebook": "",
  "website": ""
}
```

---

## Opportunity Scoring

Variables:

- Website Missing
- Domain Missing
- Facebook Presence
- Contact Availability
- Industry Value

Output:

```yaml
score: 92
generate_candidate: true
```
