"""Разведка: как устроены ЛК и расписание МГЮА. Только публичные страницы,
без логина. Временный файл, в main не попадает."""

import re
import ssl
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"
GROUP = "ИПР-2025-08Д"
KEYS = ("расписан", "raspis", "schedule", "timetable", "ruz", "rasp")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title, self._in_title = "", False
        self.links, self.forms, self.scripts, self.iframes = [], [], [], []
        self._form = None
        self._a = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "a" and a.get("href"):
            self._a = [a["href"], ""]
            self.links.append(self._a)
        elif tag == "form":
            self._form = {"action": a.get("action"), "method": a.get("method"), "inputs": []}
            self.forms.append(self._form)
        elif tag in ("input", "select", "button") and self._form is not None:
            self._form["inputs"].append((tag, a.get("type"), a.get("name"), a.get("id")))
        elif tag == "script" and a.get("src"):
            self.scripts.append(a["src"])
        elif tag == "iframe":
            self.iframes.append(a.get("src"))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "form":
            self._form = None
        elif tag == "a":
            self._a = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        if self._a is not None:
            self._a[1] += data.strip()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            body = r.read()
            cs = r.headers.get_content_charset() or "utf-8"
            return r.status, r.geturl(), dict(r.headers), body.decode(cs, "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, url, {}, f"{type(e).__name__}: {e}"


def report(url, depth_links=True):
    print(f"\n==================== {url}")
    status, final, headers, body = get(url)
    print("status:", status, "| final:", final)
    if status is None:
        print(body)
        return None, final
    print("server:", headers.get("Server"), "| cookies:",
          [c.split("=")[0] for c in headers.get("Set-Cookie", "").split(", ") if "=" in c][:8])
    p = Page()
    try:
        p.feed(body)
    except Exception as e:
        print("parse error", e)
    print("title:", p.title[:120], "| size:", len(body))
    low = body.lower()
    for word in ("captcha", "recaptcha", "smartcaptcha", "csrf", "_token", "esia", "gosuslugi",
                 "keycloak", "oauth", "saml", "sms", "2fa", "otp", "__next", "react", "vue", "angular"):
        if word in low:
            print("  mentions:", word)
    for f in p.forms:
        print("  FORM", f["method"], f["action"], f["inputs"])
    print("  scripts:", p.scripts[:12])
    if p.iframes:
        print("  iframes:", p.iframes)
    if GROUP.lower() in low or "ипр-2025" in low:
        print("  !!! группа упоминается на странице")
    hits = []
    for href, text in p.links:
        blob = (href + " " + text).lower()
        if any(k in blob for k in KEYS):
            hits.append((urllib.parse.urljoin(final, href), text[:60]))
    for h in dict(hits).items():
        print("  LINK", h)
    # API-подобные адреса прямо в тексте страницы/скриптов
    for m in sorted(set(re.findall(r"""["'](/api/[^"' ]{0,80}|https?://[^"' ]*api[^"' ]{0,60})["']""", body)))[:20]:
        print("  api?", m)
    return [u for u, _ in dict(hits).items()], final


if __name__ == "__main__":
    report("https://lk.msal.ru/")
    for guess in ("https://lk.msal.ru/login", "https://lk.msal.ru/api/", "https://lk.msal.ru/schedule"):
        report(guess)
    links, _ = report("https://msal.ru/")
    seen = set()
    for u in (links or [])[:8]:
        if u in seen or "msal" not in u:
            continue
        seen.add(u)
        sub, _ = report(u)
        for v in (sub or [])[:5]:
            if v not in seen and "msal" in v:
                seen.add(v)
                report(v)
    # JS-бандл ЛК: ищем в нём адреса API
    status, final, _, body = get("https://lk.msal.ru/")
    if status:
        p = Page(); p.feed(body)
        for s in p.scripts[:6]:
            u = urllib.parse.urljoin(final, s)
            st, _, _, js = get(u)
            found = sorted(set(re.findall(r"""["'`](/?(?:api|rest|v\d)/[A-Za-z0-9_\-/{}.$]{2,80})["'`]""", js)))
            print(f"\n---- js {u} status={st} size={len(js)} api-paths={len(found)}")
            for f in found[:60]:
                print("   ", f)
            for word in ("schedule", "raspis", "timetable", "lesson", "login", "auth", "token", "captcha"):
                n = js.lower().count(word)
                if n:
                    print(f"    '{word}' x{n}")
    sys.exit(0)
