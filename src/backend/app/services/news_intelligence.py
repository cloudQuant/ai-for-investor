from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import re
import socket
import typing
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news_intelligence import (
    NewsAnalysisModel,
    NewsArticleModel,
    NewsSourceModel,
)
from app.services.data_topic_hub import get_shared_data_topic_hub

_RSS_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Upper bound for one feed document.  RSS feeds are small; anything larger is
# either an error page or an attempt to exhaust memory during XML parsing.
_MAX_RSS_BYTES = 2 * 1024 * 1024
_RSS_MAX_REDIRECTS = 5


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped is not None and _is_disallowed_ip(mapped)


def _validate_public_http_url(raw_url: str, *, require_dns: bool) -> str:
    """Validate that an RSS feed URL uses HTTP(S) and cannot target internal networks."""
    url = str(raw_url or "").strip()
    if not url:
        raise ValueError("RSS URL is required")
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("Embedded credentials in RSS URLs are not allowed")
    hostname = (parsed.hostname or "").strip().rstrip(".")
    if not hostname:
        raise ValueError("RSS URL must include a hostname")
    lower_host = hostname.lower()
    if (
        lower_host in {"localhost", "localhost.localdomain"}
        or lower_host.endswith(".localhost")
        or lower_host.endswith(".local")
        or lower_host.endswith(".internal")
    ):
        raise ValueError("Restricted RSS target host")

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None:
        if _is_disallowed_ip(ip):
            raise ValueError("RSS URL cannot target private or loopback IP addresses")
        return url

    port = parsed.port or (443 if scheme == "https" else 80)
    try:
        addr_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        if require_dns:
            raise ValueError(f"Unable to resolve RSS host {hostname!r}") from exc
        return url

    if not addr_infos and require_dns:
        raise ValueError(f"RSS host {hostname!r} resolved no addresses")

    for _family, _socktype, _proto, _canonname, sockaddr in addr_infos:
        if not sockaddr:
            continue
        addr_text = str(sockaddr[0]).split("%", 1)[0]
        resolved_ip = ipaddress.ip_address(addr_text)
        if _is_disallowed_ip(resolved_ip):
            raise ValueError("RSS URL resolves to a restricted IP address")
    return url


class _NewsSourceInstance(typing.Protocol):
    """Scalar fields exposed by a loaded NewsSourceModel ORM instance."""

    id: str
    name: str
    url: str
    tier: int
    status: str
    metadata_json: object


