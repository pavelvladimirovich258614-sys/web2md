#!/usr/bin/env python3
"""supercli.py — CLI-управление суперскрапером.

Под-команды:
    one <url>            одна страница -> Markdown (или --json)
    batch <file>         список URL -> папка .md + сводка
    show <url>            превью основного текста в терминале (без сохранения)
    stats <file>          сводка по результатам батча (из results.json)

Примеры:
    python supercli.py one https://example.com --out page.md
    python supercli.py batch urls.txt --outdir ./out --json results.json
    python supercli.py show https://example.com --max-len 1000
    python supercli.py stats results.json

Движок — web2md.py (httpx + beautifulsoup4 + markdownify).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

import web2md


def _echo_err(msg: str) -> None:
    click.secho(msg, fg="red", err=True)


def _echo_ok(msg: str) -> None:
    click.secho(msg, fg="green", err=True)


@click.group(help="Суперскрапер: веб -> чистый Markdown/JSON. Движком служит web2md.py.")
@click.version_option("0.2.0", prog_name="supercli")
def cli() -> None:
    pass


@cli.command("one", help="Одна страница -> Markdown (и/или JSON).")
@click.argument("url")
@click.option("--out", help="Файл для Markdown (иначе вывод в консоль).")
@click.option("--json", "json_file", help="Файл для JSON-записи.")
@click.option("--max-len", type=int, help="Обрезать вывод до N символов.")
@click.option("--raw", is_flag=True, help="Не чистить шум.")
@click.option("--timeout", type=float, default=20.0, help="Таймаут запроса, сек.")
def one(url, out, json_file, max_len, raw, timeout):
    rec = web2md.process_url(url, raw=raw, max_len=max_len, timeout=timeout)

    if json_file:
        Path(json_file).write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        _echo_ok(f"json -> {json_file}")

    if not rec["ok"]:
        _echo_err(f"ошибка: {rec['error']}")
        sys.exit(1)

    if out:
        Path(out).write_text(rec["markdown"], encoding="utf-8")
        _echo_ok(f"Markdown ({rec['length']} симв.) -> {out}")
    else:
        click.echo(rec["markdown"])


@cli.command("batch", help="Список URL (по одному на строку, # = коммент) -> папка .md + сводка.")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--outdir", default="./out", help="Папка для .md-файлов (по умолч. ./out).")
@click.option("--json", "json_file", help="Файл для JSON-сводки.")
@click.option("--max-len", type=int, help="Обрезать каждую страницу до N символов.")
@click.option("--raw", is_flag=True, help="Не чистить шум.")
@click.option("--timeout", type=float, default=20.0, help="Таймаут запроса, сек.")
def batch(file, outdir, json_file, max_len, raw, timeout):
    rc = web2md.run_batch(
        Path(file), Path(outdir),
        raw=raw, max_len=max_len, timeout=timeout,
        json_file=Path(json_file) if json_file else None,
    )
    sys.exit(rc)


@cli.command("show", help="Превью основного текста в терминале (без сохранения).")
@click.argument("url")
@click.option("--max-len", type=int, default=1200, help="Сколько символов показать.")
@click.option("--raw", is_flag=True, help="Не чистить шум.")
@click.option("--timeout", type=float, default=20.0, help="Таймаут запроса, сек.")
def show(url, max_len, raw, timeout):
    rec = web2md.process_url(url, raw=raw, max_len=max_len, timeout=timeout)
    if not rec["ok"]:
        _echo_err(f"ошибка: {rec['error']}")
        sys.exit(1)
    click.secho(f"{rec['title']}  ({rec['length']} симв.)", fg="cyan", bold=True)
    click.echo("-" * 60)
    click.echo(rec["markdown"])


@cli.command("stats", help="Сводка по результатам батча (из results.json).")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
def stats(file):
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except Exception as e:
        _echo_err(f"не читается json: {e}")
        sys.exit(1)
    total = len(data)
    ok = sum(1 for r in data if r.get("ok"))
    fail = total - ok
    click.secho(f"Всего: {total}  OK: {ok}  Ошибки: {fail}", bold=True)
    click.echo("-" * 60)
    for r in data:
        mark = click.style("✓", fg="green") if r.get("ok") else click.style("✗", fg="red")
        extra = f"{r.get('length', 0)} симв." if r.get("ok") else r.get("error", "")[:50]
        click.echo(f"{mark} {r.get('url')}  [{extra}]")


if __name__ == "__main__":
    cli()
