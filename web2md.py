#!/usr/bin/env python3
"""web2md.py — lightweight web-to-Markdown scraper.

A minimal, dependency-light reimplementation of the core idea behind
Crawl4AI / Scrapling: fetch a page, strip noise, return clean Markdown.
Supports HTML pages and PDF documents (text-layer PDFs).
Uses only light packages:
httpx (fetch), beautifulsoup4 (parse/clean), markdownify (HTML->Markdown),
pypdf (PDF -> text).

Usage (single page):
    python3 web2md.py <url> [--out FILE] [--max-len N] [--raw]

Batch mode (many pages from a file, one URL per line):
    python3 web2md.py --batch urls.txt --outdir ./out [--json results.json]

JSON export for a single page:
    python3 web2md.py <url> --json page.json
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

USER_AGENT = (
    "Mozilla/5.0 (compatible; web2md/0.1; +https://example/bot) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Tags that carry no textual content value for LLM/RAG use.
NOISE_TAGS = [
    "script", "style", "noscript", "template", "iframe", "svg", "canvas",
    "nav", "footer", "header", "aside", "form", "button", "input",
    "select", "textarea", "figure figcaption",
]

# Likely "main content" candidates, in priority order.
MAIN_SELECTORS = [
    "article", "main", "[role='main']",
    "#content", "#main-content", ".content", ".main", ".post", ".article",
]


def fetch(url: str, timeout: float = 20.0) -> tuple[str, str]:
    """Fetch a URL and return (content, content_type).

    For HTML the content is decoded text; for PDF it is the raw bytes.
    The content_type is the lowercased Content-Type header (without params).
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,*/*"}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=timeout) as client:
        r = client.get(url)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "text/html").split(";")[0].strip().lower()
        if "pdf" in ctype:
            return r.content, ctype
        return r.text, ctype


def strip_noise(soup: BeautifulSoup) -> None:
    for selector in NOISE_TAGS:
        for el in soup.select(selector):
            el.decompose()
    for el in soup.find_all(attrs={"class": True}):
        cls = " ".join(el.get("class", []))
        if any(w in cls for w in ("advert", "cookie", "popup", "social-share", "comments")):
            el.decompose()
    for el in soup.select("meta, link"):
        el.decompose()


def pick_main(soup: BeautifulSoup) -> BeautifulSoup:
    for sel in MAIN_SELECTORS:
        found = soup.select_one(sel)
        if found and len(found.get_text(strip=True)) > 200:
            return found
    body = soup.body or soup
    return body


def clean_markdown(md: str, max_len: int | None) -> str:
    lines = [ln.rstrip() for ln in md.splitlines()]
    out, blanks = [], 0
    for ln in lines:
        if ln.strip() == "":
            blanks += 1
            if blanks <= 1:
                out.append("")
        else:
            blanks = 0
            out.append(ln)
    md = "\n".join(out).strip()
    if max_len and len(md) > max_len:
        md = md[:max_len].rsplit(" ", 1)[0] + "\n…[truncated]"
    return md


def to_markdown(html: str, url: str, *, raw: bool = False, max_len: int | None) -> str:
    soup = BeautifulSoup(html, "html.parser")

    title = (soup.title.string.strip() if soup.title and soup.title.string
             else urlparse(url).netloc)

    if not raw:
        strip_noise(soup)
        root = pick_main(soup)
    else:
        root = soup.body or soup

    md = html_to_md(str(root), heading_style="ATX", strip=["img"])
    md = clean_markdown(md, max_len)

    header = f"# {title}\n\nSource: <{url}>\n\n---\n\n"
    return header + md


def pdf_to_markdown(data: bytes, url: str, *, max_len: int | None) -> str:
    """Extract text from a PDF byte stream and return it as Markdown.

    Uses pypdf (imported lazily so the dependency is optional for HTML-only use).
    Scanned/image-only PDFs without a text layer yield little/no text.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF support: pip install pypdf") from exc

    title = urlparse(url).path.rsplit("/", 1)[-1] or urlparse(url).netloc
    reader = PdfReader(io.BytesIO(data))
    parts: list[str] = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            parts.append(f"## Page {i}\n\n{text}")
    body = "\n\n".join(parts).strip()
    md = clean_markdown(body, max_len)
    header = f"# {title}\n\nSource: <{url}> (PDF, {len(reader.pages)} page(s))\n\n---\n\n"
    return header + md


def process_url(url: str, *, raw: bool, max_len: int | None, timeout: float) -> dict:
    """Fetch + convert one URL. Returns a result record (for JSON).

    Routes automatically by Content-Type: HTML -> BeautifulSoup, PDF -> pypdf.
    """
    record = {"url": url, "ok": False, "error": None,
              "title": None, "markdown": None, "length": 0}
    try:
        content, ctype = fetch(url, timeout=timeout)
    except httpx.HTTPError as e:
        record["error"] = f"fetch failed: {e}"
        return record
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
        return record

    try:
        if "pdf" in ctype:
            md = pdf_to_markdown(content, url, max_len=max_len)
        else:
            md = to_markdown(content, url, raw=raw, max_len=max_len)
    except Exception as e:
        record["error"] = f"convert failed: {type(e).__name__}: {e}"
        return record

    title_line = md.splitlines()[0].lstrip("# ").strip() if md else url
    record.update(ok=True, title=title_line, markdown=md, length=len(md))
    return record


def safe_name(url: str) -> str:
    p = urlparse(url)
    base = (p.netloc + p.path).replace("/", "_").strip("_") or "page"
    return base[:80]


def run_batch(list_file: Path, outdir: Path, *, raw: bool, max_len: int | None,
              timeout: float, json_file: Path | None) -> int:
    urls = [ln.strip() for ln in list_file.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        print("error: no URLs found in file", file=sys.stderr)
        return 1
    outdir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}", file=sys.stderr)
        rec = process_url(url, raw=raw, max_len=max_len, timeout=timeout)
        results.append(rec)
        if rec["ok"]:
            outfile = outdir / f"{safe_name(url)}.md"
            outfile.write_text(rec["markdown"], encoding="utf-8")
            print(f"    -> {outfile} ({rec['length']} chars)", file=sys.stderr)
        else:
            print(f"    !! {rec['error']}", file=sys.stderr)

    if json_file:
        json_file.write_text(
            json.dumps(
                [{k: v for k, v in r.items() if k != "markdown"} for r in results],
                ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"summary json -> {json_file}", file=sys.stderr)

    ok = sum(1 for r in results if r["ok"])
    print(f"done: {ok}/{len(results)} ok", file=sys.stderr)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lightweight web-to-Markdown scraper.")
    p.add_argument("url", nargs="?", help="Page URL to convert (single mode)")
    p.add_argument("--batch", help="File with one URL per line (batch mode)")
    p.add_argument("--outdir", help="Directory for per-page Markdown files (batch)")
    p.add_argument("--out", help="Write Markdown to FILE instead of stdout (single)")
    p.add_argument("--json", help="Write JSON summary/record to FILE")
    p.add_argument("--max-len", type=int, help="Truncate output to N characters")
    p.add_argument("--raw", action="store_true", help="Skip noise stripping")
    p.add_argument("--timeout", type=float, default=20.0)
    args = p.parse_args(argv)

    if args.batch:
        list_file = Path(args.batch)
        if not list_file.is_file():
            print(f"error: file not found: {list_file}", file=sys.stderr)
            return 1
        outdir = Path(args.outdir or "./out")
        json_file = Path(args.json) if args.json else None
        return run_batch(list_file, outdir, raw=args.raw, max_len=args.max_len,
                         timeout=args.timeout, json_file=json_file)

    if not args.url:
        p.error("url is required (or use --batch FILE)")

    rec = process_url(args.url, raw=args.raw, max_len=args.max_len,
                      timeout=args.timeout)

    if args.json:
        Path(args.json).write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote json -> {args.json}", file=sys.stderr)

    if not rec["ok"]:
        print(f"error: {rec['error']}", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_text(rec["markdown"], encoding="utf-8")
        print(f"wrote {rec['length']} chars -> {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(rec["markdown"] + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
