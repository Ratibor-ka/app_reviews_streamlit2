"""
App Store Reviews Scraper — Streamlit UI
Версия 2.0.0
Запуск: streamlit run app.py
"""

import re
import time
import logging
import os
import io
import datetime
import warnings
warnings.filterwarnings("ignore")

import requests
import pandas as pd
import streamlit as st

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("reviews.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("appstore_v2")

ALLOWED_FIELDS = ["date", "userName", "title", "review", "rating", "isEdited"]
ITUNES_RSS = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "page={page}/id={app_id}/sortBy=mostRecent/json"
)
MAX_PAGES   = 10
PER_PAGE    = 50
MAX_REVIEWS = MAX_PAGES * PER_PAGE

COUNTRIES = {
    "🇺🇸 США (us)":           "us",
    "🇷🇺 Россия (ru)":         "ru",
    "🇩🇪 Германия (de)":       "de",
    "🇬🇧 Великобритания (gb)": "gb",
    "🇫🇷 Франция (fr)":        "fr",
    "🇯🇵 Япония (ja)":         "ja",
    "🇨🇳 Китай (cn)":          "cn",
    "🇮🇳 Индия (in)":          "in",
    "🇧🇷 Бразилия (br)":       "br",
    "🇰🇷 Корея (kr)":          "kr",
    "🇦🇺 Австралия (au)":      "au",
    "🇨🇦 Канада (ca)":         "ca",
    "🇪🇸 Испания (es)":        "es",
    "🇮🇹 Италия (it)":         "it",
    "🇳🇱 Нидерланды (nl)":     "nl",
    "🇵🇱 Польша (pl)":         "pl",
    "🇹🇷 Турция (tr)":         "tr",
    "🇦🇪 ОАЭ (ae)":            "ae",
}


class ScraperError(Exception):
    pass


def parse_app_id(value: str) -> int:
    value = value.strip()
    if value.startswith("http"):
        m = re.search(r"/id(\d+)", value)
        if m:
            return int(m.group(1))
        raise ScraperError(f"Не найден `/id<число>` в URL: {value}")
    if value.isdigit():
        return int(value)
    raise ScraperError(f'Неверный формат: "{value}". Нужно число или ссылка App Store.')


def _parse_entry(entry: dict) -> dict:
    raw_date = entry.get("updated", {}).get("label", "")
    try:
        dt = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        date_str = raw_date
    return {
        "date":     date_str,
        "userName": entry.get("author", {}).get("name", {}).get("label", ""),
        "title":    entry.get("title", {}).get("label", ""),
        "review":   entry.get("content", {}).get("label", ""),
        "rating":   int(entry.get("im:rating", {}).get("label", 0)),
        "isEdited": False,
    }


