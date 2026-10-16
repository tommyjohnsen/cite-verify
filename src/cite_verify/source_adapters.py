from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .cache import LocalCache
from .courtlistener import Lookup
from .extract import ExtractedCitation, normalize_citation

FUZZY_THRESHOLD = 0.88
GOVINFO = "https://api.govinfo.gov"
ECFR = "https://www.ecfr.gov/api/versioner/v1"
WASHINGTON = "https://app.leg.wa.gov"
CROSSREF = "https://api.crossref.org"
OPENALEX = "https://api.openalex.org"

GetTransport = Callable[[str, dict[str, str]], tuple[int, dict[str, str], bytes]]


def get_transport(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request) as response:
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_citation(left), normalize_citation(right)).ratio()


def _json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _first_item(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    for key in ("results", "items", "packages"):
        value = data.get(key)
        if isinstance(value, list):
            return value[0] if value and isinstance(value[0], dict) else {}
    message = data.get("message")
    if isinstance(message, dict):
        items = message.get("items")
        if isinstance(items, list):
            return items[0] if items and isinstance(items[0], dict) else {}
        return message
    return data


class CachedAdapter:
    source = "source"

    def __init__(self, cache: LocalCache, transport: GetTransport = get_transport) -> None:
        self.cache = cache
        self.transport = transport

    def verify(self, citation: ExtractedCitation) -> Lookup:
        cached = self.cache.get(self.source, citation.normalized)
        if cached is not None:
            return Lookup(**cached)
        value = self.fetch(citation)
        self.cache.put(self.source, citation.normalized, value.cache_value())
        return value

    def verify_many(self, citations: Iterable[ExtractedCitation]) -> dict[str, Lookup]:
        return {cite.normalized: self.verify(cite) for cite in citations}

    def fetch(self, citation: ExtractedCitation) -> Lookup:
        raise NotImplementedError


class GovInfoAdapter(CachedAdapter):
    source = "govinfo"

    def __init__(self, api_key: str, cache: LocalCache, transport: GetTransport = get_transport) -> None:
        super().__init__(cache, transport)
        self.api_key = api_key

    def verify(self, citation: ExtractedCitation) -> Lookup:
        if not self.api_key:
            return Lookup(0, reason="govinfo skipped: no GOVINFO_API_KEY")
        return super().verify(citation)

    def fetch(self, citation: ExtractedCitation) -> Lookup:
        collection = "USCODE" if citation.kind == "usc" else "CFR"
        query = f'{citation.field("title")} {collection} {citation.field("section")}'
        params = urlencode({"query": query, "pageSize": 10, "offsetMark": "*", "api_key": self.api_key})
        url = f"{GOVINFO}/search?{params}"
        status, _, body = self.transport(url, {"Accept": "application/json"})
        if status != 200:
            return Lookup(status, source_url=url.split("?", 1)[0], reason="not found" if status == 404 else f"HTTP {status}")
        item = _first_item(_json(body))
        authoritative = str(item.get("citation") or item.get("title") or item.get("packageTitle") or "")
        source_url = str(item.get("detailsLink") or item.get("url") or item.get("packageLink") or url.split("?", 1)[0])
        return _citation_match(citation, authoritative, source_url, "section number")


class ECFRAdapter(CachedAdapter):
    source = "ecfr"

    def fetch(self, citation: ExtractedCitation) -> Lookup:
        title, section = citation.field("title"), citation.field("section")
        url = f"{ECFR}/full/current/title-{quote(title)}.json?{urlencode({'section': section})}"
        status, _, body = self.transport(url, {"Accept": "application/json"})
        if status != 200:
            return Lookup(status, source_url=url, reason="not found" if status == 404 else f"HTTP {status}")
        data = _json(body)
        item = _first_item(data)
        returned_section = str(item.get("section") or item.get("identifier") or item.get("label") or section)
        heading = str(item.get("heading") or item.get("title") or item.get("subject") or "")
        authority = f"{title} C.F.R. § {returned_section}"
        reason = "section exists" + (f": {heading}" if heading else "")
        return _citation_match(citation, authority, url, "section number", reason)


class _HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.heading = ""
        self._capture = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"h1", "h2", "h3", "title"} and not self.heading:
            self._capture = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"h1", "h2", "h3", "title"}:
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self.heading += data


