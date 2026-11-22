"""Image generation backends (08). FLUX/SDXL run on Guma GPUs behind an OpenAI-compatible
`/images/generations` endpoint (LocalAI, a ComfyUI bridge, or a small diffusers server)."""

from __future__ import annotations

import base64
from typing import Protocol

import httpx

from app.core.config import Settings
from app.domains.website_factory.images import (
    NEGATIVE_PROMPT,
    GeneratedImage,
    ImageRequest,
    image_dimensions,
    image_prompt,
    procedural_svg,
    sniff_image,
)


class ImageGenerator(Protocol):
    name: str

    def generate(self, req: ImageRequest) -> GeneratedImage: ...


class ProceduralImageGenerator:
    name = "procedural"

    def generate(self, req: ImageRequest) -> GeneratedImage:
        return procedural_svg(req)


class HttpImageGenerator:
    name = "http"

    def __init__(self, base_url: str, model: str, timeout: float = 300.0) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def generate(self, req: ImageRequest) -> GeneratedImage:
        response = self._client.post("/images/generations", json={
            "model": self.model,
            "prompt": image_prompt(req.industry, req.category),
            "negative_prompt": NEGATIVE_PROMPT,
            "size": f"{req.width}x{req.height}",
            "seed": req.seed,
            "n": 1,
            "response_format": "b64_json",
        })
        response.raise_for_status()
        data = base64.b64decode(response.json()["data"][0]["b64_json"])
        mime = sniff_image(data)
        if mime is None:
            raise ValueError("image server returned an unsupported format")
        width, height = image_dimensions(data, mime)
        return GeneratedImage(data, mime, width or req.width, height or req.height, self.model)


def build_image_generator(settings: Settings) -> ImageGenerator:
    if settings.image_backend == "http":
        return HttpImageGenerator(settings.image_api_url, settings.image_model)
    return ProceduralImageGenerator()
