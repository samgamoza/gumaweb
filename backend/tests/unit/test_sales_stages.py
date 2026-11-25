"""Sales CRM stage rules (pure)."""

from __future__ import annotations

import pytest

from app.domains.sales import ProspectStage as S
from app.domains.sales import auto_advance


@pytest.mark.parametrize(("current", "target", "expected"), [
    (S.NEW, S.CONTACTED, S.CONTACTED),
    (S.ENGAGED, S.CONTACTED, S.ENGAGED),  # never backwards: a late "sent" doesn't undo an open
    (S.CLAIMED, S.ENGAGED, S.CLAIMED),
    (S.LOST, S.ENGAGED, S.LOST),  # closed stays closed for ordinary events
    (S.DO_NOT_CONTACT, S.CONVERSATION, S.DO_NOT_CONTACT),
    (S.LOST, S.CLAIMED, S.CLAIMED),  # a conversion is a fact
    (S.DO_NOT_CONTACT, S.WON, S.WON),
    (S.ENGAGED, S.DO_NOT_CONTACT, S.DO_NOT_CONTACT),
    (S.LOST, S.DO_NOT_CONTACT, S.DO_NOT_CONTACT),
    (S.WON, S.DO_NOT_CONTACT, S.WON),  # customers keep their stage
    (S.CLAIMED, S.WON, S.WON),
])
def test_auto_advance(current, target, expected):
    assert auto_advance(current, target) is expected
