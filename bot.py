#!/usr/bin/env python3
"""bot.py — Telegram bot front-end for the web2md engine.

Users send a URL and get back the page's main content as clean Markdown. The
bot supports a /summarize command that delegates to the optional CrewAI crew
(crew_pipeline.py) when an LLM provider key is configured.

Configuration (environment / .env):
    TELEGRAM_BOT_TOKEN     — token from @BotFather (required to run)
    WEB2MD_MAX_LEN        — default Markdown cap (default: 6000)
    WEB2MD_TIMEOUT        — fetch timeout in seconds (default: 20)
    TG_MAX_REPLY          — hard reply size cap in characters (default: 4000)
    OPENAI_API_KEY        — required only for /summarize (CrewAI path)
    CREW_MODEL            — model id for the crew (default: gpt-4o-mini)

Run:
    python bot.py
"""
from __future__ import annotations

import logging
import os
import re
import sys
from typing import Optional

import web2md
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (ApplicationBuilder, CommandHandler, ContextTypes,
                          MessageHandler, filters)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("web2md.bot")

URL_RE = re.compile(r"https?://[^\s<>\"')]+")

DEFAULT_MAX_LEN = int(os.getenv("WEB2MD_MAX_LEN", "6000"))
DEFAULT_TIMEOUT = float(os.getenv("WEB2MD_TIMEOUT", "20"))
TG_MAX_REPLY = int(os.getenv("TG_MAX_REPLY", "4000"))
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _find_url(text: str) -> Optional[str]:
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,);") if m else None


def _chunks(text: str, size: int):
    for i in range(0, len(text), size):
        yield text[i:i + size]


async def _help_text() -> str:
    return (
        "*web2md bot*\n\n"
        "Send me a URL and I'll fetch the page and return its main content as "
        "clean Markdown.\n\n"
        "Commands:\n"
        "/start — about the bot\n"
        "/help — this message\n"
        "/scrape `<url> [max-len]` — fetch + Markdown\n"
        "/summary `<url>` — scrape + AI summary (needs OPENAI\\_API\\_KEY)\n"
        "\nExample:\n"
        "`/scrape https://example.com 3000`\n"
    )


def _scrape(url: str, max_len: int) -> dict:
    return web2md.process_url(url, raw=False, max_len=max_len,
                             timeout=DEFAULT_TIMEOUT)


async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *web2md* — turn any web page into clean Markdown.\n"
        "Send a URL or use /help.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(await _help_text(),
                                    parse_mode=ParseMode.MARKDOWN)


async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: /scrape <url> [max-len]", parse_mode=ParseMode.MARKDOWN)
        return
    url = args[0]
    max_len = DEFAULT_MAX_LEN
    if len(args) > 1:
        try:
            max_len = int(args[1])
        except ValueError:
            await update.message.reply_text("max-len must be an integer.")
            return
    await _reply_scrape(update, url, max_len)


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /summary <url>", parse_mode=ParseMode.MARKDOWN)
        return
    url = context.args[0]
    if not os.getenv("OPENAI_API_KEY"):
        await update.message.reply_text(
            "⚠️ /summary needs an LLM key (OPENAI_API_KEY). "
            "Use /scrape instead.")
        return
    await update.message.reply_text("🔍 scraping + analyzing…")
    try:
        import crew_pipeline
        crew = crew_pipeline.build_crew(max_len=DEFAULT_MAX_LEN)
        result = crew.kickoff(inputs={"url": url, "max_len": DEFAULT_MAX_LEN})
        text = str(getattr(result, "raw", result) or result)
    except Exception as exc:
        log.exception("crew failed")
        await update.message.reply_text(f"❌ summary failed: {exc}")
        return
    await _send_chunks(update, text)


async def on_url(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    url = _find_url(update.message.text if update.message else "")
    if not url:
        await update.message.reply_text(
            "Send a URL, e.g. https://example.com", parse_mode=ParseMode.MARKDOWN)
        return
    await _reply_scrape(update, url, DEFAULT_MAX_LEN)


async def _reply_scrape(update: Update, url: str, max_len: int) -> None:
    await update.message.reply_text("⏳ fetching…")
    rec = _scrape(url, max_len)
    if not rec["ok"]:
        await update.message.reply_text(f"❌ {rec['error']}")
        return
    head = f"*{rec['title']}*  ({rec['length']} chars)\nSource: {url}\n\n"
    await _send_chunks(update, head + rec["markdown"])


async def _send_chunks(update: Update, text: str) -> None:
    for part in _chunks(text, TG_MAX_REPLY):
        await update.message.reply_text(part, parse_mode=ParseMode.MARKDOWN)


def main() -> int:
    if not TG_TOKEN:
        print("error: set TELEGRAM_BOT_TOKEN (see .env.example)", file=sys.stderr)
        return 1
    app = (ApplicationBuilder().token(TG_TOKEN)
           .add_handler(CommandHandler("start", cmd_start))
           .add_handler(CommandHandler("help", cmd_help))
           .add_handler(CommandHandler("scrape", cmd_scrape))
           .add_handler(CommandHandler("summary", cmd_summary))
           .add_handler(MessageHandler(
               filters.TEXT & ~filters.COMMAND, on_url))
           .build())
    log.info("web2md bot starting (polling)…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
