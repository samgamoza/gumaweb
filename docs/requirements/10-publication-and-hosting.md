# Publication and Hosting

## Objective

Deploy generated websites at scale with minimal infrastructure cost.

---

# Hosting Model

Use static website hosting.

Never deploy application servers unless needed.

---

# URL Strategy

```text
business-name.gumaweb.io
```

Examples:

```text
abc-plumbing.gumaweb.io

xyz-construction.gumaweb.io

smith-dental.gumaweb.io
```

---

# Deployment Pipeline

```text
Build Website
       ↓
Upload Artifacts
       ↓
Generate Metadata
       ↓
Create DNS
       ↓
Publish
```

---

# Storage Architecture

```yaml
provider: object_storage

assets: images

artifacts: websites

logs: deployment_logs
```

---

# CDN Layer

Responsibilities:

- caching
- compression
- edge delivery

---

# SEO Services

Automatically generate:

```yaml
robots_txt:
sitemap_xml:

schema_markup:
```

---

# Monitoring

Track:

```yaml
uptime:
traffic:
claims:
conversion:
```

---

# Regeneration Support

Website can be regenerated if:

```yaml
new_data_found:
template_updated:
seo_updated:
```
