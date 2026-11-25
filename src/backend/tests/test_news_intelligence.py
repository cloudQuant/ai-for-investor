import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.database import async_session_maker
from app.models.news_intelligence import NewsAnalysisModel, NewsArticleModel, NewsSourceModel
from app.services.data_topic_hub import TopicPolicy, get_shared_data_topic_hub
from app.services.news_intelligence import NewsIntelligenceService
from tests.conftest import register_and_login


@pytest.mark.asyncio
async def test_news_intelligence_dedup_classify_cluster_and_publish_topic(client: AsyncClient):
    _, headers = await register_and_login(client, username="news_user")
    hub = get_shared_data_topic_hub()
    hub.register_topic("news:symbol:RB2510", TopicPolicy(push_only=True))

    source = await client.post(
        "/api/v1/news-intelligence/sources",
        headers=headers,
        json={"name": "demo", "url": "https://example.com/rss", "tier": 2},
    )
    ingest = await client.post(
        "/api/v1/news-intelligence/articles/ingest",
        headers=headers,
        json={
            "articles": [
                {
                    "headline": "RB2510 surges after bullish demand shock",
                    "url": "https://example.com/a?utm_source=x",
                    "source": "demo",
                    "tickers": ["RB2510"],
                },
                {
                    "headline": "RB2510 surges after bullish demand shock",
                    "url": "https://example.com/a",
                    "source": "demo",
                    "tickers": ["RB2510"],
                },
            ]
        },
    )
    latest = await client.get("/api/v1/news-intelligence/articles", headers=headers)
    topic = hub.peek_raw("news:symbol:RB2510")

    assert source.status_code == 201
    assert ingest.status_code == 200
    assert ingest.json()["inserted_count"] == 1
    assert latest.status_code == 200
    article = latest.json()["items"][0]
    assert article["sentiment"] == "BULLISH"
    assert article["impact"] in {"HIGH", "MEDIUM", "LOW"}
    assert article["cluster_id"]
    assert article["summary"]
    assert article["has_content"] is True
    assert topic["headline"].startswith("RB2510")

    async with async_session_maker() as session:
        sources = (await session.execute(select(NewsSourceModel))).scalars().all()
        articles = (await session.execute(select(NewsArticleModel))).scalars().all()
        analyses = (await session.execute(select(NewsAnalysisModel))).scalars().all()

    assert len(sources) == 1
    assert len(articles) == 1
    assert len(analyses) == 1
    assert articles[0].canonical_url == "https://example.com/a"


@pytest.mark.asyncio
async def test_news_intelligence_ai_fallback_degrades_when_unavailable(client: AsyncClient):
    _, headers = await register_and_login(client, username="news_degraded")

    response = await client.post(
        "/api/v1/news-intelligence/analyze",
        headers=headers,
        json={"headline": "Unclear macro policy update", "allow_ai": True},
    )

    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}
    assert response.json()["sentiment"] in {"BULLISH", "BEARISH", "NEUTRAL"}

    async with async_session_maker() as session:
        analyses = (await session.execute(select(NewsAnalysisModel))).scalars().all()

    assert len(analyses) == 1


