#!/usr/bin/env python3
"""crew_pipeline.py — CrewAI research crew powered by the web2md engine.

web2md exposes the scraping engine as a CrewAI tool so that a small crew of
agents can fetch a page, clean it to Markdown and summarize it for RAG/LLM use.

Dependencies (see requirements.txt):
    - crewai>=0.70
    - the web2md engine (web2md.py)

Configuration (read from environment, none are required to import the module):
    - OPENAI_API_KEY          — provider key for the agents' LLM
    - CREW_MODEL              — model id (default: gpt-4o-mini)
    - WEB2MD_MAX_LEN          — default Markdown cap for the tool (default: 6000)
    - WEB2MD_TIMEOUT          — fetch timeout in seconds (default: 20)

Run:
    python crew_pipeline.py "https://example.com"
    python crew_pipeline.py "https://example.com" --max-len 8000
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from crewai import Agent, Crew, Process, Task
from crewai.tools import tool

import web2md

DEFAULT_MODEL = os.getenv("CREW_MODEL", "gpt-4o-mini")
DEFAULT_MAX_LEN = int(os.getenv("WEB2MD_MAX_LEN", "6000"))
DEFAULT_TIMEOUT = float(os.getenv("WEB2MD_TIMEOUT", "20"))


def _len_arg(value: Optional[str], default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@tool("scrape_to_md")
def scrape_to_md_tool(url: str, max_len: Optional[int] = None) -> str:
    """Fetch a web page and return its main content as clean Markdown.

    Use this to read a URL for the user. The page is fetched, navigation/footer
    noise is stripped, the main article is selected and converted to Markdown.
    """
    cap = _len_arg(max_len, DEFAULT_MAX_LEN)
    record = web2md.process_url(url, raw=False, max_len=cap, timeout=DEFAULT_TIMEOUT)
    if not record["ok"]:
        return f"Failed to scrape {url}: {record['error']}"
    return record["markdown"]


def build_crew(model: str = DEFAULT_MODEL, max_len: int = DEFAULT_MAX_LEN) -> Crew:
    researcher = Agent(
        role="Web Researcher",
        goal="Fetch the requested web page with the scrape_to_md tool and return "
             "the full, clean Markdown content verbatim.",
        backstory="A meticulous data collector specialized in extracting the main "
                  "textual content from any web page and removing navigation, ads "
                  "and boilerplate.",
        tools=[scrape_to_md_tool],
        allow_delegation=False,
        verbose=True,
        llm=model,
    )

    analyst = Agent(
        role="Content Analyst",
        goal="Produce a concise structured summary of the page: a one-sentence "
             "topic, 3-7 key points and a short 'why it matters' note.",
        backstory="An analyst who turns long documents into tight, faithful, "
                  "non-hallucinated briefings for retrieval and human reading.",
        allow_delegation=False,
        verbose=True,
        llm=model,
    )

    fetch_task = Task(
        description=(
            "Scrape the page at the following URL using the scrape_to_md tool and "
            "return the complete Markdown content it produces. URL: {url}"
        ),
        expected_output="The full Markdown content of the page, returned verbatim.",
        agent=researcher,
    )

    summarize_task = Task(
        description=(
            "Based on the Markdown returned by the previous task, write a faithful "
            "summary: a one-sentence topic, 3-7 bullet key points, and a short "
            "'Why it matters' note. Do not invent facts not present in the content. "
            "Respect the cap of {max_len} characters if provided."
        ),
        expected_output=(
            "A structured Markdown summary with a topic line, key points and a "
            "'Why it matters' note."
        ),
        agent=analyst,
        context=[fetch_task],
    )

    return Crew(
        agents=[researcher, analyst],
        tasks=[fetch_task, summarize_task],
        process=Process.sequential,
        verbose=True,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="web2md + CrewAI: scrape a page and summarize it.")
    p.add_argument("url", help="URL of the page to scrape and summarize.")
    p.add_argument("--model", default=DEFAULT_MODEL, help="LLM model id.")
    p.add_argument("--max-len", type=int, default=DEFAULT_MAX_LEN,
                   help="Character cap passed to the scrape tool.")
    args = p.parse_args(argv)

    crew = build_crew(model=args.model, max_len=args.max_len)
    inputs = {"url": args.url, "max_len": args.max_len}
    try:
        result = crew.kickoff(inputs=inputs)
    except Exception as exc:
        print(f"crew failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("\n===== CREW RESULT =====\n")
    print(str(result.raw) if hasattr(result, "raw") else str(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
