"""Збір оголошень з LUN (сторінки оренди ЛУН розміщені на flatfy.ua).

Беремо звичайні сторінки списку (?page=N — це дозволено файлом robots.txt сайту)
і читаємо дані, вбудовані в сторінку (window.INITIAL_STATE).
"""
import json
import re
import urllib.parse

from common import Blocked, find_phones, guess_from_text, iso, parse_time
from olx import olx_code

BASE = "https://flatfy.ua/uk/"
IMG = "https://market-images.lunstatic.net/lun-ua/{w}/{h}/images/{id}.jpg"


def parse_state(html_text):
    marker = "window.INITIAL_STATE = "
    i = html_text.find(marker)
    if i < 0:
        return None
    body = html_text[i + len(marker):]
    end = body.find(";\n")
    if end < 0:
        end = body.find("</script>")
    body = body[:end].strip().rstrip(";")
    # це об'єкт JavaScript, а не чистий JSON: замінюємо undefined на null
    body = re.sub(r"([:\[,])undefined(?=[,\]\}])", r"\1null", body)
    return json.loads(body)


def collect(http, settings, city, log):
    path = "оренда-квартир-" + city["lun"]
    url0 = BASE + urllib.parse.quote(path)
    items, rate = [], None
    total_seen = 0
    for page in range(1, settings.lun_pages + 1):
        url = url0 if page == 1 else f"{url0}?page={page}"
        try:
            raw = http.get(url).decode("utf-8", "replace")
        except Exception as e:
            if getattr(e, "code", None) == 404:
                if page == 1:
                    raise ValueError(f"LUN не знайшов сторінку «{path}». Перевірте назву міста.")
                break
            raise
        try:
            state = parse_state(raw)
        except ValueError:
            state = None
        if not state:
            raise Blocked("LUN повернув сторінку без даних")
        if rate is None:
            try:
                rate = float(state["currencies"]["coefficients"]["UAH"]["USD"])
            except (KeyError, TypeError, ValueError):
                rate = settings.usd_rate
        realties = ((state.get("search") or {}).get("realties") or {})
        lst = realties.get("list") or []
        if not lst:
            break
        total_seen += len(lst)
        for r in lst:
            if r.get("section_id") not in (None, 2):
                continue
            if not r.get("is_owner"):  # LUN позначає власників окремо
                continue
            item = normalize(r, city, rate, settings)
            if item:
                items.append(item)
        if total_seen >= (realties.get("totalCount") or 0):
            break
    log(f"  LUN {city['name']}: переглянуто {total_seen}, від власників {len(items)}")
    return items


def _img(image_id, w, h):
    return IMG.format(w=w, h=h, id=image_id)


def normalize(r, city, rate, settings):
    price = r.get("price")
    if not price:
        return None
    cur = (r.get("currency") or "UAH").upper()
    if cur == "USD":
        price = price * (rate or settings.usd_rate)
    elif cur == "EUR":
        price = price * (rate or settings.usd_rate) * 1.1
    district = None
    for g in r.get("geo_entities") or []:
        if g.get("type") == "district":
            district = g.get("name")
            break
    pets_full = r.get("pets_allowed_full")
    pets = False if pets_full == "no" else (True if pets_full in ("yes", "some", "all") else None)
    kids = r.get("children_allowed") if isinstance(r.get("children_allowed"), bool) else None
    images = [i.get("image_id") for i in (r.get("images") or []) if i.get("image_id")][:12]
    text = (r.get("text") or "").strip()
    original = r.get("url_raw")
    site = ((r.get("site") or {}).get("name") or "").lower()
    created = parse_time(r.get("insert_time"))
    agency = r.get("agency")
    agency_id = agency.get("id") if isinstance(agency, dict) else agency
    item = {
        "id": f"lun:{r['id']}",
        "source": "LUN",
        "url": f"https://flatfy.ua/uk/realty/{r['id']}",
        "original_url": original,
        "original_site": site,
        "olx_code": olx_code(original) if "olx" in site else None,
        "city": city["slug"],
        "district": district,
        "title": (r.get("header") or "").strip(),
        "text": text[:2500],
        "price": round(float(price)),
        "rooms": r.get("room_count"),
        "area": r.get("area_total"),
        "floor": r.get("floor"),
        "floors": r.get("floor_count"),
        "pets": pets,
        "kids": kids,
        "furniture": None,
        "appliances": None,
        "no_commission": False,
        "photos": [_img(i, 1024, 768) for i in images],
        "thumbs": [_img(i, 360, 360) for i in images],
        "created": iso(created),
        "updated": iso(created),
        "author": f"lun-agency:{agency_id}" if agency_id else None,
        "phones": find_phones(text),
        "owner_flag": True,
        "lun_group": r.get("group_id"),
    }
    guess_from_text(item["title"] + "\n" + text, item)
    return item
