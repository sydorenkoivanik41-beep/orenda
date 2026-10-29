"""Спільні допоміжні функції: налаштування, мережа, робота з текстом."""
import configparser
import html
import json
import random
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


# ---------------------------------------------------------------- налаштування
class Settings:
    def __init__(self, path=ROOT / "settings.ini"):
        cp = configparser.ConfigParser(delimiters=("=",), inline_comment_prefixes=None,
                                       interpolation=None)
        cp.optionxform = str  # не перетворювати назви міст на малі літери
        cp.read(path, encoding="utf-8-sig")
        self.cities = []
        for name, value in cp.items("міста"):
            parts = [p.strip() for p in value.split("|")]
            olx_slug = parts[0].lower()
            lun_slug = parts[1] if len(parts) > 1 and parts[1] else name.strip().lower().replace(" ", "-")
            if olx_slug:
                self.cities.append({"name": name.strip(), "slug": olx_slug, "lun": lun_slug})
        s = cp["налаштування"] if cp.has_section("налаштування") else {}

        def num(key, default, kind=float):
            try:
                return kind(str(s.get(key, default)).replace(",", ".").strip())
            except ValueError:
                return default

        self.olx_pages = num("сторінок_olx", 10, int)
        self.lun_pages = num("сторінок_lun", 8, int)
        self.pause_min = max(1.0, num("пауза_від", 3))
        self.pause_max = max(self.pause_min, num("пауза_до", 7))
        self.max_per_author = num("макс_оголошень_автора", 3, int)
        self.keep_days = num("днів_зберігати", 30, int)
        self.compare_photos = str(s.get("порівнювати_фото", "так")).strip().lower() in ("так", "yes", "1", "true")
        self.usd_rate = num("курс_usd", 41.5)
        pub = cp["публікація"] if cp.has_section("публікація") else {}
        self.repo = str(pub.get("репозиторій", "")).strip()


def read_word_list(name):
    path = ROOT / name
    if not path.exists():
        return []
    words = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line)
    return words


# ---------------------------------------------------------------------- мережа
class Blocked(Exception):
    """Сайт відмовив у доступі (найчастіше — захист від ботів)."""


class Http:
    def __init__(self, settings, log):
        self.s = settings
        self.log = log
        self._last = 0.0

    def polite_pause(self):
        wait = random.uniform(self.s.pause_min, self.s.pause_max)
        elapsed = time.time() - self._last
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last = time.time()

    def get(self, url, accept="text/html,application/json", pause=True, headers=None, tries=3):
        if pause:
            self.polite_pause()
        hdrs = {
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.5",
        }
        if headers:
            hdrs.update(headers)
        last_err = None
        for attempt in range(tries):
            try:
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 429):
                    raise Blocked(f"HTTP {e.code}")
                if e.code == 404:
                    raise
                last_err = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = e
            time.sleep(5 * (attempt + 1))
        raise last_err

    def get_json(self, url, **kw):
        raw = self.get(url, accept="application/json", **kw)
        try:
            return json.loads(raw)
        except ValueError:
            # замість JSON прийшла сторінка — зазвичай це перевірка «чи ви не робот»
            raise Blocked("сайт повернув сторінку перевірки замість даних")


# ---------------------------------------------------------------------- текст
APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "‘": "'", "ʹ": "'", "ё": "е"})


def clean_html(text):
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def norm_text(text):
    return re.sub(r"\s+", " ", (text or "").lower().translate(APOSTROPHES)).strip()


PHONE_RE = re.compile(r"(?:\+?38[\s\-()]*)?\(?0\d{2}\)?[\s.\-]*\d{3}[\s.\-]*\d{2}[\s.\-]*\d{2}(?!\d)")


def find_phones(text):
    phones = set()
    for m in PHONE_RE.finditer(text or ""):
        digits = re.sub(r"\D", "", m.group(0))
        if digits.startswith("380"):
            digits = digits[2:]
        if len(digits) == 10 and digits.startswith("0"):
            phones.add(digits)
    return sorted(phones)


def parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def now_utc():
    return datetime.now(timezone.utc)


def first_int(text):
    m = re.search(r"\d+", str(text or ""))
    return int(m.group(0)) if m else None


def to_float(value):
    try:
        return float(str(value).replace(",", ".").split()[0])
    except (ValueError, IndexError):
        return None


# Ознаки з тексту — коли джерело не дало структуроване поле.
def guess_from_text(text, item):
    t = norm_text(text)
    if item.get("pets") is None:
        if re.search(r"без (домашніх )?(тварин|тваринок|улюблен|животн)|тварин(и)? не|животных не|no pets", t):
            item["pets"] = False
        elif re.search(r"можна з (тварин|домашн|улюблен)|з тваринами можна|можно с животн|с животными можно|тварини (дозволен|можна)", t):
            item["pets"] = True
    if item.get("kids") is None:
        if re.search(r"без діт|без детей|без діток", t):
            item["kids"] = False
        elif re.search(r"можна з дітьми|з дітьми можна|можно с детьми|сім'ї з дит|семье с дет|з дитиною|з дітьми", t):
            item["kids"] = True
    if item.get("furniture") is None:
        if re.search(r"без меблів|без мебели|не мебльован", t):
            item["furniture"] = False
        elif re.search(r"мебл|мебел|мебльован|меблюван", t):
            item["furniture"] = True
    if item.get("appliances") is None:
        if re.search(r"без техніки|без техники", t):
            item["appliances"] = False
        elif re.search(r"пральн|холодильн|стиральн|бойлер|техніка|техника|посудомийн|мікрохвил", t):
            item["appliances"] = True