def fetch_reviews(app_id: int, country: str, count: int, progress_cb=None) -> list:
    count = min(count, MAX_REVIEWS)
    all_reviews = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }
    pages_needed = min(MAX_PAGES, -(-count // PER_PAGE))

    for page in range(1, pages_needed + 1):
        url = ITUNES_RSS.format(country=country, page=page, app_id=app_id)
        log.info(f"Страница {page}/{pages_needed}: {url}")
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
        except requests.exceptions.HTTPError:
            if resp.status_code == 400:
                log.warning(f"Страница {page} -> 400, отзывов больше нет.")
                break
            raise ScraperError(f"HTTP {resp.status_code}: {resp.url}")
        except requests.exceptions.ConnectionError as e:
            raise ScraperError(f"Ошибка соединения: {e}")
        except requests.exceptions.Timeout:
            raise ScraperError("Превышено время ожидания (timeout 30 сек).")

        try:
            data = resp.json()
        except ValueError:
            log.warning(f"Страница {page}: не удалось разобрать JSON.")
            break

        entries = data.get("feed", {}).get("entry", [])
        if not entries:
            log.info(f"Страница {page}: нет записей.")
            break
        if page == 1:
            entries = entries[1:]
        if not entries:
            break

        for entry in entries:
            try:
                all_reviews.append(_parse_entry(entry))
            except Exception:
                continue

        collected = len(all_reviews)
        log.info(f"Собрано: {collected}")
        if progress_cb:
            progress_cb(collected, count)
        if collected >= count:
            break
        time.sleep(0.4)

    if not all_reviews:
        log.warning("Отзывов не найдено.")
    return all_reviews[:count]


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_csv(buf, index=False, encoding="utf-8-sig")
    return buf.getvalue()


def to_xml_bytes(df: pd.DataFrame) -> bytes:
    def esc(s):
        return (str(s)
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<reviews>"]
    for _, row in df.iterrows():
        lines.append("  <review>")
        for col in df.columns:
            lines.append(f"    <{col}>{esc(row[col])}</{col}>")
        lines.append("  </review>")
    lines.append("</reviews>")
    return "\n".join(lines).encode("utf-8")


# ─── Streamlit UI ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="App Store Reviews Scraper",
    page_icon="🍎",
    layout="centered",
)

st.markdown("""
<style>
.block-container{max-width:760px;}
.badge{display:inline-block;background:#fff3cd;color:#856404;
border:1px solid #ffc107;border-radius:6px;padding:4px 12px;
font-size:13px;margin-bottom:8px;}
div[data-testid="stMetricValue"]{font-size:26px;font-weight:700;}
</style>
""", unsafe_allow_html=True)

st.title("🍎 App Store Reviews Scraper")
st.markdown(
    "Сбор отзывов через **iTunes RSS API** — без сторонних зависимостей.  \n"
    '<span class="badge">⚠️ Лимит Apple: до 500 отзывов на страну</span>',
    unsafe_allow_html=True,
)
st.divider()

# ── Форма ────────────────────────────────────────────────────────────────────
with st.form("scraper_form"):
    st.subheader("⚙️ Параметры сбора")

    app_input = st.text_input(
        "App ID или ссылка на приложение *",
        placeholder="618783545  или  https://apps.apple.com/us/app/slack/id618783545",
        help="Числовой ID из URL App Store или полная ссылка",
    )

    col1, col2 = st.columns(2)
    with col1:
        count_input = st.slider(
            "Количество отзывов",
            min_value=1, max_value=500, value=100, step=10,
        )
    with col2:
        country_label = st.selectbox(
            "Страна App Store",
            options=list(COUNTRIES.keys()),
            index=0,
        )

    fields_input = st.multiselect(
        "Поля для сохранения",
        options=ALLOWED_FIELDS,
        default=ALLOWED_FIELDS,
    )

    st.markdown("**Формат и имя файла**")
    fcol1, fcol2 = st.columns([1, 2])
    with fcol1:
        file_format = st.radio(
            "Формат",
            options=["CSV", "XML"],
            index=0,
            horizontal=True,
            label_visibility="collapsed",
        )
    with fcol2:
        file_name = st.text_input(
            "Имя файла",
            value="reviews.csv",
            label_visibility="collapsed",
        )

    submitted = st.form_submit_button(
        "▶ Собрать отзывы", type="primary", use_container_width=True
    )

# ── Обработка ────────────────────────────────────────────────────────────────
if submitted:
    if not app_input.strip():
        st.error("❌ Поле «App ID или ссылка» не может быть пустым.")
        st.stop()
    if not fields_input:
        st.error("❌ Выберите хотя бы одно поле.")
        st.stop()

    try:
        app_id = parse_app_id(app_input.strip())
    except ScraperError as e:
        st.error(f"❌ {e}")
        st.stop()

    country_code = COUNTRIES[country_label]
    st.info(
        f"**App ID:** `{app_id}` | **Страна:** `{country_code.upper()}` | "
        f"**Запрошено:** `{count_input}` | **Формат:** `{file_format}`"
    )

    progress_bar = st.progress(0, text="Подключение к iTunes API...")
    status_slot  = st.empty()

    def on_progress(done, total):
        pct = min(int(done / total * 100), 100) if total > 0 else 0
        progress_bar.progress(pct, text=f"Собрано: {done} / {total}")

    try:
        with st.spinner("Идёт сбор отзывов..."):
            reviews = fetch_reviews(
                app_id=app_id,
                country=country_code,
                count=count_input,
                progress_cb=on_progress,
            )
    except ScraperError as e:
        progress_bar.empty()
        st.error(f"❌ {e}")
        st.stop()
    except Exception as e:
        progress_bar.empty()
        st.exception(e)
        st.stop()

    progress_bar.progress(100, text="Готово!")
    status_slot.empty()

    if not reviews:
        st.warning(
            "⚠️ Отзывы не найдены.\n\n"
            "- Проверьте App ID\n"
            "- Попробуйте другую страну\n"
            "- Приложение может быть недоступно в этом регионе"
        )
        st.stop()

    df_all = pd.DataFrame(reviews)
    exist_fields = [f for f in fields_input if f in df_all.columns]
    df = df_all[exist_fields]

    st.success(f"✅ Собрано: **{len(df)}** отзывов | Страна: **{country_code.upper()}**")

    m1, m2, m3 = st.columns(3)
    m1.metric("Отзывов", len(df))
    if "rating" in df.columns:
        avg = round(df["rating"].mean(), 2)
        m2.metric("Средний рейтинг", f"{avg} ⭐")
        m3.metric("5 звёзд", int((df["rating"] == 5).sum()))

    st.divider()
    st.subheader("📋 Предпросмотр")
    st.dataframe(df.head(10), use_container_width=True)

    if "rating" in df.columns:
        st.subheader("📊 Распределение рейтингов")
        st.bar_chart(df["rating"].value_counts().sort_index())

    st.divider()
    st.subheader("💾 Скачать файл")

    ext = ".csv" if file_format == "CSV" else ".xml"
    base = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    out_name = base + ext

    if file_format == "CSV":
        file_bytes = to_csv_bytes(df)
        mime = "text/csv"
    else:
        file_bytes = to_xml_bytes(df)
        mime = "application/xml"

    size_kb = max(1, len(file_bytes) // 1024)
    st.download_button(
        label=f"⬇️ Скачать {out_name}  ({size_kb} KB)",
        data=file_bytes,
        file_name=out_name,
        mime=mime,
        type="primary",
        use_container_width=True,
    )

    with st.expander("🪵 Лог выполнения"):
        try:
            with open("reviews.log", encoding="utf-8") as f:
                lines = f.readlines()
            st.code("".join(lines[-40:]), language="text")
        except FileNotFoundError:
            st.caption("Файл лога пока не создан.")


# ── Боковая панель ────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("📖 Справка")
    st.markdown("""
**Как найти App ID?**

Откройте страницу приложения в App Store — число после `/id` в URL и есть App ID:

```
.../app/slack/id618783545
              ─────────
              618783545
```

---

**Популярные приложения**

| Приложение | App ID |
|---|---|
| Slack | 618783545 |
| WhatsApp | 310633997 |
| Telegram | 686449807 |
| Instagram | 389801252 |
| YouTube | 544007664 |
| TikTok | 1235601864 |
| Spotify | 324684580 |
| Duolingo | 570060128 |

---

**Форматы файлов**

| Формат | Кодировка |
|---|---|
| CSV | UTF-8 BOM |
| XML | UTF-8 |

---

**Лимиты**

iTunes RSS API — максимум **500 отзывов** на страну.  
Для большего объёма запустите несколько стран.
""")
    st.divider()
    st.caption("v2.0.0 · iTunes RSS API · Python 3.12+")
