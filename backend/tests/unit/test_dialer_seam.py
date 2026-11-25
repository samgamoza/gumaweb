"""The parked dialer seam: with no dialer connected, Gumaweb behaves as before."""

from __future__ import annotations

import pytest

from app.domains.dialer import (
    DialerContact,
    DialerNotConfiguredError,
    NullDialer,
    build_dialer,
    external_ref,
    to_e164,
)
from app.services.providers import providers


def test_default_dialer_is_the_null_dialer():
    providers.reset()
    assert providers.dialer.name == "none"
    assert providers.dialer.health().connected is False


def test_null_dialer_refuses_pushes_and_syncs_nothing():
    dialer = NullDialer()
    contact = DialerContact(external_ref=external_ref("b1"), company_name="Shop", phone_e164="+639171234567")
    with pytest.raises(DialerNotConfiguredError):
        dialer.push_batch("gw:test:1", "test", [contact])
    page = dialer.fetch_outcomes("cursor-1")
    assert page.events == [] and page.next_cursor == "cursor-1"
    assert dialer.push_suppressions(["+639171234567"], "requested") is None


@pytest.mark.parametrize(("stored", "expected"), [
    ("639171234567", "+639171234567"),
    ("+63 917 123 4567", "+639171234567"),
    ("123", None),
    (None, None),
])
def test_to_e164(stored, expected):
    assert to_e164(stored) == expected


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        build_dialer("gumadial")  # not built yet: arrives with its adapter
    assert external_ref("abc") == "gw:business:abc"