@pytest.mark.asyncio
async def test_news_intelligence_pull_source_and_filter_articles(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_rss_fetcher(self, url: str) -> str:
        assert url == "https://example.com/feed.xml"
        return """
<rss>
  <channel>
    <item>
      <title>RB2510 surges after bullish demand shock</title>
      <link>https://example.com/rss/rb2510?utm_source=test</link>
      <description>Demand shock lifted steel-linked futures.</description>
      <category>RB2510</category>
    </item>
    <item>
      <title>BU2501 drops on weak inventory data</title>
      <link>https://example.com/rss/bu2501</link>
      <category>BU2501</category>
    </item>
  </channel>
</rss>
"""

    monkeypatch.setattr(NewsIntelligenceService, "_default_rss_fetcher", fake_rss_fetcher)
    _, headers = await register_and_login(client, username="news_pull_user")

    source = await client.post(
        "/api/v1/news-intelligence/sources",
        headers=headers,
        json={
            "name": "terminal-rss",
            "url": "https://example.com/feed.xml",
            "tier": 2,
            "metadata": {"tickers": ["RB2510"]},
        },
    )
    pulled = await client.post(
        "/api/v1/news-intelligence/sources/terminal-rss/pull",
        headers=headers,
        params={"limit": 10},
    )
    bullish = await client.get(
        "/api/v1/news-intelligence/articles",
        headers=headers,
        params={"sentiment": "BULLISH"},
    )
    rb_articles = await client.get(
        "/api/v1/news-intelligence/articles",
        headers=headers,
        params={"ticker": "RB2510"},
    )
    all_articles = await client.get(
        "/api/v1/news-intelligence/articles",
        headers=headers,
    )
    cluster_id = all_articles.json()["items"][0]["cluster_id"]
    cluster_articles = await client.get(
        "/api/v1/news-intelligence/articles",
        headers=headers,
        params={"cluster_id": cluster_id},
    )

    assert source.status_code == 201
    assert pulled.status_code == 200
    assert pulled.json()["status"] == "ok"
    assert pulled.json()["fetched_count"] == 2
    assert pulled.json()["inserted_count"] == 2

    assert bullish.status_code == 200
    assert bullish.json()["total"] == 1
    assert bullish.json()["items"][0]["headline"].startswith("RB2510")

    assert rb_articles.status_code == 200
    assert rb_articles.json()["total"] == 1
    assert rb_articles.json()["items"][0]["tickers"] == ["RB2510"]
    assert "Demand shock" in rb_articles.json()["items"][0]["summary"]
    article_id = rb_articles.json()["items"][0]["id"]
    content = await client.get(
        f"/api/v1/news-intelligence/articles/{article_id}/content",
        headers=headers,
    )
    assert content.status_code == 200
    assert "Demand shock" in content.json()["content"]

    assert cluster_articles.status_code == 200
    assert cluster_articles.json()["total"] == 1
    assert cluster_articles.json()["items"][0]["cluster_id"] == cluster_id


@pytest.mark.asyncio
async def test_news_intelligence_default_rss_fetcher_uses_financial_feed_headers(
    monkeypatch: pytest.MonkeyPatch,
):
    import socket

    captured: dict[str, object] = {}

    class FakeStreamResponse:
        status_code = 200
        headers: dict[str, str] = {}
        encoding = "utf-8"

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            yield b"<rss><channel></channel></rss>"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["stream_kwargs"] = kwargs
            return FakeStreamResponse()

    monkeypatch.setattr("app.services.news_intelligence.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    body = await NewsIntelligenceService()._default_rss_fetcher(
        "https://feeds.bloomberg.com/markets/news.rss"
    )

    stream_kwargs = captured["stream_kwargs"]
    assert body.startswith("<rss")
    assert captured["method"] == "GET"
    assert captured["url"] == "https://feeds.bloomberg.com/markets/news.rss"
    assert stream_kwargs["follow_redirects"] is False
    assert "headers" in stream_kwargs
    assert "Mozilla/5.0" in stream_kwargs["headers"]["User-Agent"]
    assert "application/rss+xml" in stream_kwargs["headers"]["Accept"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocked_url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8080/internal",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost/feed.xml",
    ],
)
async def test_news_intelligence_blocks_ssrf_schemes_and_private_ips(
    client: AsyncClient,
    blocked_url: str,
):
    _, headers = await register_and_login(client, username=f"ssrf_{hash(blocked_url) & 0xFFFF}")
    resp = await client.post(
        "/api/v1/news-intelligence/sources",
        headers=headers,
        json={"name": "bad-src", "url": blocked_url},
    )
    assert resp.status_code == 422

    with pytest.raises(ValueError):
        await NewsIntelligenceService()._default_rss_fetcher(blocked_url)


@pytest.mark.asyncio
async def test_news_intelligence_blocks_private_redirects_and_oversized_streams(
    monkeypatch: pytest.MonkeyPatch,
):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **k: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("127.0.0.1" if host == "rebind.test" else "93.184.216.34", 443),
            )
        ],
    )

    with pytest.raises(ValueError, match="restricted IP"):
        await NewsIntelligenceService()._default_rss_fetcher("https://rebind.test/rss.xml")

    class RedirectResponse:
        status_code = 302
        headers = {"location": "http://127.0.0.1/admin"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

    class RedirectClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs):
            return RedirectResponse()

    monkeypatch.setattr("app.services.news_intelligence.httpx.AsyncClient", RedirectClient)
    with pytest.raises(ValueError, match="private or loopback"):
        await NewsIntelligenceService()._default_rss_fetcher("https://example.com/rss.xml")

    class HugeResponse:
        status_code = 200
        headers: dict[str, str] = {}
        encoding = "utf-8"

        def raise_for_status(self) -> None:
            return None

        async def aiter_bytes(self):
            for _ in range(5):
                yield b"x" * (600 * 1024)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a) -> None:
            return None

    class HugeClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs):
            return HugeResponse()

    monkeypatch.setattr("app.services.news_intelligence.httpx.AsyncClient", HugeClient)
    with pytest.raises(ValueError, match="maximum accepted size"):
        await NewsIntelligenceService()._default_rss_fetcher("https://example.com/huge.xml")
