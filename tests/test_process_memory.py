from __future__ import annotations

from utils.process_memory import peak_rss_kib


def test_peak_rss_is_reported_in_kib() -> None:
    peak = peak_rss_kib()

    assert isinstance(peak, int)
    assert peak > 0
