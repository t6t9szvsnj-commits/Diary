"""Собирает data.json для приложения: курсы, сырьё, новости, расписание.

Запускается в GitHub Actions по расписанию. Телефон сам ходить по этим
сайтам не может (браузер блокирует чужие ответы без CORS), поэтому всё
собирается здесь и отдаётся одним файлом рядом с приложением.

Каждый раздел собирается независимо: если упал один источник, остальные
всё равно попадут в файл. Если раздел не удалось обновить, берём его из
прошлой выкладки и помечаем как устаревший — лучше старые цифры с пометкой,
чем пустая карточка.
"""

import argparse
import html
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "Mozilla/5.0 (personal-diary-bot)"
TIMEOUT = 20

CURRENCIES = [
    ("USD", "Доллар"),
    ("EUR", "Евро"),
    ("CNY", "Юань"),
]

# Yahoo отдаёт котировки фьючерсов без ключа; stooq — запасной вариант,
# потому что Yahoo время от времени режет запросы с серверов GitHub.
COMMODITIES = [
    {"id": "brent", "label": "Нефть Brent", "unit": "$/барр.",
     "yahoo": "BZ=F", "stooq": "cb.f"},
    {"id": "gold", "label": "Золото", "unit": "$/унция",
     "yahoo": "GC=F", "stooq": "gc.f"},
]

NEWS_FEEDS = [
    ("Хабр", "https://habr.com/ru/rss/news/?fl=ru"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch", "https://techcrunch.com/feed/"),
    ("Hacker News", "https://hnrss.org/frontpage?points=200"),
]
NEWS_PER_FEED = 6
NEWS_TOTAL = 20

ATOM = "{http://www.w3.org/2005/Atom}"


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


# --- курсы ЦБ -------------------------------------------------------------

def parse_cbr(raw):
    data = json.loads(raw)
    valutes = data["Valute"]
    items = []
    for code, label in CURRENCIES:
        v = valutes[code]
        # Юань и прочие иногда котируются за 10 или 100 единиц.
        nominal = v.get("Nominal", 1) or 1
        value = v["Value"] / nominal
        prev = v["Previous"] / nominal
        items.append({
            "id": code, "label": label, "unit": "₽",
            "value": round(value, 4), "change": round(value - prev, 4),
        })
    return {"items": items, "date": data.get("Date")}


def fetch_rates():
    return parse_cbr(http_get("https://www.cbr-xml-daily.ru/daily_json.js"))


# --- нефть и золото -------------------------------------------------------

def parse_yahoo_chart(raw):
    result = json.loads(raw)["chart"]["result"][0]
    closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    price = result["meta"].get("regularMarketPrice")
    if price is None:
        if not closes:
            raise ValueError("в ответе Yahoo нет цен")
        price = closes[-1]
    # Последняя свеча — это текущий день, поэтому «вчера» — предпоследняя.
    prev = closes[-2] if len(closes) >= 2 else None
    change = round(price - prev, 2) if prev is not None else None
    return round(price, 2), change


def parse_stooq_csv(raw):
    lines = raw.decode("utf-8", "replace").strip().splitlines()
    if len(lines) < 2:
        raise ValueError("пустой ответ stooq")
    header = [h.strip().lower() for h in lines[0].split(",")]
    row = lines[1].split(",")
    close = row[header.index("close")]
    if close in ("", "N/D"):
        raise ValueError("stooq не знает этот тикер")
    return round(float(close), 2), None


def fetch_commodity(spec):
    errors = []
    try:
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
               f"{spec['yahoo']}?range=5d&interval=1d")
        return parse_yahoo_chart(http_get(url))
    except Exception as e:
        errors.append(f"yahoo: {e}")
    try:
        url = f"https://stooq.com/q/l/?s={spec['stooq']}&f=sd2t2c&h&e=csv"
        return parse_stooq_csv(http_get(url))
    except Exception as e:
        errors.append(f"stooq: {e}")
    raise RuntimeError("; ".join(errors))


