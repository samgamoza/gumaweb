# Deployment Guide

Target: self-hosted Kubernetes (doc 18). Everything runs on Guma infrastructure: PostgreSQL, Redis,
MinIO, a self-hosted MTA, and later vLLM on GPU nodes. There are no paid SaaS dependencies.

## 1. Cluster prerequisites

| Component | Purpose |
|---|---|
| ingress-nginx | Routing for `api.`, `app.` and `*.gumaweb.io` |
| cert-manager + a **DNS-01** ClusterIssuer (`letsencrypt-dns01`) | Wildcard TLS for every generated site |
| A storage class (Ceph/Longhorn); RWX if `storageBackend=local` | PVCs |
| kube-prometheus-stack, Loki + Alloy | Monitoring (values in `kubernetes/monitoring/`) |
| CloudNativePG operator *(production)* | HA PostgreSQL with PITR backups |
| NVIDIA device plugin *(Phase 2)* | GPU scheduling for `guma-ai` |

DNS: `api.gumaweb.io`, `app.gumaweb.io` and the wildcard `*.gumaweb.io` → ingress load balancer IP.

## 2. Build images

```bash
REGISTRY=registry.guma.local TAG=0.1.0 API_URL=https://api.gumaweb.io scripts/build-images.sh --push
```

* `gumaweb/api` is built from the repo root. It bundles `/templates`, runs as non-root UID 10001, and serves gunicorn with uvicorn workers.
* `gumaweb/portal` is the Next.js standalone build. `NEXT_PUBLIC_API_URL` is baked in at build time.

## 3. Namespaces and secrets

```bash
kubectl apply -f kubernetes/namespaces.yaml        # guma-core, guma-ai, guma-websites, guma-monitoring, guma-system
cp kubernetes/secrets/gumaweb-secrets.example.yaml /secure/place/gumaweb-secrets.yaml   # fill in, never commit
kubectl -n guma-core apply -f /secure/place/gumaweb-secrets.yaml
```

