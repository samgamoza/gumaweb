# Database Architecture

## Objective

Provide a scalable data foundation for GumaWeb.

---

# Core Databases

## PostgreSQL

System of record.

---

## Redis

Caching.

---

## Vector Database

Semantic search.

---

## Object Storage

Images and website artifacts.

---

# PostgreSQL Schema

## Businesses

```sql
CREATE TABLE businesses (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    industry TEXT,
    city TEXT,
    province TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    facebook TEXT,
    score INTEGER,
    created_at TIMESTAMP
);
```

---

## Generated Websites

```sql
CREATE TABLE websites (
    id UUID PRIMARY KEY,
    business_id UUID,
    template_id UUID,
    status VARCHAR(50),
    url TEXT,
    quality_score INTEGER,
    generated_at TIMESTAMP
);
```

---

## Claims

```sql
CREATE TABLE claims (
    id UUID PRIMARY KEY,
    business_id UUID,
    user_id UUID,
    status VARCHAR(50),
    verified_at TIMESTAMP
);
```

---

## Customers

```sql
CREATE TABLE customers (
    id UUID PRIMARY KEY,
    business_id UUID,
    plan VARCHAR(50),
    activated_at TIMESTAMP
);
```

---

## Outreach Events

```sql
CREATE TABLE outreach_events (
    id UUID PRIMARY KEY,
    business_id UUID,
    channel TEXT,
    event_type TEXT,
    timestamp TIMESTAMP
);
```

---

# Redis Usage

## Cached Records

```yaml
business_profiles:
generated_content:
generated_images:
seo_results:
```

---

# Vector Database

Store:

```yaml
embeddings:
business_descriptions:
industry_patterns:
competitor_data:
```