def fetch_commodities():
    items = []
    errors = []
    for spec in COMMODITIES:
        try:
            value, change = fetch_commodity(spec)
        except Exception as e:
            errors.append(f"{spec['label']}: {e}")
            continue
        items.append({"id": spec["id"], "label": spec["label"],
                      "unit": spec["unit"], "value": value, "change": change})
    if not items:
        raise RuntimeError("; ".join(errors))
    return {"items": items}


# --- новости --------------------------------------------------------------

def _text(el):
    if el is None or el.text is None:
        return ""
    # Некоторые ленты экранируют HTML дважды: &amp;quot; и т.п.
    return html.unescape(el.text).strip()


def _parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_link(link):
    # Ссылка попадёт в <a href>; javascript: и прочее нам не нужно.
    return link if link.startswith(("https://", "http://")) else ""


def parse_feed(raw, source):
    root = ET.fromstring(raw)
    items = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry"):
            link = ""
            for l in entry.findall(f"{ATOM}link"):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            date = _text(entry.find(f"{ATOM}published")) or _text(entry.find(f"{ATOM}updated"))
            items.append((_text(entry.find(f"{ATOM}title")), link, date))
    else:
        for item in root.iter("item"):
            items.append((_text(item.find("title")), _text(item.find("link")),
                          _text(item.find("pubDate"))))

    result = []
    for title, link, date in items:
        link = _safe_link(link)
        if not title or not link:
            continue
        dt = _parse_date(date)
        result.append({
            "title": title, "link": link, "source": source,
            "published": dt.isoformat().replace("+00:00", "Z") if dt else None,
        })
    return result


def merge_news(per_feed):
    """Берём по несколько свежих из каждой ленты, чтобы одна болтливая
    лента не вытеснила остальные, и сортируем всё вместе по времени."""
    merged = []
    for items in per_feed:
        items = sorted(items, key=lambda n: n["published"] or "", reverse=True)
        merged.extend(items[:NEWS_PER_FEED])
    merged.sort(key=lambda n: n["published"] or "", reverse=True)
    return merged[:NEWS_TOTAL]


def fetch_news():
    per_feed = []
    errors = []
    for source, url in NEWS_FEEDS:
        try:
            per_feed.append(parse_feed(http_get(url), source))
        except Exception as e:
            errors.append(f"{source}: {e}")
    if not per_feed:
        raise RuntimeError("; ".join(errors))
    return {"items": merge_news(per_feed)}


# --- расписание -----------------------------------------------------------

def fetch_schedule():
    # Логин и пароль от личного кабинета лежат в секретах репозитория и
    # сюда приходят через переменные окружения. Сам разбор кабинета
    # пишется под конкретный вуз, пока его нет.
    if not os.environ.get("LK_LOGIN"):
        return {"items": [], "note": "Расписание пока не подключено"}
    raise NotImplementedError("разбор личного кабинета ещё не написан")


# --- сборка ---------------------------------------------------------------

SECTIONS = {
    "rates": fetch_rates,
    "commodities": fetch_commodities,
    "news": fetch_news,
    "schedule": fetch_schedule,
}


def load_previous(url):
    if not url:
        return {}
    try:
        return json.loads(http_get(url))
    except Exception as e:
        print(f"прошлый data.json недоступен: {e}", file=sys.stderr)
        return {}


def build(sections, previous, now):
    out = {"updated": now}
    for name, fetch in sections.items():
        try:
            section = fetch()
            section["updated"] = now
        except Exception as e:
            # Текст ошибки уходит в публичный лог и файл, поэтому только
            # сообщение исключения, без переменных окружения.
            print(f"{name}: {e}", file=sys.stderr)
            old = previous.get(name)
            if old and old.get("items"):
                section = dict(old, stale=True)
            else:
                section = {"items": [], "error": "Не удалось обновить"}
        out[name] = section
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--previous", help="URL уже выложенного data.json")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data = build(SECTIONS, load_previous(args.previous), now)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for name in SECTIONS:
        s = data[name]
        state = "устарело" if s.get("stale") else ("ошибка" if s.get("error") else "ок")
        print(f"{name}: {len(s.get('items', []))} шт., {state}")


if __name__ == "__main__":
    main()
