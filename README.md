# web2md

Лёгкий скрапер: берёт веб-страницу, чистит от мусора и выдаёт **чистый Markdown** — удобно для чтения, RAG и LLM-агентов.

Идея повторяет ядро проектов вроде [Crawl4AI](https://github.com/unclecode/crawl4ai) и [Scrapling](https://github.com/D4Vinci/Scrapling), но без тяжёлых браузеров (Playwright) и внешних API — работает за секунды на трёх лёгких библиотеках.

## Возможности

- Одиночный режим: один URL → Markdown (в консоль или в файл).
- Батч-режим: файл со списком URL → по одному `.md`-файлу на каждую страницу + сводка в JSON.
- Экспорт в JSON (title, url, длина, текст).
- Чистка шума: `<script>`, `<style>`, `<nav>`, `<footer>`, формы, рекламные/cookie-виджеты.
- Выбор основного контента (`article`, `main`, `#content` и т.п.) или `<body>`.
- Ограничение длины вывода (`--max-len`).

## Установка

Нужен Python 3.10+.

```bash
git clone https://github.com/pavelvladimirovich258614-sys/web2md.git
cd web2md
pip install -r requirements.txt
```

## Управление через CLI (supercli.py)

Поверх движка есть CLI-обёртка с под-командами (нужен `click`):

```bash
python supercli.py --help                 # список команд
python supercli.py one <url> --out page.md # одна страница -> файл
python supercli.py one <url> --json r.json # + JSON-запись
python supercli.py show <url> --max-len 1000 # превью в терминале, без сохранения
python supercli.py batch urls.txt --outdir ./out --json results.json  # батч
python supercli.py stats results.json       # сводка по батчу: ✓/✗, длина/ошибка
```

Под-команды:

| Команда | Что делает |
|---|---|
| `one <url>` | одна страница -> Markdown (и/или JSON) |
| `batch <file>` | список URL (по одному на строку, `#` = коммент) -> папка `.md` + сводка |
| `show <url>` | превью основного текста в терминале, без сохранения |
| `stats <file>` | сводка по результатам батча из `results.json` (✓/✗) |

Флаги те же, что у `web2md.py`: `--max-len`, `--raw`, `--timeout`.

## Использование

### Одна страница

```bash
# вывести в консоль
python web2md.py https://example.com

# сохранить в файл
python web2md.py https://example.com --out page.md

# ограничить длину
python web2md.py https://example.com --max-len 4000 --out page.md

# плюс JSON-запись (title, url, длина, текст)
python web2md.py https://example.com --out page.md --json page.json
```

### Список URL (батч)

Создай файл `urls.txt` (по одной ссылке на строку, строки с `#` игнорируются):

```
https://example.com
https://en.wikipedia.org/wiki/Web_scraping
# это комментарий, пропускается
https://news.ycombinator.com
```

Запусти:

```bash
python web2md.py --batch urls.txt --outdir ./out --json results.json
```

Результат:
- `out/<домен_путь>.md` — Markdown для каждой страницы;
- `results.json` — сводка: url, ok, title, длина (без самого текста, чтобы файл был компактным).

### Флаги

| Флаг | Описание |
|---|---|
| `--out FILE` | Куда писать Markdown (одиночный режим) |
| `--batch FILE` | Файл со списком URL (батч-режим) |
| `--outdir DIR` | Папка для `.md`-файлов (батч-режим) |
| `--json FILE` | Записать JSON-сводку/запись |
| `--max-len N` | Обрезать вывод до N символов |
| `--raw` | Не чистить шум (для проверки) |
| `--timeout S` | Таймаут запроса, сек (по умолчанию 20) |

## Ограничения

- Только статичный HTML (без JS-рендеринга). Сайты, которые рисуют контент через JavaScript, отдадут пустой/неполный результат — для них нужен браузерный движок (Playwright), это следующий шаг развития.
- Обходит не всю антибот-защиту — для Cloudflare/Turnstile нужна тяжёлая версия.
