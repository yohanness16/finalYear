"""Tests for bus dashboard pairing flow."""

import re

from app.api.v1.pairing import PairVerifyRequest, _generate_code


def test_generate_code_format():
    """Pairing code should match BUS-XXXX-XXXX format."""
    code = _generate_code()
    assert code.startswith("BUS-")
    assert len(code) == 13
    assert re.match(r"^BUS-[A-Z0-9]{4}-[A-Z0-9]{4}$", code)


def test_pair_verify_request_accepts_valid_payload():
    """PairVerifyRequest should accept a valid payload."""
    payload = PairVerifyRequest(code="BUS-ABCD-EFGH", password="test1234")
    assert payload.code == "BUS-ABCD-EFGH"
