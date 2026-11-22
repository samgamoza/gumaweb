# Kubernetes Deployment

## Objective

Provide highly scalable operations.

---

# Cluster Layout

```text
guma-prod

├── ingress
├── api
├── websites
├── ai
├── monitoring
└── storage
```

---

# Namespace Structure

```yaml
guma-core:
guma-ai:
guma-websites:
guma-monitoring:
guma-system:
```

---

# Core Services

## API Gateway

Handles routing.

---

## Website Builder

Website generation.

---

## Outreach Engine

Campaign execution.

---

## Claim Service

Claim workflows.

---

## AI Services

Inferencing workloads.

---

# Storage

```yaml
postgres:
redis:
vector_db:
object_storage:
```

---

# Ingress

```yaml
nginx:
tls:
cert_manager:
```

---

# Monitoring

```yaml
prometheus:
grafana:
loki:
alertmanager:
```

---

# Helm Structure

```text
charts/

api/
builder/
ai/
outreach/
portal/
monitoring/
```

---

# Scaling Strategy

Horizontal scaling:

```yaml
api: autoscale

outreach: autoscale

website_builder: autoscale
```
