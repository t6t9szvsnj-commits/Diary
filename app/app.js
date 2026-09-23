"use strict";

// ---------- мелочи ----------

const $ = (sel) => document.querySelector(sel);

// Всё, что пришло от пользователя или из новостей, вставляется только
// через textContent — никакого innerHTML, чтобы чужой заголовок не стал кодом.
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

// toISOString() дал бы дату по UTC, и после полуночи по Москве запись
// попадала бы во вчерашний день.
function isoDay(d = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}
function parseDay(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
function daysBetween(fromIso, toIso) {
  return Math.round((parseDay(toIso) - parseDay(fromIso)) / 86400000);
}
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}
function uid() {
  return crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2);
}
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
function fmtDate(iso, opts) {
  return parseDay(iso).toLocaleDateString("ru-RU", opts);
}
function ago(isoTime) {
  if (!isoTime) return "";
  const min = Math.round((Date.now() - new Date(isoTime)) / 60000);
  if (min < 1) return "только что";
  if (min < 60) return `${min} мин назад`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} ч назад`;
  const d = Math.round(h / 24);
  return `${d} ${plural(d, "день", "дня", "дней")} назад`;
}
function lsGet(key, fallback) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
  catch { return fallback; }
}
function lsSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* приватный режим */ }
}

// ---------- хранилище (IndexedDB) ----------

const db = {
  _p: null,
  open() {
    if (!this._p) {
      this._p = new Promise((resolve, reject) => {
        const req = indexedDB.open("diary", 1);
        req.onupgradeneeded = () => {
          const d = req.result;
          d.createObjectStore("entries", { keyPath: "id" });
          d.createObjectStore("deadlines", { keyPath: "id" });
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }
    return this._p;
  },
  async _tx(store, mode, fn) {
    const d = await this.open();
    return new Promise((resolve, reject) => {
      const tx = d.transaction(store, mode);
      const result = fn(tx.objectStore(store));
      tx.oncomplete = () => resolve(result && "result" in result ? result.result : undefined);
      tx.onerror = () => reject(tx.error);
    });
  },
  all(store) { return this._tx(store, "readonly", (s) => s.getAll()); },
  put(store, obj) { return this._tx(store, "readwrite", (s) => s.put(obj)); },
  del(store, id) { return this._tx(store, "readwrite", (s) => s.delete(id)); },
};

// ---------- навигация ----------

function go(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.go === view));
  window.scrollTo(0, 0);
  if (view === "diary") renderEntries();
  if (view === "deadlines") renderDeadlines();
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-go]");
  if (b) go(b.dataset.go);
});

// ---------- дневник ----------

let editing = null;

function openEditor(entry) {
  editing = entry || null;
  $("#editor-date").value = entry ? entry.date : isoDay();
  $("#editor-text").value = entry ? entry.text : "";
  $("#editor-delete").hidden = !entry;
  $("#editor").showModal();
  $("#editor-text").focus();
}

$("#new-entry-btn").addEventListener("click", () => openEditor(null));

$("#editor").addEventListener("close", async () => {
  if ($("#editor").returnValue !== "save") return;
  const text = $("#editor-text").value.trim();
  const date = $("#editor-date").value || isoDay();
  if (!text) {
    if (editing && confirm("Запись пустая. Удалить её?")) await db.del("entries", editing.id);
  } else {
    const now = new Date().toISOString();
    await db.put("entries", editing
      ? { ...editing, text, date, updated: now }
      : { id: uid(), text, date, created: now, updated: now });
  }
  renderEntries();
});

$("#editor-delete").addEventListener("click", async () => {
  if (!editing || !confirm("Удалить эту запись насовсем?")) return;
  await db.del("entries", editing.id);
  $("#editor").close("deleted");
  renderEntries();
});

function highlight(text, q) {
  if (!q) return [text];
  const out = [];
  const lower = text.toLowerCase();
  let i = 0;
  for (let j = lower.indexOf(q); j !== -1; j = lower.indexOf(q, i)) {
    out.push(text.slice(i, j), el("mark", {}, text.slice(j, j + q.length)));
    i = j + q.length;
  }
  out.push(text.slice(i));
  return out;
}

async function renderEntries() {
  const q = $("#search").value.trim().toLowerCase();
  let entries = await db.all("entries");
  if (q) entries = entries.filter((e) => e.text.toLowerCase().includes(q));
  entries.sort((a, b) => (b.date + b.created).localeCompare(a.date + a.created));

  const box = $("#entries");
  box.replaceChildren();
  if (!entries.length) {
    box.append(el("p", { class: "empty" }, q ? "Ничего не нашлось." : "Пока ни одной записи. Нажмите ＋, чтобы начать."));
    return;
  }
  let group = null;
  for (const e of entries) {
    if (!group || group.dataset.date !== e.date) {
      group = el("div", { class: "day-group", "data-date": e.date },
        el("h3", {}, cap(fmtDate(e.date, { weekday: "long", day: "numeric", month: "long",
          year: e.date.slice(0, 4) === isoDay().slice(0, 4) ? undefined : "numeric" }))));
      box.append(group);
    }
    const time = new Date(e.created).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    group.append(el("div", { class: `entry ${q ? "" : "clamp"}`, onclick: () => openEditor(e) },
      el("div", { class: "time" }, time),
      el("div", { class: "body" }, highlight(e.text, q))));
  }
}
$("#search").addEventListener("input", renderEntries);

// ---------- дедлайны ----------

function dueLabel(due) {
  const n = daysBetween(isoDay(), due);
  if (n < 0) return { text: `просрочено на ${-n} ${plural(-n, "день", "дня", "дней")}`, cls: "due-over" };
  if (n === 0) return { text: "сегодня", cls: "due-over" };
  if (n === 1) return { text: "завтра", cls: "due-soon" };
  if (n <= 3) return { text: `через ${n} ${plural(n, "день", "дня", "дней")}`, cls: "due-soon" };
  return { text: `${fmtDate(due, { day: "numeric", month: "short" })}, через ${n} ${plural(n, "день", "дня", "дней")}`, cls: "" };
}

function deadlineRow(d, withControls) {
  const label = dueLabel(d.due);
  const toggle = async () => { await db.put("deadlines", { ...d, done: !d.done }); renderDeadlines(); renderHomeDeadlines(); };
  return el("li", {},
    withControls && el("button", { class: `check ${d.done ? "on" : ""}`, "aria-label": "Готово", onclick: toggle }),
    el("span", { class: "grow" }, d.title),
    !d.done && el("span", { class: `meta ${label.cls}` }, label.text),
    withControls && el("button", {
      class: "del", "aria-label": "Удалить",
      onclick: async () => {
        if (!confirm(`Удалить «${d.title}»?`)) return;
        await db.del("deadlines", d.id); renderDeadlines(); renderHomeDeadlines();
      },
    }, "×"));
}

async function renderDeadlines() {
  const all = (await db.all("deadlines")).sort((a, b) => a.due.localeCompare(b.due));
  const open = all.filter((d) => !d.done), done = all.filter((d) => d.done).reverse();
  $("#deadlines").replaceChildren(...(open.length ? open.map((d) => deadlineRow(d, true))
    : [el("li", { class: "empty" }, "Дедлайнов нет. Красота.")]));
  $("#deadlines-done").replaceChildren(...done.map((d) => deadlineRow(d, true)));
}

async function renderHomeDeadlines() {
  const open = (await db.all("deadlines")).filter((d) => !d.done).sort((a, b) => a.due.localeCompare(b.due));
  $("#home-deadlines").replaceChildren(...(open.length ? open.slice(0, 5).map((d) => deadlineRow(d, false))
    : [el("li", { class: "empty" }, "Ничего не горит")]));
}

$("#deadline-due").value = isoDay(new Date(Date.now() + 7 * 86400000));
$("#deadline-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = $("#deadline-title").value.trim();
  if (!title) return;
  // Очищаем поле до записи в базу, а не после: иначе то, что успели
  // набрать, пока шла запись, стиралось бы вместе с прошлым дедлайном.
  $("#deadline-title").value = "";
  await db.put("deadlines", { id: uid(), title, due: $("#deadline-due").value, done: false, created: new Date().toISOString() });
  renderDeadlines(); renderHomeDeadlines();
});

// ---------- погода (Open-Meteo, прямо с телефона: у них открыт CORS) ----------

const DEFAULT_CITY = { name: "Москва", lat: 55.7558, lon: 37.6173 };
const WMO = [
  [[0], "☀️", "ясно"], [[1], "🌤", "малооблачно"], [[2], "⛅️", "облачно"], [[3], "☁️", "пасмурно"],
  [[45, 48], "🌫", "туман"], [[51, 53, 55, 56, 57], "🌦", "морось"],
  [[61, 63, 65, 66, 67, 80, 81, 82], "🌧", "дождь"], [[71, 73, 75, 77, 85, 86], "🌨", "снег"],
  [[95, 96, 99], "⛈", "гроза"],
];
function wmo(code) {
  return WMO.find(([codes]) => codes.includes(code)) || [null, "🌡", ""];
}

function city() { return lsGet("city", DEFAULT_CITY); }

async function loadWeather(force) {
  const c = city();
  $("#city-btn").textContent = c.name;
  const cached = lsGet("weather", null);
  const fresh = cached && cached.key === `${c.lat},${c.lon}` && Date.now() - cached.at < 30 * 60000;
  if (cached && cached.key === `${c.lat},${c.lon}`) renderWeather(cached.data);
  if (fresh && !force) return;
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${c.lat}&longitude=${c.lon}` +
      "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&forecast_days=4&timezone=auto";
    const r = await fetch(url);
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    lsSet("weather", { key: `${c.lat},${c.lon}`, at: Date.now(), data });
    renderWeather(data);
  } catch {
    if (!cached) $("#weather").replaceChildren(el("p", { class: "empty" }, "Нет связи с сервисом погоды"));
  }
}

