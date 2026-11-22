"""Outreach follow-up sequence (Day 0 / 3 / 7 / 14) and message rendering.

Templates are operator-editable, so they render in a Jinja2 sandbox.
Every message carries an unsubscribe link (communications compliance).
"""

from __future__ import annotations

from typing import Any

from jinja2.sandbox import SandboxedEnvironment

_FOOTER = (
    "\n\n--\nYou are receiving this because {{ business_name }} is listed in a public business directory."
    "\nUnsubscribe: {{ unsubscribe_url }}"
)

DEFAULT_SEQUENCE: list[dict[str, Any]] = [
    {
        "step": 0,
        "day": 0,
        "subject": "We Built a Website for Your Business",
        "body": (
            "Hi {{ business_name }},\n\n"
            "We noticed your business has limited online presence.\n\n"
            "We have already created a professional website for you.\n\n"
            "View it here:\n{{ website_url }}\n\n"
            "You can claim ownership for free:\n{{ claim_url }}\n\n"
            "Regards,\nGumaWeb"
        ),
    },
    {
        "step": 1,
        "day": 3,
        "subject": "Reminder: your free website for {{ business_name }}",
        "body": (
            "Hi {{ business_name }},\n\n"
            "Just a reminder that your website is live at {{ website_url }}.\n"
            "Claim it for free to edit your details: {{ claim_url }}\n\nRegards,\nGumaWeb"
        ),
    },
    {
        "step": 2,
        "day": 7,
        "subject": "How a website helps {{ business_name }} get found",
        "body": (
            "Hi {{ business_name }},\n\n"
            "Customers in {{ city }} search online before they call. Your website makes it easy for them to "
            "find your services, phone number and location.\n\n"
            "See it here: {{ website_url }}\nClaim it for free: {{ claim_url }}\n\nRegards,\nGumaWeb"
        ),
    },
    {
        "step": 3,
        "day": 14,
        "subject": "Final reminder: claim your website",
        "body": (
            "Hi {{ business_name }},\n\n"
            "This is our last reminder about the website we built for you: {{ website_url }}\n"
            "Claim it any time: {{ claim_url }}\n\nRegards,\nGumaWeb"
        ),
    },
]

_env = SandboxedEnvironment(autoescape=False)


def render_message(subject: str, body: str, variables: dict[str, Any]) -> tuple[str, str]:
    rendered_subject = _env.from_string(subject).render(**variables).strip()
    rendered_body = _env.from_string(body + _FOOTER).render(**variables)
    return rendered_subject, rendered_body


def validate_sequence(sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    for item in sequence:
        if not {"step", "day", "subject", "body"} <= item.keys():
            raise ValueError("each sequence step needs step, day, subject and body")
        if item["step"] in seen:
            raise ValueError(f"duplicate step {item['step']}")
        seen.add(item["step"])
        _env.parse(item["subject"])
        _env.parse(item["body"])
    return sorted(sequence, key=lambda s: s["step"])
