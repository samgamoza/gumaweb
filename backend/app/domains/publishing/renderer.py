"""Static site renderer.

Phase 1 renders blueprints to static HTML with Jinja2 (no Node toolchain in the
hot path, ~ms per site). The `SiteRenderer` interface allows an Astro build
worker (09-website-assembly-pipeline) to be swapped in later without changing
the pipeline. Output: static HTML, one CSS file, minimal JS, robots.txt,
sitemap.xml and a site.json metadata file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.domains.seo.generator import faq_schema, robots_txt, sitemap_xml

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_SAFE_FONT = re.compile(r"^[\w\s,\-'\"]+$")


@dataclass(frozen=True)
class RenderContext:
    website_id: str
    blueprint: dict[str, Any]
    content: dict[str, dict[str, Any]]
    seo: dict[str, Any]
    site_url: str
    api_url: str
    claim_url: str
    version: int
    # asset_id -> (relative output path, bytes); content image refs are rewritten to these paths
    assets: dict[str, tuple[str, bytes]] | None = None


def theme_css_variables(theme: dict[str, Any]) -> str:
    """Only allow-listed, validated values reach the stylesheet."""
    lines = []
    for key, value in (theme.get("palette") or {}).items():
        if isinstance(value, str) and _HEX_COLOR.match(value):
            lines.append(f"--color-{re.sub(r'[^a-z0-9-]', '', key.replace('_', '-'))}: {value};")
    for key, value in (theme.get("fonts") or {}).items():
        if isinstance(value, str) and _SAFE_FONT.match(value):
            lines.append(f"--font-{re.sub(r'[^a-z0-9-]', '', key)}: {value};")
    radius = theme.get("radius")
    if isinstance(radius, str) and re.match(r"^\d{1,2}(px|rem)$", radius):
        lines.append(f"--radius: {radius};")
    return ":root{" + "".join(lines) + "}"


class SiteRenderer:
    def __init__(self, templates_dir: Path) -> None:
        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["tel"] = lambda v: "+" + v if v and str(v).isdigit() else v

    def available_components(self) -> set[tuple[str, str]]:
        root = self.templates_dir / "components"
        return {(p.parent.name, p.name.removesuffix(".html.j2")) for p in root.glob("*/*.html.j2")}

    def _link(self, root: str, target: str | None, pages: set[str]) -> str:
        if not target:
            return f"{root}"
        if target in pages:
            return f"{root}{'' if target == 'home' else target + '/'}"
        return f"#{target}"

    @staticmethod
    def _with_image_paths(content: dict[str, dict[str, Any]], assets: dict[str, tuple[str, bytes]]
                          ) -> dict[str, dict[str, Any]]:
        """Replace {asset_id} image references with build-relative paths; drop unresolvable ones."""
        def resolve(ref: Any) -> dict[str, Any] | None:
            if isinstance(ref, dict) and str(ref.get("asset_id")) in assets:
                return {**ref, "path": assets[str(ref["asset_id"])][0]}
            return None

        out = {}
        for key, block in content.items():
            block = dict(block)
            if "image" in block:
                block["image"] = resolve(block["image"])
            if isinstance(block.get("images"), list):
                block["images"] = [r for r in (resolve(i) for i in block["images"]) if r]
            out[key] = block
        return out

    def render(self, ctx: RenderContext) -> dict[str, bytes]:
        bp = ctx.blueprint
        page_slugs = {p["slug"] for p in bp["pages"]}
        files: dict[str, bytes] = {}
        assets = ctx.assets or {}
        content = self._with_image_paths(ctx.content, assets)
        page_meta = ctx.seo.get("pages") or {}
        layout = self.env.get_template("layouts/base.html.j2")
        css_vars = theme_css_variables(bp.get("theme", {}))
        for page in bp["pages"]:
            root = "./" if page["slug"] == "home" else "../"
            sections_html = []
            schemas = [ctx.seo.get("schema_markup", {})]
            for section in page["sections"]:
                block = content.get(section["content_key"], {})
                if section["component"] == "faq" and page["slug"] != "home":
                    schemas.append(faq_schema(block.get("items", [])))
                tpl = self.env.get_template(f"components/{section['component']}/{section['variant']}.html.j2")
                sections_html.append(
                    Markup(
                        tpl.render(
                            block=block,
                            business=bp["business"],
                            root=root,
                            link=lambda target, r=root: self._link(r, target, page_slugs),
                            api_url=ctx.api_url,
                            subdomain=bp["subdomain"],
                            site_url=ctx.site_url,
                        )
                    )
                )
            meta = page_meta.get(page["slug"], {})
            page_title = meta.get("title") or (ctx.seo["page_title"] if page["slug"] == "home" else (
                f"{page['title']} | {bp['business']['name']}"
            ))
            hero_image = (content.get("hero", {}).get("image") or {}).get("path")
            html = layout.render(
                page=page,
                page_title=page_title,
                page_description=meta.get("description") or ctx.seo["meta_description"],
                og_image=f"{ctx.site_url.rstrip('/')}/{hero_image}" if hero_image and
                not hero_image.endswith(".svg") else None,
                pages=bp["pages"],
                sections_html=sections_html,
                business=bp["business"],
                seo=ctx.seo,
                schema_blocks=[Markup(json.dumps(s).replace("</", "<\\/")) for s in schemas if s],
                css_vars=Markup(css_vars),
                root=root,
                canonical_url=ctx.site_url.rstrip("/") + "/" + page["path"],
                claim_banner=bp.get("claim_banner", False),
                claim_url=ctx.claim_url,
                api_url=ctx.api_url,
                subdomain=bp["subdomain"],
                footer=ctx.content.get("footer", {}),
                year=date.today().year,
            )
            files[page["output"]] = html.encode("utf-8")

        for path, data in assets.values():
            files[path] = data
        files["assets/site.css"] = (self.templates_dir / "assets" / "site.css").read_bytes()
        files["robots.txt"] = robots_txt(ctx.site_url).encode()
        files["sitemap.xml"] = sitemap_xml(ctx.site_url, [p["path"] for p in bp["pages"]]).encode()
        files["site.json"] = json.dumps(
            {
                "website_id": ctx.website_id,
                "subdomain": bp["subdomain"],
                "version": ctx.version,
                "template": bp["template"],
                "generated": date.today().isoformat(),
            },
            indent=2,
        ).encode()
        return files
