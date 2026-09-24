"""Разведка, круг 2: папка с расписанием на files.msal.ru и API кабинета.
Только публичные адреса, без логина. Временный файл, в main не попадает."""

import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"


def get(url, data=None, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "ru"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return r.status, r.geturl(), dict(r.headers), body
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers), e.read()
    except Exception as e:
        return None, url, {}, f"{type(e).__name__}: {e}".encode()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._a = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._a = [href, ""]
                self.links.append(self._a)

    def handle_endtag(self, tag):
        if tag == "a":
            self._a = None

    def handle_data(self, data):
        if self._a is not None:
            self._a[1] += data.strip()


def listing(url, depth, seen):
    if depth < 0 or url in seen:
        return
    seen.add(url)
    status, final, headers, body = get(url)
    text = body.decode("utf-8", "replace")
    print(f"\n### [{depth}] {urllib.parse.unquote(url)}\n    status={status} type={headers.get('Content-Type')} size={len(body)}")
    if status != 200 or "html" not in (headers.get("Content-Type") or ""):
        print("   ", text[:300].replace("\n", " "))
        return
    p = Links()
    p.feed(text)
    subs = []
    for href, label in p.links:
        full = urllib.parse.urljoin(final, href)
        if "files.msal.ru" not in full:
            continue
        name = urllib.parse.unquote(full)
        if "folder=" in full and "Default.aspx" in full:
            if "Расписание" in name:
                subs.append(full)
                print("    DIR ", label or name[-80:])
        elif label and not label.startswith(("На уровень", "Главная")):
            print("    FILE", label, "->", name[-120:])
    for s in subs[:25]:
        listing(s, depth - 1, seen)


print("=== config.js")
print(get("https://lk.msal.ru/config.js")[3].decode("utf-8", "replace"))

st, _, _, js = get("https://lk.msal.ru/assets/index-LTa2wxwL.js")
js = js.decode("utf-8", "replace")
print("\n=== bundle", st, len(js))
urls = sorted(set(re.findall(r"""https?://[A-Za-z0-9.\-]+(?::\d+)?[A-Za-z0-9_\-/.{}$]*""", js)))
print("urls:", [u for u in urls if "w3.org" not in u and "reactjs" not in u][:40])
paths = sorted(set(re.findall(r"""["'`](/[a-z][A-Za-z0-9_\-]*(?:/[A-Za-z0-9_\-${}:.]+){0,5}/?)["'`]""", js)))
print("paths:", paths[:150])
for m in re.finditer(r"schedule|login|auth/|token", js):
    pass
seen_ctx = set()
for word in ("schedule", "/auth", "login", "password", "captcha", "Bearer", "withCredentials", "baseURL"):
    n = 0
    for m in re.finditer(re.escape(word), js):
        ctx = js[max(0, m.start() - 90): m.end() + 90].replace("\n", " ")
        key = ctx[60:140]
        if key in seen_ctx:
            continue
        seen_ctx.add(key)
        print(f"  [{word}] …{ctx}…")
        n += 1
        if n >= 6:
            break

print("\n=== files.msal.ru")
listing("https://files.msal.ru/HTCOMNET/Default.aspx?folder=%D0%A3%D0%9C%D0%9C%2F%D0%A0%D0%B0%D1%81%D0%BF%D0%B8%D1%81%D0%B0%D0%BD%D0%B8%D0%B5", 2, set())