Prefer External Secrets / Sealed Secrets / Vault. Required keys: `JWT_SECRET_KEY` (≥ 48 random bytes),
`DATABASE_URL`, `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `FIRST_ADMIN_EMAIL` and
`FIRST_ADMIN_PASSWORD` (optionally `SMTP_USER` / `SMTP_PASSWORD`). The API refuses to start in production
with the default JWT secret.

## 4. Install with Helm

```bash
helm lint kubernetes/helm/gumaweb -f kubernetes/helm/gumaweb/values-prod.yaml
TAG=0.1.0 scripts/deploy.sh                          # helm upgrade --install ... -n guma-core --wait
```

What the chart deploys (`kubernetes/helm/gumaweb/templates/`):

| Template | Resources |
|---|---|
| `config.yaml` | ConfigMap (env), nginx site config, Secret (only when `secrets.existingSecret` is empty) |
| `api.yaml` / `portal.yaml` / `sites.yaml` | Deployments + Services. Restricted security context, read-only root FS, probes |
| `jobs.yaml` | Migration Job (Helm hook: `alembic upgrade head && seed`), CronJobs: **outreach dispatch** (every 15 min), **factory batch** (nightly `enqueue --limit 1000`) |
| `worker.yaml` | Factory workers (doc 18 "builder"): drain `factory_jobs`, relay events to Redis; HPA on CPU; 120 s graceful shutdown finishes the current job |
| `datastores.yaml` | PostgreSQL (pgvector), Redis and MinIO StatefulSets, plus a MinIO bucket Job. Each can be toggled. |
| `ingress.yaml` | Ingress with app TLS and a wildcard TLS secret |
| `scaling.yaml` | HPAs (api, portal, sites) and PodDisruptionBudgets |
| `networkpolicy.yaml` | Default-deny ingress; allows the ingress controller, monitoring and in-release access to data stores |
| `monitoring.yaml` | ServiceMonitor (`/metrics`) and PrometheusRules (5xx rate, p95 latency, API down, failed jobs) |
| `ai.yaml` | vLLM (OpenAI-compatible) in `guma-ai`. Disabled by default. |

### Storage modes for published sites

| `config.storageBackend` | How it works | When |
|---|---|---|
| `local` (default) | API and CronJobs write to an **RWX PVC**; nginx serves it read-only | Small clusters with CephFS/NFS/Longhorn RWX |
| `s3` (prod values) | API writes to MinIO (`_releases/` + live prefix); nginx proxies `<sub>.gumaweb.io/*` → `bucket/<sub>/*` with a proxy cache | Production scale; put a CDN in front of the `sites` service |

## 5. After the first install

1. `kubectl -n guma-core get jobs` shows the migration job succeeded.
2. Sign in at `https://app.gumaweb.io` with the bootstrap admin and **change the password**. Create named
   operator accounts (Admin API `POST /admin/users`) instead of sharing the admin account.
3. Import a directory export (Businesses → *Import CSV*), check the scores, then let the nightly factory
   batch run, or click *Generate & publish*.
4. Run the smoke test: `python tests/e2e/smoke_test.py --api https://api.gumaweb.io --email ... --password ...`

## 6. Operations

* **Scaling:** api, portal, sites and **worker** autoscale on CPU. The nightly CronJob only enqueues; workers claim
  jobs with `SKIP LOCKED`, so throughput scales with `worker.autoscaling.maxReplicas`. With AI enabled, throughput is
  bounded by GPU inference, so size vLLM replicas accordingly.
* **Rollback (app):** `helm rollback gumaweb <rev>`. Migrations are expand/contract, so the previous
  version runs against the newer schema.
* **Rollback (a site):** the last 3 releases of every site stay under `_releases/<sub>/v<n>/`.
  Republishing creates a new version.
* **Logs:** JSON logs on stdout (`LOG_JSON=true`), collected by Alloy into Loki (30-day retention).
* **Metrics:** `gumaweb_http_requests_total` and `gumaweb_http_request_duration_seconds` (by method, route, status).

## 7. Backup and disaster recovery (doc 19: RPO 1 h, RTO 4 h)

| Data | Mechanism |
|---|---|
| PostgreSQL | CloudNativePG continuous WAL archiving + daily base backups to object storage (RPO minutes). `scripts/backup-db.sh` for ad-hoc logical dumps. |
| Object storage (sites, assets) | MinIO bucket versioning + daily site replication to a second site |
| Configuration | Git (chart and values) plus the secrets manager's own backup |

Restore drill (quarterly): restore PostgreSQL into a scratch namespace, point a staging release at it, run
the smoke test, and time it against the 4-hour RTO.

## 8. Enabling AI (Phase 2)

1. Label GPU nodes and install the NVIDIA device plugin.
2. Set `ai.enabled=true` (vLLM serving `ai.model`, default `Qwen/Qwen2.5-14B-Instruct`, in `guma-ai`) and
   `config.aiEnabled=true`. Optionally point `config.llmSecondaryModel` at a DeepSeek deployment for review.
3. Images: keep `config.imageBackend=procedural` (zero cost), or set `http` + `config.imageApiUrl` to a FLUX/SDXL
   server exposing `/images/generations`. Failures fall back to procedural art automatically.
4. Watch **Admin → Overview → AI factory** (acceptance per model, tokens per site) and each website's
   `quality_report.content_notes` to tune prompts and model size. Gates are never relaxed per model.

## 8b. Custom domains and business email (Phase 5)

**Custom domains.** Run Caddy (`infrastructure/caddy/Caddyfile`) on a public IP in front of the sites service, with
`GUMAWEB_TLS_ASK_URL=http://<api-service>:8000/api/v1/public/domains/tls-check`. Publish `domains.gumaweb.io` →
that IP and set `CUSTOM_DOMAIN_CNAME_TARGET=domains.gumaweb.io` and `CUSTOM_DOMAIN_IPV4=<ip>`, so owners get the
right records. Certificates are issued on first visit, only for verified domains we serve. Persist Caddy's
`/data` volume, or certificates are re-issued and you hit CA rate limits.

**Business email.** Run Stalwart (`stalwartlabs/stalwart:v1`) with persistent `/etc/stalwart` and
`/var/lib/stalwart`, its admin port reachable only from the API. Open 25/465/993 publicly. Name it with
`mail.gumaweb.io` (A record and reverse DNS/PTR from your provider; many receivers reject mail without one).
1. Start it once with `STALWART_RECOVERY_ADMIN=admin:<password>`.
2. Run `python -m app.cli mail-bootstrap --hostname mail.gumaweb.io --domain gumaweb.io`. It prints the admin
   account once.
3. Store that account as `secrets.stalwartSecret` / `config.stalwartUsername`, and set `config.mailProvider=stalwart`.
4. Remove the recovery variable and restart Stalwart.

Sending reputation is the hard part of self-hosting: start with low volumes, keep DMARC reports flowing, and
watch blocklists.

## 9. Security checklist

- [ ] Real `JWT_SECRET_KEY`, admin password rotated, secrets in a secrets manager
- [ ] TLS everywhere (wildcard plus app certificates issued)
- [ ] NetworkPolicies enabled; database not exposed outside the cluster
- [ ] `ENVIRONMENT=production` (disables the `/sites` dev preview mount)
- [ ] SMTP with SPF/DKIM/DMARC for `gumaweb.io` before running outreach campaigns
- [ ] Daily backups verified; alert receivers configured in Alertmanager