function renderWeather(data) {
  const d = data.daily;
  const today = isoDay();
  $("#weather").replaceChildren(...d.time.map((day, i) => {
    const [, icon, desc] = wmo(d.weather_code[i]);
    const n = daysBetween(today, day);
    const name = n === 0 ? "Сегодня" : n === 1 ? "Завтра" : fmtDate(day, { weekday: "short" });
    const rain = d.precipitation_probability_max?.[i];
    return el("div", { title: desc },
      el("div", { class: "day" }, name),
      el("div", { class: "ico", "aria-label": desc }, icon),
      el("div", { class: "t" }, `${Math.round(d.temperature_2m_max[i])}° `, el("span", {}, `${Math.round(d.temperature_2m_min[i])}°`)),
      el("div", { class: "p" }, rain >= 20 ? `💧${rain}%` : ""));
  }));
}

$("#city-btn").addEventListener("click", () => { go("settings"); $("#city-input").focus(); });
$("#city-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#city-input").value.trim();
  $("#city-status").textContent = "Ищу…";
  try {
    const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?count=1&language=ru&name=${encodeURIComponent(name)}`);
    const found = (await r.json()).results?.[0];
    if (!found) { $("#city-status").textContent = "Не нашёл такой город."; return; }
    lsSet("city", { name: found.name, lat: found.latitude, lon: found.longitude });
    $("#city-status").textContent = `Готово: ${found.name}${found.admin1 ? ", " + found.admin1 : ""}`;
    loadWeather(true);
  } catch {
    $("#city-status").textContent = "Нет связи, попробуйте позже.";
  }
});

// ---------- данные из GitHub Actions (data.json) ----------

function stamp(node, section) {
  node.classList.toggle("stale", !!section?.stale);
  if (!section?.updated) { node.textContent = ""; return; }
  node.textContent = section.stale ? `не обновлялось ${ago(section.updated)}` : ago(section.updated);
}

function fmtNum(v, digits) {
  return v.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function marketTile(item, digits) {
  const ch = item.change;
  return el("div", {},
    el("div", { class: "name" }, item.label),
    el("div", { class: "val" }, `${fmtNum(item.value, digits)} ${item.unit}`),
    ch != null && el("div", { class: `chg ${ch > 0 ? "up" : ch < 0 ? "down" : "muted"}` },
      `${ch > 0 ? "▲" : ch < 0 ? "▼" : "•"} ${fmtNum(Math.abs(ch), digits)}`));
}

function renderData(data) {
  const rates = data.rates?.items || [], comm = data.commodities?.items || [];
  const tiles = [...rates.map((i) => marketTile(i, 2)), ...comm.map((i) => marketTile(i, 2))];
  $("#markets").replaceChildren(...(tiles.length ? tiles : [el("p", { class: "empty" }, "Нет данных")]));
  stamp($("#markets-stamp"), data.rates || data.commodities);

  const news = data.news?.items || [];
  $("#news").replaceChildren(...(news.length ? news.map((n) => el("li", {},
    el("a", { class: "grow", href: n.link, target: "_blank", rel: "noopener noreferrer" },
      n.title,
      el("span", { class: "meta" }, [n.source, n.published && ago(n.published)].filter(Boolean).join(" · ")))))
    : [el("li", { class: "empty" }, "Нет данных")]));
  stamp($("#news-stamp"), data.news);

  const sch = data.schedule || {};
  const lessons = sch.items || [];
  $("#schedule").replaceChildren(...(lessons.length ? lessons.map((l) => el("li", {},
    el("span", { class: "meta" }, l.time || ""),
    el("span", { class: "grow" }, l.title || "", l.room ? el("span", { class: "meta" }, ` · ${l.room}`) : null)))
    : [el("li", { class: "empty" }, sch.note || sch.error || "Пар нет")]));
  stamp($("#schedule-stamp"), lessons.length ? sch : null);
}

async function loadData() {
  const cached = lsGet("data", null);
  if (cached) renderData(cached);
  try {
    const r = await fetch("data.json", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    lsSet("data", data);
    renderData(data);
  } catch {
    if (!cached) renderData({});
  }
}

// ---------- резервная копия ----------

$("#export-btn").addEventListener("click", async () => {
  const payload = {
    app: "diary", version: 1, exported: new Date().toISOString(),
    entries: await db.all("entries"), deadlines: await db.all("deadlines"),
  };
  const name = `дневник-${isoDay()}.json`;
  const file = new File([JSON.stringify(payload, null, 1)], name, { type: "application/json" });
  // На айфоне лист «Поделиться» даёт «Сохранить в Файлы» — это удобнее,
  // чем скачивание, которое в режиме приложения ведёт себя странно.
  if (navigator.canShare?.({ files: [file] })) {
    try { await navigator.share({ files: [file], title: name }); } catch { /* отменили */ }
  } else {
    const a = el("a", { href: URL.createObjectURL(file), download: name });
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  lsSet("lastBackup", Date.now());
  $("#backup-status").textContent = `Копия: ${payload.entries.length} записей, ${payload.deadlines.length} дедлайнов.`;
});

$("#import-input").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    if (data.app !== "diary") throw new Error("не тот файл");
    const entries = data.entries || [], deadlines = data.deadlines || [];
    // Восстановление только добавляет и обновляет — ничего не стирает.
    if (!confirm(`Восстановить ${entries.length} записей и ${deadlines.length} дедлайнов? Существующие не удалятся.`)) return;
    for (const x of entries) await db.put("entries", x);
    for (const x of deadlines) await db.put("deadlines", x);
    $("#backup-status").textContent = "Восстановлено.";
    renderEntries(); renderDeadlines(); renderHomeDeadlines();
  } catch (err) {
    $("#backup-status").textContent = `Не получилось прочитать файл: ${err.message}`;
  }
});

// ---------- запуск ----------

function renderHeader() {
  const now = new Date();
  $("#today-weekday").textContent = cap(now.toLocaleDateString("ru-RU", { weekday: "long" }));
  $("#today-date").textContent = now.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

function refreshAll(force) {
  renderHeader();
  renderHomeDeadlines();
  loadWeather(force);
  loadData();
  lsSet("lastRefresh", Date.now());
}

$("#refresh-btn").addEventListener("click", () => refreshAll(true));

// Айфон не перезапускает приложение с главного экрана, а будит его —
// поэтому «при заходе» значит «при возврате на экран».
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - lsGet("lastRefresh", 0) > 5 * 60000) refreshAll(false);
});

(async () => {
  refreshAll(false);
  if (navigator.storage?.persist) {
    const ok = await navigator.storage.persist().catch(() => false);
    $("#storage-status").textContent = ok
      ? "Браузер обещал не стирать данные."
      : "Добавьте приложение на экран «Домой», чтобы Safari не стёр записи.";
  }
  const last = lsGet("lastBackup", 0);
  if (last) $("#backup-status").textContent = `Последняя копия: ${ago(new Date(last).toISOString())}.`;
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
})();