class NewsIntelligenceService:
    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db
        self._hub = get_shared_data_topic_hub()
        self._rss_fetcher = self._default_rss_fetcher

    async def add_source(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        db = self._require_db()
        name = str(payload.get("name") or "").strip()
        raw_url = payload.get("url")
        result = await db.execute(
            select(NewsSourceModel).where(
                NewsSourceModel.owner_id == user_id,
                NewsSourceModel.name == name,
            )
        )
        source = result.scalar_one_or_none()
        candidate_url = str(raw_url or (source.url if source is not None else "") or "").strip()
        validated_url = await asyncio.to_thread(
            _validate_public_http_url, candidate_url, require_dns=False
        )
        if source is None:
            source = NewsSourceModel(
                owner_id=user_id,
                name=name,
                url=validated_url,
                tier=int(payload.get("tier") or 2),
                status="active",
                metadata_json=dict(payload.get("metadata") or {}),
            )
            db.add(source)
        else:
            # Legacy Column declarations type class attributes, not loaded ORM scalar values.
            source_row = typing.cast(_NewsSourceInstance, source)
            source_row.url = validated_url
            source_row.tier = int(payload.get("tier") or source_row.tier or 2)
            source_row.status = str(payload.get("status") or source_row.status or "active")
            existing_metadata = source_row.metadata_json
            if not isinstance(existing_metadata, Mapping):
                existing_metadata = {}
            source_row.metadata_json = dict(payload.get("metadata") or existing_metadata or {})
        await db.commit()
        await db.refresh(source)
        return self._serialize_source(source)

    async def ingest(self, user_id: str, articles: list[dict[str, Any]]) -> dict[str, Any]:
        db = self._require_db()
        inserted = 0
        source_rows = (
            (await db.execute(select(NewsSourceModel).where(NewsSourceModel.owner_id == user_id)))
            .scalars()
            .all()
        )
        sources: dict[str, _NewsSourceInstance] = {}
        for source_model in source_rows:
            # Use the loaded-row contract rather than legacy Column class attributes.
            source_row = typing.cast(_NewsSourceInstance, source_model)
            sources[source_row.name] = source_row
        canonical_urls = [self._canonicalize_url(str(item.get("url") or "")) for item in articles]
        existing_keys = set(
            (
                await db.execute(
                    select(NewsArticleModel.canonical_url).where(
                        NewsArticleModel.owner_id == user_id,
                        NewsArticleModel.canonical_url.in_(canonical_urls),
                    )
                )
            )
            .scalars()
            .all()
        )
        for item in articles:
            canonical_url = self._canonicalize_url(str(item.get("url") or ""))
            if canonical_url in existing_keys:
                continue
            classified = self.analyze(item.get("headline", ""), allow_ai=False)
            cluster_id = hashlib.sha256(
                item.get("headline", "").lower().encode("utf-8")
            ).hexdigest()[:12]
            source_name = str(item.get("source") or "unknown")
            source = sources.get(source_name)
            headline = str(item.get("headline") or "").strip()
            article_summary = str(item.get("summary") or "").strip()
            article_content = str(item.get("content") or article_summary).strip()
            article = NewsArticleModel(
                owner_id=user_id,
                source_id=source.id if source is not None else None,
                source=source_name,
                headline=headline,
                url=str(item.get("url") or "").strip(),
                canonical_url=canonical_url,
                tickers=[
                    str(ticker).strip()
                    for ticker in list(item.get("tickers") or [])
                    if str(ticker).strip()
                ],
                priority=str(item.get("priority") or "P2"),
                tier=int(item.get("tier") or (source.tier if source is not None else 2)),
                source_flag=str(item.get("source_flag") or "rss"),
                sentiment=classified["sentiment"],
                impact=classified["impact"],
                threat=classified["threat"],
                cluster_id=cluster_id,
                summary=article_summary or self._build_summary(headline, classified),
                content=article_content
                or article_summary
                or self._build_summary(headline, classified),
                status=classified["status"],
            )
            db.add(article)
            await db.flush()
            db.add(
                NewsAnalysisModel(
                    owner_id=user_id,
                    article_id=article.id,
                    headline=article.headline,
                    sentiment=classified["sentiment"],
                    impact=classified["impact"],
                    threat=classified["threat"],
                    status=classified["status"],
                    provider="rules",
                )
            )
            existing_keys.add(canonical_url)
            inserted += 1
            record = self._serialize_article(article)
            await self._hub.push("news:general", record)
            await self._hub.push(f"news:cluster:{record['cluster_id']}", record)
            await self._hub.push(f"news:category:{record['sentiment'].lower()}", record)
            for ticker in record["tickers"]:
                await self._hub.push(f"news:symbol:{ticker}", record)
        await db.commit()
        total = await self._article_count(user_id)
        return {"inserted_count": inserted, "total": total}

    async def pull_source(
        self,
        user_id: str,
        source_name: str,
        *,
        limit: int = 20,
    ) -> dict[str, Any] | None:
        db = self._require_db()
        result = await db.execute(
            select(NewsSourceModel).where(
                NewsSourceModel.owner_id == user_id,
                NewsSourceModel.name == source_name,
            )
        )
        source = result.scalar_one_or_none()
        if source is None:
            return None
        try:
            feed_text = await self._rss_fetcher(str(source.url or ""))
            articles = self._parse_feed_items(feed_text, source, limit=limit)
        except (ET.ParseError, ValueError, httpx.HTTPError):
            return {
                "source": source_name,
                "status": "degraded",
                "reason": "fetch_failed",
                "fetched_count": 0,
                "inserted_count": 0,
                "total": await self._article_count(user_id),
            }
        ingested = await self.ingest(user_id, articles)
        return {
            "source": source_name,
            "status": "ok",
            "fetched_count": len(articles),
            "inserted_count": ingested["inserted_count"],
            "total": ingested["total"],
        }

    async def list_articles(
        self,
        user_id: str,
        *,
        sentiment: str | None = None,
        source: str | None = None,
        ticker: str | None = None,
        cluster_id: str | None = None,
    ) -> dict[str, Any]:
        db = self._require_db()
        query = select(NewsArticleModel).where(NewsArticleModel.owner_id == user_id)
        if sentiment:
            query = query.where(NewsArticleModel.sentiment == str(sentiment).upper())
        if source:
            query = query.where(NewsArticleModel.source == str(source).strip())
        if cluster_id:
            query = query.where(NewsArticleModel.cluster_id == str(cluster_id).strip())
        result = await db.execute(query.order_by(NewsArticleModel.created_at.desc()))
        rows = list(result.scalars().all())
        if ticker:
            expected_ticker = str(ticker).strip().upper()
            rows = [
                item
                for item in rows
                if expected_ticker
                in {
                    str(value).strip().upper()
                    for value in list(item.tickers or [])
                    if str(value).strip()
                }
            ]
        items = [self._serialize_article(item) for item in rows]
        return {"items": items, "total": len(items)}

    async def get_article_content(self, user_id: str, article_id: str) -> dict[str, Any] | None:
        """Return the locally stored article body for the requesting owner only."""
        db = self._require_db()
        result = await db.execute(
            select(NewsArticleModel).where(
                NewsArticleModel.id == article_id,
                NewsArticleModel.owner_id == user_id,
            )
        )
        article = result.scalar_one_or_none()
        if article is None:
            return None
        content = str(article.content or article.summary or "").strip()
        return {
            "id": article.id,
            "headline": article.headline,
            "content": content,
            "summary": article.summary,
            "source": article.source,
            "url": article.url,
        }

    async def latest(self, user_id: str) -> dict[str, Any]:
        db = self._require_db()
        result = await db.execute(
            select(NewsArticleModel)
            .where(NewsArticleModel.owner_id == user_id)
            .order_by(NewsArticleModel.created_at.desc())
        )
        article = result.scalars().first()
        return (
            self._serialize_article(article)
            if article is not None
            else {"headline": "No news", "sentiment": "NEUTRAL"}
        )

    def analyze(self, headline: str, *, allow_ai: bool) -> dict[str, Any]:
        text = headline.lower()
        sentiment = "NEUTRAL"
        impact = "LOW"
        threat = "LOW"
        status = "ok"
        if any(word in text for word in ["surge", "bullish", "beat", "strong"]):
            sentiment = "BULLISH"
            impact = "HIGH"
        elif any(word in text for word in ["drop", "bearish", "miss", "weak"]):
            sentiment = "BEARISH"
            impact = "HIGH"
            threat = "HIGH"
        elif allow_ai:
            status = "degraded"
        return {"status": status, "sentiment": sentiment, "impact": impact, "threat": threat}

    async def analyze_headline(
        self,
        user_id: str,
        headline: str,
        *,
        allow_ai: bool,
    ) -> dict[str, Any]:
        db = self._require_db()
        result = self.analyze(headline, allow_ai=allow_ai)
        db.add(
            NewsAnalysisModel(
                owner_id=user_id,
                article_id=None,
                headline=headline,
                sentiment=result["sentiment"],
                impact=result["impact"],
                threat=result["threat"],
                status=result["status"],
                provider="rules" if result["status"] == "ok" else "fallback",
            )
        )
        await db.commit()
        return result

    @staticmethod
    def _canonicalize_url(url: str) -> str:
        parsed = urlparse(url)
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ]
        return urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), "")
        )

    async def _article_count(self, user_id: str) -> int:
        db = self._require_db()
        result = await db.execute(
            select(NewsArticleModel.id).where(NewsArticleModel.owner_id == user_id)
        )
        return len(list(result.scalars().all()))

    async def _default_rss_fetcher(self, url: str) -> str:
        current_url = url
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            for _hop in range(_RSS_MAX_REDIRECTS + 1):
                current_url = await asyncio.to_thread(
                    _validate_public_http_url, current_url, require_dns=True
                )
                async with client.stream(
                    "GET",
                    current_url,
                    follow_redirects=False,
                    headers=_RSS_REQUEST_HEADERS,
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("RSS redirect response missing Location header")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            if int(content_length) > _MAX_RSS_BYTES:
                                raise ValueError("RSS feed exceeds the maximum accepted size")
                        except ValueError as exc:
                            if "maximum accepted size" in str(exc):
                                raise
                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > _MAX_RSS_BYTES:
                            raise ValueError("RSS feed exceeds the maximum accepted size")
                        chunks.append(chunk)
                    encoding = getattr(response, "encoding", None) or "utf-8"
                    return b"".join(chunks).decode(encoding, errors="replace")
            raise ValueError("Too many redirects while fetching RSS feed")

    def _parse_feed_items(
        self,
        feed_text: str,
        source: NewsSourceModel,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        # RSS is a semi-trusted input.  The stdlib parser expands internal
        # entities; reject DTD/ENTITY payloads and cap the document size before
        # handing it to ElementTree.
        if len(feed_text) > _MAX_RSS_BYTES:
            raise ValueError("RSS feed exceeds the maximum accepted size")
        upper = feed_text[:4096].upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise ValueError("RSS feeds with DTD/ENTITY declarations are not accepted")
        root = ET.fromstring(feed_text)
        metadata_json = source.metadata_json
        ticker_values: Iterable[object] = ()
        if isinstance(metadata_json, Mapping):
            candidate_tickers = metadata_json.get("tickers")
            if isinstance(candidate_tickers, Iterable):
                ticker_values = candidate_tickers
        default_tickers = [str(item).strip() for item in ticker_values if str(item).strip()]
        items: list[dict[str, Any]] = []
        for entry in self._iter_feed_entries(root):
            headline = self._entry_text(entry, "title")
            link = self._entry_link(entry)
            if not headline or not link:
                continue
            categories = self._entry_categories(entry)
            tickers = categories or default_tickers
            summary = self._entry_summary(entry)
            items.append(
                {
                    "headline": headline,
                    "url": link,
                    "source": source.name,
                    "tickers": tickers,
                    "tier": source.tier,
                    "source_flag": "rss_pull",
                    "summary": summary,
                }
            )
            if len(items) >= max(limit, 1):
                break
        if not items:
            raise ValueError("invalid_feed")
        return items

    def _iter_feed_entries(self, root: ET.Element) -> list[ET.Element]:
        entries = [
            element for element in root.iter() if self._tag_name(element.tag) in {"item", "entry"}
        ]
        return entries

    def _entry_text(self, entry: ET.Element, field_name: str) -> str:
        for child in entry:
            if self._tag_name(child.tag) == field_name:
                return " ".join(str(text).strip() for text in child.itertext() if str(text).strip())
        return ""

    def _entry_summary(self, entry: ET.Element) -> str:
        for field_name in ("description", "summary", "encoded", "content"):
            text = self._entry_text(entry, field_name)
            if text:
                return self._clean_feed_text(text)
        return ""

    def _entry_link(self, entry: ET.Element) -> str:
        for child in entry:
            if self._tag_name(child.tag) != "link":
                continue
            href = str(child.attrib.get("href") or "").strip()
            if href:
                return href
            text = str(child.text or "").strip()
            if text:
                return text
        return ""

    def _entry_categories(self, entry: ET.Element) -> list[str]:
        categories: list[str] = []
        for child in entry:
            if self._tag_name(child.tag) != "category":
                continue
            value = str(child.attrib.get("term") or child.text or "").strip()
            if value:
                categories.append(value)
        return categories

    def _tag_name(self, tag: str) -> str:
        return str(tag).split("}")[-1].split(":")[-1]

    def _clean_feed_text(self, text: str) -> str:
        decoded = html.unescape(str(text or "")).strip()
        without_tags = re.sub(r"<[^>]+>", " ", decoded)
        return " ".join(without_tags.split())

    def _serialize_source(self, source: NewsSourceModel) -> dict[str, Any]:
        return {
            "id": source.id,
            "name": source.name,
            "url": source.url,
            "tier": source.tier,
            "status": source.status,
        }

    def _serialize_article(self, article: NewsArticleModel) -> dict[str, Any]:
        return {
            "id": article.id,
            "headline": article.headline,
            "url": article.url,
            "canonical_url": article.canonical_url,
            "source": article.source,
            "tickers": list(article.tickers or []),
            "priority": article.priority,
            "tier": article.tier,
            "source_flag": article.source_flag,
            "sentiment": article.sentiment,
            "impact": article.impact,
            "threat": article.threat,
            "cluster_id": article.cluster_id,
            "summary": article.summary,
            "has_content": bool(str(article.content or article.summary or "").strip()),
            "status": article.status,
        }

    def _build_summary(self, headline: str, classified: dict[str, Any]) -> str:
        return (
            f"{headline} | sentiment={classified['sentiment']} | "
            f"impact={classified['impact']} | threat={classified['threat']}"
        )

    def _require_db(self) -> AsyncSession:
        if self.db is None:
            raise RuntimeError("database_session_required")
        return self.db


def get_news_intelligence_service(db: AsyncSession | None = None) -> NewsIntelligenceService:
    return NewsIntelligenceService(db)