class WashingtonAdapter(CachedAdapter):
    source = "washington"

    def fetch(self, citation: ExtractedCitation) -> Lookup:
        code = citation.kind.upper()
        section = citation.field("section")
        url = f"{WASHINGTON}/{code}/default.aspx?{urlencode({'cite': section})}"
        status, _, body = self.transport(url, {"Accept": "text/html"})
        if status != 200:
            return Lookup(status, source_url=url, reason="not found" if status == 404 else f"HTTP {status}")
        parser = _HeadingParser()
        try:
            parser.feed(body.decode("utf-8", errors="replace"))
        except ValueError:
            return Lookup(0, source_url=url, reason="invalid response")
        heading = re.sub(r"\s+", " ", parser.heading).strip()
        if section.casefold() not in body.decode("utf-8", errors="replace").casefold():
            return Lookup(404, source_url=url, reason="section not present in official page")
        authority = f"{code} {section}"
        supplied_heading = citation.field("heading")
        if supplied_heading:
            score = similarity(supplied_heading, heading)
            if score < FUZZY_THRESHOLD:
                return Lookup(404, source_url=url, reason=f"heading similarity below {FUZZY_THRESHOLD:.2f}")
            if normalize_citation(supplied_heading) != normalize_citation(heading):
                authority += f", {heading}"
                return Lookup(200, authority, url, "section number+heading", f"fuzzy heading match ({score:.2f})")
        return _citation_match(citation, authority, url, "section number", f"section exists; heading: {heading}" if heading else "section exists")


def _citation_match(citation: ExtractedCitation, authority: str, url: str, field: str,
                    exact_reason: str = "authoritative match") -> Lookup:
    if not authority:
        return Lookup(404, source_url=url, reason="not found")
    if normalize_citation(authority) == citation.normalized:
        return Lookup(200, authority, url, field, exact_reason)
    # Section identity is authoritative even when publisher punctuation differs.
    section = citation.field("section")
    if section and section.casefold() in authority.casefold():
        return Lookup(200, authority, url, field, exact_reason)
    return Lookup(404, source_url=url, reason="authoritative result did not match")


def _metadata(item: dict[str, Any]) -> dict[str, str]:
    title = item.get("title", "")
    if isinstance(title, list):
        title = title[0] if title else ""
    container = item.get("container-title") or item.get("host_venue", {}).get("display_name", "")
    if isinstance(container, list):
        container = container[0] if container else ""
    year = item.get("publication_year") or item.get("year") or ""
    if not year:
        parts = item.get("published", {}).get("date-parts", [[]])
        year = parts[0][0] if parts and parts[0] else ""
    page = str(item.get("page") or item.get("biblio", {}).get("first_page") or "").split("-", 1)[0]
    authors: list[str] = []
    raw_authors = item.get("author")
    if isinstance(raw_authors, list):
        for author in raw_authors:
            if isinstance(author, dict):
                authors.append(str(author.get("family") or author.get("name") or ""))
    raw_authorships = item.get("authorships")
    if isinstance(raw_authorships, list):
        for authorship in raw_authorships:
            if isinstance(authorship, dict):
                author = authorship.get("author", {})
                if isinstance(author, dict):
                    display = str(author.get("display_name") or "")
                    authors.append(display.rsplit(" ", 1)[-1])
    return {"doi": str(item.get("DOI") or item.get("doi") or "").removeprefix("https://doi.org/"),
            "author": " and ".join(filter(None, authors)), "title": str(title), "journal": str(container), "year": str(year),
            "volume": str(item.get("volume") or item.get("biblio", {}).get("volume") or ""), "page": page}


class JournalAdapter(CachedAdapter):
    def __init__(self, cache: LocalCache, *, contact_email: str = "", api_key: str = "",
                 transport: GetTransport = get_transport) -> None:
        super().__init__(cache, transport)
        self.contact_email = contact_email
        self.api_key = api_key

    def item_url(self, citation: ExtractedCitation) -> str:
        raise NotImplementedError

    def fetch(self, citation: ExtractedCitation) -> Lookup:
        url = self.item_url(citation)
        status, _, body = self.transport(url, {"Accept": "application/json"})
        if status != 200:
            return Lookup(status, source_url=url, reason="not found" if status == 404 else f"HTTP {status}")
        item = _first_item(_json(body))
        meta = _metadata(item)
        doi = citation.field("doi")
        source_url = str(item.get("URL") or item.get("id") or (f"https://doi.org/{meta['doi']}" if meta["doi"] else url))
        if doi:
            if normalize_citation(doi) == normalize_citation(meta["doi"]):
                return Lookup(200, meta["doi"], source_url, "DOI", "exact DOI match")
            return Lookup(404, source_url=source_url, reason="DOI not found")
        title_score = similarity(citation.field("title"), meta["title"])
        exact_fields = all(not citation.field(key) or not meta[key] or
                           normalize_citation(citation.field(key)) == normalize_citation(meta[key])
                           for key in ("author", "title", "year", "journal", "volume", "page"))
        authority = _article_form(meta)
        if exact_fields:
            return Lookup(200, citation.text, source_url, "title+authors+year+journal+volume+first page", "exact metadata match")
        author_matches = (not citation.field("author") or not meta["author"] or
                          normalize_citation(citation.field("author")) == normalize_citation(meta["author"]))
        if title_score >= FUZZY_THRESHOLD and citation.field("year") == meta["year"] and author_matches:
            return Lookup(200, authority, source_url, "title+authors+year", f"fuzzy title match ({title_score:.2f})")
        return Lookup(404, source_url=source_url, reason=f"metadata similarity below {FUZZY_THRESHOLD:.2f}")


