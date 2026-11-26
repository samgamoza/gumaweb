"""Preview images of a draft (A7b): what the owner sees of their site in the outreach email.

`PREVIEW_CAPTURE_BACKEND`:
* `none` (default): no images. Emails still work: a text headline and a button, no picture.
* `playwright`: headless Chromium renders the draft from a temporary folder and takes a desktop and a phone shot.
  Needs `pip install -r requirements/preview.txt` and `playwright install --with-deps chromium` (the worker image
  does this with `--build-arg WITH_PREVIEWS=true`).

The draft is loaded from local files; requests to other hosts are blocked except web fonts, so capturing never
calls our own API (analytics, chat) and never leaks the draft anywhere.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("gumaweb.previews")

FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")


@dataclass(frozen=True)
class Shot:
    kind: str  # "desktop" | "phone"
    data: bytes
    mime: str


VIEWPORTS = {"desktop": (1200, 750), "phone": (390, 780)}


class PreviewCapture(Protocol):
    name: str

    def capture(self, files: dict[str, bytes]) -> list[Shot]: ...


class DisabledCapture:
    name = "none"

    def capture(self, files: dict[str, bytes]) -> list[Shot]:
        return []


class PlaywrightCapture:
    name = "playwright"

    def __init__(self, timeout_ms: int = 15000, quality: int = 70) -> None:
        self.timeout_ms = timeout_ms
        self.quality = quality

    def capture(self, files: dict[str, bytes]) -> list[Shot]:
        from playwright.sync_api import sync_playwright  # optional dependency: requirements/preview.txt

        with tempfile.TemporaryDirectory(prefix="gw-preview-") as tmp:
            root = Path(tmp)
            for rel, data in files.items():
                target = (root / rel).resolve()
                if root.resolve() not in target.parents:  # never write outside the folder
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            index = (root / "index.html").as_uri()
            shots = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    for kind, (width, height) in VIEWPORTS.items():
                        context = browser.new_context(viewport={"width": width, "height": height},
                                                      device_scale_factor=1, is_mobile=kind == "phone")
                        context.route("**/*", _only_local_and_fonts)
                        page = context.new_page()
                        page.goto(index, wait_until="load", timeout=self.timeout_ms)
                        page.wait_for_timeout(300)  # let web fonts settle
                        data = page.screenshot(type="jpeg", quality=self.quality, full_page=False)
                        shots.append(Shot(kind, data, "image/jpeg"))
                        context.close()
                finally:
                    browser.close()
            return shots


def _only_local_and_fonts(route) -> None:
    url = route.request.url
    if url.startswith("file:") or any(f"//{host}/" in url for host in FONT_HOSTS):
        route.continue_()
    else:
        route.abort()


def build_capture(backend: str) -> PreviewCapture:
    if backend == "playwright":
        return PlaywrightCapture()
    return DisabledCapture()
