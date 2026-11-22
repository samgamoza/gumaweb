# Image Factory

## Objective

Generate website imagery without recurring stock-photo costs.

---

# Design Philosophy

Generate once.

Reuse thousands of times.

---

# Architecture

```text
Business Profile
       ↓
Industry Mapping
       ↓
Prompt Builder
       ↓
Image Generation
       ↓
Image Review
       ↓
Asset Library
       ↓
Website Factory
```

---

# Models

## Primary

```yaml
model: flux
```

Purpose:

- hero banners
- marketing imagery
- industry visuals

---

## Secondary

```yaml
model: sdxl
```

Purpose:

- fallback generation
- experimentation

---

# Asset Categories

## Construction

```yaml
hero:
service:
gallery:
contact:
```

---

## Healthcare

```yaml
hero:
staff:
services:
waiting_room:
```

---

## Hospitality

```yaml
hero:
rooms:
amenities:
location:
```

---

# Asset Library

Store generated assets.

```text
Image Generated
       ↓
Asset Tagged
       ↓
Asset Stored
       ↓
Reused
```

---

# Asset Metadata

```yaml
asset_id:
industry:
category:
tags:
quality_score:
```

---

# Future Features

## AI Video Generation

Create:

- business intro videos
- promotional videos
- social media reels

---

## Logo Generation

Generate starter logos for unclaimed websites.
