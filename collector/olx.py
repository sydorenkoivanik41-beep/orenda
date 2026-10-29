"""Збір оголошень з OLX.ua через ту саму службу даних, яку використовує сам сайт OLX."""
import re
import urllib.parse

from common import Blocked, clean_html, find_phones, first_int, guess_from_text, iso, parse_time, to_float

API = "https://www.olx.ua/api/v1"
CATEGORY_PATH = "nedvizhimost,kvartiry,dolgosrochnaya-arenda-kvartir"
CATEGORY_ID = 1760  # «Довгострокова оренда квартир»

# Запасні номери міст, якщо OLX не відповість на запит про місто.
KNOWN = {
    "kiev": (25, 268), "cherkassy": (12, 145), "odessa": (9, 62),
    "lvov": (5, 176), "ivano-frankovsk": (13, 132),
}

OLX_CODE_RE = re.compile(r"-ID([0-9A-Za-z]+)\.html")


def olx_code(url):
    m = OLX_CODE_RE.search(url or "")
    return m.group(1) if m else None


def resolve_city(http, slug):
    try:
        j = http.get_json(f"{API}/friendly-links/query-params/{CATEGORY_PATH},{urllib.parse.quote(slug)}")
        d = j.get("data") or {}
        if d.get("city_id"):
            return int(d["region_id"]), int(d["city_id"])
    except Blocked:
        raise
    except Exception:
        pass
    if slug in KNOWN:
        return KNOWN[slug]
    raise ValueError(f"OLX не знає місто «{slug}». Перевірте рядок у settings.ini.")


def collect(http, settings, city, log):
    region_id, city_id = resolve_city(http, city["slug"])
    params = {
        "offset": 0, "limit": 50, "category_id": CATEGORY_ID,
        "region_id": region_id, "city_id": city_id,
        "sort_by": "created_at:desc", "owner_type": "private",
    }
    url = f"{API}/offers/?" + urllib.parse.urlencode(params)
    items, seen = [], set()
    for page in range(settings.olx_pages):
        j = http.get_json(url)
        data = j.get("data") or []
        for offer in data:
            if offer.get("id") in seen:
                continue
            seen.add(offer.get("id"))
            if (offer.get("category") or {}).get("id") != CATEGORY_ID:
                continue
            if ((offer.get("location") or {}).get("city") or {}).get("id") != city_id:
                continue
            if offer.get("business"):  # «Бізнес», а не «Приватна особа»
                continue
            item = normalize(offer, city, settings)
            if item:
                items.append(item)
        nxt = ((j.get("links") or {}).get("next") or {}).get("href")
        if not nxt or not data:
            break
        url = nxt
    log(f"  OLX {city['name']}: {len(items)} оголошень від приватних осіб")
    return items


def _param(offer, key):
    for p in offer.get("params") or []:
        if p.get("key") == key:
            return p.get("value") or {}
    return None


def normalize(offer, city, settings):
    price = _param(offer, "price") or {}
    value = price.get("value")
    cur = price.get("currency") or "UAH"
    if value is None:
        return None
    if cur != "UAH":
        value = price.get("converted_value") or (value * settings.usd_rate if cur == "USD" else None)
        if value is None:
            return None
    rooms = first_int((_param(offer, "number_of_rooms_string") or {}).get("label"))
    area = to_float((_param(offer, "total_area") or {}).get("key"))
    floor = first_int((_param(offer, "floor") or {}).get("key"))
    floors = first_int((_param(offer, "total_floors") or {}).get("key"))

    pets = None
    pk = (_param(offer, "pets") or {}).get("key")
    if isinstance(pk, list) and pk:
        pets = any(str(k).startswith("yes") for k in pk)
    kids = None
    ak = (_param(offer, "additional") or {}).get("key")
    if isinstance(ak, list) and "with_children" in ak:
        kids = True
    furniture = None
    fk = (_param(offer, "furnish") or {}).get("key")
    if fk in ("yes", "no"):
        furniture = fk == "yes"
    appliances = None
    apk = (_param(offer, "appliances_2") or {}).get("key")
    if isinstance(apk, list):
        appliances = len(apk) > 0
    no_commission = (_param(offer, "commission") or {}).get("key") == "1"

    description = clean_html(offer.get("description"))
    photos = []
    for ph in (offer.get("photos") or [])[:12]:
        link = ph.get("link") or ""
        if "{width}" in link:
            photos.append(link.replace("{width}x{height}", "960x720"))
    thumbs = [p.replace("960x720", "240x180") for p in photos]
    loc = offer.get("location") or {}
    created = parse_time(offer.get("created_time"))
    refreshed = parse_time(offer.get("last_refresh_time")) or created

    item = {
        "id": f"olx:{offer['id']}",
        "source": "OLX",
        "url": offer.get("url"),
        "olx_code": olx_code(offer.get("url")),
        "city": city["slug"],
        "district": ((loc.get("district") or {}).get("name") or "").strip() or None,
        "title": (offer.get("title") or "").strip(),
        "text": description[:2500],
        "price": round(float(value)),
        "rooms": rooms,
        "area": area,
        "floor": floor,
        "floors": floors,
        "pets": pets,
        "kids": kids,
        "furniture": furniture,
        "appliances": appliances,
        "no_commission": no_commission,
        "photos": photos,
        "thumbs": thumbs,
        "created": iso(created),
        "updated": iso(refreshed),
        "author": f"olx-user:{(offer.get('user') or {}).get('id')}" if (offer.get("user") or {}).get("id") else None,
        "phones": find_phones(description),
        "owner_flag": True,
    }
    guess_from_text(item["title"] + "\n" + description, item)
    return item
