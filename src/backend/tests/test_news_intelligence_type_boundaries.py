from __future__ import annotations

import pytest

from app.models.news_intelligence import NewsSourceModel
from app.services.news_intelligence import NewsIntelligenceService

_FEED = """
<rss><channel>
  <item>
    <title>Market update</title>
    <link>https://example.com/news/1</link>
  </item>
</channel></rss>
"""


@pytest.mark.asyncio
async def test_default_service_keeps_local_helpers_and_requires_db_for_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeResponse:
        text = "<rss><channel></channel></rss>"

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def get(self, url: str, **_kwargs: object) -> FakeResponse:
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr("app.services.news_intelligence.httpx.AsyncClient", FakeAsyncClient)
    service = NewsIntelligenceService()

    classification = service.analyze("Bullish demand surge", allow_ai=False)
    body = await service._default_rss_fetcher("https://example.com/feed.xml")

    assert classification["sentiment"] == "BULLISH"
    assert body == "<rss><channel></channel></rss>"
    assert calls == ["https://example.com/feed.xml"]

    with pytest.raises(RuntimeError) as add_source_error:
        await service.add_source("owner-1", {"name": "test"})
    assert str(add_source_error.value) == "database_session_required"

    with pytest.raises(RuntimeError) as count_error:
        await service._article_count("owner-1")
    assert str(count_error.value) == "database_session_required"


@pytest.mark.parametrize(
    ("metadata_json", "expected_tickers"),
    [
        (["RB2510"], []),
        ({"tickers": ["RB2510", " IF2510 "]}, ["RB2510", "IF2510"]),
    ],
    ids=["non-mapping-metadata", "mapping-default-tickers"],
)
def test_parse_feed_items_safely_handles_metadata_json(
    metadata_json: object,
    expected_tickers: list[str],
) -> None:
    source = NewsSourceModel(
        owner_id="owner-1",
        name="test-source",
        url="https://example.com/feed.xml",
        metadata_json=metadata_json,
    )

    articles = NewsIntelligenceService()._parse_feed_items(_FEED, source, limit=5)

    assert articles[0]["tickers"] == expected_tickers