def _article_form(meta: dict[str, str]) -> str:
    parts = [part for part in (meta["author"], meta["title"]) if part]
    publication = " ".join(part for part in (meta["volume"], meta["journal"], meta["page"]) if part)
    if publication:
        parts.append(publication)
    if meta["year"]:
        parts.append(f"({meta['year']})")
    return ", ".join(parts)


class CrossrefAdapter(JournalAdapter):
    source = "crossref"

    def item_url(self, citation: ExtractedCitation) -> str:
        params = {"mailto": self.contact_email} if self.contact_email else {}
        if citation.field("doi"):
            base = f"{CROSSREF}/works/{quote(citation.field('doi'), safe='')}"
        else:
            base = f"{CROSSREF}/works"
            params.update({"query.bibliographic": citation.text, "rows": 1})
        return base + ("?" + urlencode(params) if params else "")


class OpenAlexAdapter(JournalAdapter):
    source = "openalex"

    def item_url(self, citation: ExtractedCitation) -> str:
        params: dict[str, str | int] = {}
        if self.contact_email:
            params["mailto"] = self.contact_email
        if self.api_key:
            params["api_key"] = self.api_key
        if citation.field("doi"):
            base = f"{OPENALEX}/works/https://doi.org/{quote(citation.field('doi'), safe='/')}"
        else:
            base = f"{OPENALEX}/works"
            params.update({"search": citation.field("title"), "per-page": 1})
        return base + ("?" + urlencode(params) if params else "")


@dataclass(frozen=True, slots=True)
class EthicsSource:
    issuer: str
    citation_pattern: str
    url_template: str = ""
    index_url: str = ""


def load_ethics_sources(path: str | Path | None) -> list[EthicsSource]:
    if path is None:
        return []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw.get("sources", []) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("ethics sources must be a JSON list")
    return [EthicsSource(str(row["issuer"]), str(row["citation_pattern"]),
                         str(row.get("url_template", "")), str(row.get("index_url", ""))) for row in rows]


def extract_ethics_citations(text: str, sources: Iterable[EthicsSource]) -> list[ExtractedCitation]:
    found: list[ExtractedCitation] = []
    for source in sources:
        pattern = re.compile(source.citation_pattern, re.I)
        for match in pattern.finditer(text):
            groups = {key: value for key, value in match.groupdict().items() if value is not None}
            if "number" not in groups:
                continue
            groups["issuer"] = source.issuer
            groups["url_template"] = source.url_template
            groups["index_url"] = source.index_url
            found.append(ExtractedCitation(match.group(), normalize_citation(match.group()), match.start(), "ethics",
                                           tuple(groups.items())))
    return sorted(found, key=lambda item: item.location)


class BarEthicsAdapter(CachedAdapter):
    source = "bar-ethics"

    def fetch(self, citation: ExtractedCitation) -> Lookup:
        number = citation.field("number")
        template = citation.field("url_template")
        url = template.format(number=quote(number)) if template else citation.field("index_url")
        if not url:
            return Lookup(0, reason="source has no official URL")
        status, _, body = self.transport(url, {"Accept": "text/html, application/json"})
        if status != 200:
            return Lookup(status, source_url=url, reason="not found" if status == 404 else f"HTTP {status}")
        content = body.decode("utf-8", errors="replace")
        if number.casefold() not in content.casefold():
            return Lookup(404, source_url=url, reason="opinion number not present in official source")
        title = citation.field("title")
        date = citation.field("date")
        if title and title.casefold() not in content.casefold():
            candidates = re.findall(r"<(?:h1|h2|title)[^>]*>(.*?)</(?:h1|h2|title)>", content, re.I | re.S)
            clean = [re.sub(r"<[^>]+>", "", item) for item in candidates]
            score = max((similarity(title, item) for item in clean), default=0.0)
            if score < FUZZY_THRESHOLD:
                return Lookup(404, source_url=url, reason=f"title similarity below {FUZZY_THRESHOLD:.2f}")
            reason = f"opinion number and fuzzy title match ({score:.2f})"
        elif date and date not in content:
            return Lookup(404, source_url=url, reason="opinion date did not match")
        else:
            reason = "opinion number and supplied metadata match" if title or date else "opinion number match"
        authority = f"{citation.field('issuer')} opinion {number}"
        return Lookup(200, authority, url, "opinion number" + ("+title" if title else "+date" if date else ""), reason)
