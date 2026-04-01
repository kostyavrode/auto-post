"""
Web scraper for news sites without RSS.

Two modes:
  1. AUTO (default) — no selectors needed. Fetches the listing page, finds all
     article-looking links, then visits each one and uses trafilatura to extract
     title, body, and the main image automatically.
  2. MANUAL — CSS selectors provided in source config. Works like before.

Auto mode works on virtually any news site out of the box.
"""
import asyncio
import logging
import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from .rss import RawArticle

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Links that are clearly not articles
_SKIP_PATTERNS = re.compile(
    r"(#|javascript:|mailto:|tel:|\.pdf$|\.zip$|/tag/|/tags/|/author/|"
    r"/category/|/page/\d|/search|/login|/register|/about|/contact|"
    r"/privacy|/terms|/rss|/feed)",
    re.IGNORECASE,
)


async def fetch_scraper(source: dict) -> List[RawArticle]:
    """Entry point. Auto-detects mode based on whether selectors are set."""
    if source.get("article_selector"):
        return await _fetch_with_selectors(source)
    return await _fetch_auto(source)


# ─────────────────────────────────────────────────────────────────
#  AUTO MODE
# ─────────────────────────────────────────────────────────────────

async def _fetch_auto(source: dict) -> List[RawArticle]:
    """
    1. Fetch the listing page.
    2. Collect candidate article URLs from <a> tags.
    3. For each URL, fetch and extract content with trafilatura.
    """
    base_url = source["url"]
    source_name = source.get("name", base_url)
    source_id = source.get("id")
    max_articles = int(source.get("max_articles", 10))

    html = await _get(base_url)
    if not html:
        return []

    candidate_urls = _extract_article_links(html, base_url)
    if not candidate_urls:
        logger.warning("Auto-scraper %s: found 0 article links on %s", source_name, base_url)
        return []

    logger.info("Auto-scraper %s: found %d candidate links", source_name, len(candidate_urls))

    articles: List[RawArticle] = []
    # Fetch articles concurrently in small batches
    for batch in _chunks(candidate_urls[:max_articles], size=5):
        results = await asyncio.gather(*[
            _extract_article(url, source_name, source_id)
            for url in batch
        ], return_exceptions=True)
        for r in results:
            if isinstance(r, RawArticle):
                articles.append(r)

    logger.info("Auto-scraper %s: extracted %d articles", source_name, len(articles))
    return articles


async def _extract_article(url: str, source_name: str, source_id: Optional[int]) -> Optional[RawArticle]:
    """Fetch a single article page and extract content with trafilatura."""
    html = await _get(url)
    if not html:
        return None

    # trafilatura.extract returns the main text of the article
    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
    if not text or len(text.strip()) < 50:
        return None

    # trafilatura metadata gives us title and image
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else _title_from_html(html)) or url
    image_url = (meta.image if meta and meta.image else None)
    if image_url:
        image_url = urljoin(url, image_url)

    return RawArticle(
        url=url,
        title=title.strip(),
        body=text.strip(),
        image_url=image_url,
        source_name=source_name,
        source_id=source_id,
    )


def _extract_article_links(html: str, base_url: str) -> List[str]:
    """
    Heuristically pick article links from a listing page.

    Good article URLs tend to:
    - Be on the same domain
    - Have a path with 2+ segments or contain a date pattern
    - Not match skip patterns
    """
    base_domain = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "lxml")
    seen: set = set()
    links: List[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)

        if parsed.netloc != base_domain:
            continue
        if _SKIP_PATTERNS.search(parsed.path):
            continue
        if full in seen or full == base_url:
            continue

        path = parsed.path.rstrip("/")
        # Require at least one meaningful path segment
        segments = [s for s in path.split("/") if s]
        if not segments:
            continue

        seen.add(full)
        links.append(full)

    # Prioritise links that look like articles (have date or long slug)
    def _score(u: str) -> int:
        p = urlparse(u).path
        score = 0
        if re.search(r"/\d{4}/\d{2}", p):   # date in path
            score += 3
        if len(p.split("/")) >= 3:           # deep path
            score += 2
        if len(p) > 30:                       # long slug
            score += 1
        return score

    links.sort(key=_score, reverse=True)
    return links


# ─────────────────────────────────────────────────────────────────
#  MANUAL (CSS selectors) MODE
# ─────────────────────────────────────────────────────────────────

async def _fetch_with_selectors(source: dict) -> List[RawArticle]:
    """Classic selector-based scraper for sites that need custom targeting."""
    url = source["url"]
    source_name = source.get("name", url)
    source_id = source.get("id")

    article_sel = source["article_selector"]
    title_sel = source.get("title_selector", "h2, h3, h1")
    body_sel = source.get("body_selector", "p")
    link_sel = source.get("link_selector", "a")
    image_sel = source.get("image_selector", "img")

    html = await _get(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = soup.select(article_sel)

    if not items:
        logger.warning("Scraper %s: selector '%s' matched 0 elements", source_name, article_sel)
        return []

    articles: List[RawArticle] = []
    for item in items:
        title_tag = item.select_one(title_sel)
        title = title_tag.get_text(strip=True) if title_tag else ""

        link_tag = item.select_one(link_sel)
        href = link_tag.get("href", "") if link_tag else ""
        article_url = urljoin(url, href) if href else ""
        if not article_url:
            continue

        body_tags = item.select(body_sel)
        body = " ".join(t.get_text(strip=True) for t in body_tags)

        # If body is very short, try fetching and auto-extracting the full article
        if len(body) < 100 and article_url:
            full = await _extract_article(article_url, source_name, source_id)
            if full:
                articles.append(full)
                continue

        img_tag = item.select_one(image_sel)
        image_url: Optional[str] = None
        if img_tag:
            image_url = img_tag.get("src") or img_tag.get("data-src")
            if image_url:
                image_url = urljoin(url, image_url)

        articles.append(RawArticle(
            url=article_url,
            title=title,
            body=body,
            image_url=image_url,
            source_name=source_name,
            source_id=source_id,
        ))

    logger.info("Scraper %s (selectors): fetched %d articles", source_name, len(articles))
    return articles


# ─────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────

async def _get(url: str, timeout: int = 15) -> Optional[str]:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_UA},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.warning("HTTP error for %s: %s", url, exc)
        return None


def _title_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]
