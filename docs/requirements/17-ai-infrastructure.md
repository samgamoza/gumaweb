# AI Infrastructure

## Objective

Support local-first AI operations at scale.

---

# Infrastructure Philosophy

AI should operate primarily inside the Guma Datacenter.

Cloud APIs are optional.

---

# AI Cluster

```text
GPU Cluster
│
├── Content Generation
├── Classification
├── Image Generation
├── Validation
└── Agent Orchestration
```

---

# Model Allocation

## Content Models

```yaml
primary: qwen

secondary: deepseek
```

---

## Embedding Models

```yaml
embedding_model: bge
```

---

## Image Models

```yaml
primary: flux

secondary: sdxl
```

---

# AI Services

## Business Classifier

Industry detection.

---

## SEO Generator

Keyword generation.

---

## Content Writer

Business copy.

---

## QA Reviewer

Quality validation.

---

## Agent Orchestrator

Coordinates workflows.

---

# Future Agent Swarm

```text
Discovery Agent
      ↓
Research Agent
      ↓
Content Agent
      ↓
SEO Agent
      ↓
QA Agent
```

---

# Performance Goals

```yaml
websites_per_day: 1000+

generation_time: under_5_minutes

cost_per_site: near_zero
```
