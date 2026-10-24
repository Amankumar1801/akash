"""The real light-curve source must say WHY nothing was usable, not just count failures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from akash_api.services import DataLayerLightCurveSource
from akash_core.errors import ValidationFailure


class _FakeSvc:
    def __init__(self, res: SimpleNamespace) -> None:
        self.res = res

    def ingest(self, obj, flt):  # type: ignore[no-untyped-def]
        return self.res


def _source(res: SimpleNamespace) -> DataLayerLightCurveSource:
    return DataLayerLightCurveSource(None, _FakeSvc(res), _FakeSvc(res), "test")  # type: ignore[arg-type]


def test_failure_message_carries_first_reasons() -> None:
    res = SimpleNamespace(
        observations=[], errors=[("kplr1", "HTTP 503")],
        quarantined=[("kplr2", "missing table columns: ['SAP_QUALITY/QUALITY']")])
    with pytest.raises(ValidationFailure) as ei:
        _source(res).fetch(SimpleNamespace(), "kepler", [], 10)  # type: ignore[arg-type]
    msg = str(ei.value)
    assert "1 errors, 1 quarantined" in msg
    assert "kplr1: HTTP 503" in msg and "SAP_QUALITY/QUALITY" in msg


def test_failure_message_without_reasons_stays_short() -> None:
    res = SimpleNamespace(observations=[], errors=[], quarantined=[])
    with pytest.raises(ValidationFailure) as ei:
        _source(res).fetch(SimpleNamespace(), "tess", [], 10)  # type: ignore[arg-type]
    assert "First reasons" not in str(ei.value)
