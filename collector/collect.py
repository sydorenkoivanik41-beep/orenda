"""
ГОЛОВНИЙ ФАЙЛ ЗБИРАЧА.

Запуск:
    python collector/collect.py            — зібрати дані й зібрати сайт у папку site/
    python collector/collect.py --publish  — те саме + викласти сайт на GitHub Pages
"""
import argparse
import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dedup  # noqa: E402
import lun  # noqa: E402
import olx  # noqa: E402
from common import ROOT, Blocked, Http, Settings, iso, now_utc, parse_time  # noqa: E402
from publish import load_previous_state, publish  # noqa: E402
from trust import TrustRules, author_counts  # noqa: E402

SOURCES = (("OLX", olx), ("LUN", lun))
KEEP_FAILED_HOURS = 48  # якщо джерело тимчасово недоступне — показуємо старі дані ще 2 доби


def log(msg):
    print(msg, flush=True)


# --------------------------------------------------------------------- збір
def gather(settings, http, prev, only_cities=None):
    prev_items = prev.get("items") or []
    now = now_utc()
    items, status = [], []
    blocked_sources = set()
    for city in settings.cities:
        if only_cities and city["slug"] not in only_cities:
            continue
        log(f"Місто: {city['name']}")
        for name, module in SOURCES:
            ok, note, got = False, "", []
            if name in blocked_sources:
                note = "пропущено (джерело заблокувало запити)"
            else:
                try:
                    got = module.collect(http, settings, city, log)
                    ok = True
                    note = f"{len(got)} оголошень"
                except Blocked as e:
                    blocked_sources.add(name)
                    note = f"заблоковано: {e}"
                except Exception as e:  # noqa: BLE001
                    note = f"помилка: {type(e).__name__}: {e}"
            if ok:
                for it in got:
                    it["seen"] = iso(now)
                items += got
            else:
                log(f"  {name} {city['name']}: {note}")
                limit = now - timedelta(hours=KEEP_FAILED_HOURS)
                old = [it for it in prev_items
                       if it.get("source") == name and it.get("city") == city["slug"]
                       and (parse_time(it.get("seen")) or now) >= limit]
                items += old
                if old:
                    note += f"; показуємо {len(old)} збережених"
            status.append({"city": city["name"], "source": name, "ok": ok, "note": note})
    return items, status


# --------------------------------------------------------------------- обробка
def process(items, settings, prev, http=None):
    now = now_utc()
    rules = TrustRules()
    stats = {"collected": len(items)}

    # 1. прибираємо застарілі
    limit = now - timedelta(days=settings.keep_days)
    items = [it for it in items if (parse_time(it.get("created")) or now) >= limit]

    # 2. відбитки фото
    cache = dict(prev.get("photo_hashes") or {})
    if settings.compare_photos and http is not None:
        dedup.add_photo_hashes(items, cache, http, log)
    else:
        for it in items:
            it["ph"] = [cache[u] for u in (it.get("thumbs") or [])[:3] if cache.get(u)]

    # 3. скільки різних квартир у кожного автора / телефону (рахуємо до фільтра слів)
    counts = author_counts(items)

    # 4. стоп-слова
    kept, hidden_words = [], 0
    for it in items:
        if rules.stop_hit(it):
            hidden_words += 1
        else:
            kept.append(it)
    stats["hidden_words"] = hidden_words

    # 5. дублікати
    groups = dedup.cluster(kept)
    stats["merged_duplicates"] = len(kept) - len(groups)

    # 6. оцінка довіри й об'єднання
    first_seen = dict(prev.get("first_seen") or {})
    out, hidden_agents = [], 0
    for g in groups:
        keys = set()
        for it in g:
            if it.get("author"):
                keys.add(it["author"])
            keys |= {f"tel:{p}" for p in it.get("phones") or []}
        n_flats = max([counts.get(k, 1) for k in keys] or [1])
        if n_flats > settings.max_per_author:
            hidden_agents += 1
            continue
        why = []
        if n_flats >= 2:
            why.append(f"автор має {n_flats} оголошення про різні квартири")
        for it in g:
            w = rules.doubt_hit(it)
            if w:
                why.append(f"у тексті є «{w}»")
                break
        rec = merge(g, first_seen, now)
        rec["trust"] = "doubt" if why else "owner"
        if why:
            rec["why"] = why
        out.append(rec)
    stats["hidden_agents"] = hidden_agents
    stats["shown"] = len(out)

    # first_seen лише для актуальних
    alive = {it["id"] for it in items}
    first_seen = {k: v for k, v in first_seen.items() if k in alive}
    used_thumbs = {u for it in items for u in (it.get("thumbs") or [])[:3]}
    cache = {u: h for u, h in cache.items() if u in used_thumbs}
    for it in items:
        it.pop("ph", None)
    state = {"items": items, "photo_hashes": cache, "first_seen": first_seen}
    return out, state, stats


def merge(group, first_seen, now):
    """Збирає одну картку з кількох оголошень про ту саму квартиру."""
    group = sorted(group, key=lambda it: it.get("updated") or "", reverse=True)
    newest = group[0]
    rec = {}
    for key in ("city", "district", "rooms", "area", "floor", "floors"):
        rec[key] = next((it[key] for it in group if it.get(key) not in (None, "")), None)
    for key in ("pets", "kids", "furniture", "appliances"):
        vals = [it[key] for it in group if it.get(key) is not None]
        rec[key] = vals[0] if vals else None
    rec["price"] = newest["price"]  # найсвіжіша ціна
    older_prices = [it["price"] for it in group[1:] if it["price"] != newest["price"]]
    if older_prices:
        rec["old_price"] = older_prices[0]
    best_photos = max(group, key=lambda it: len(it.get("photos") or []))
    rec["photos"] = best_photos.get("photos") or []
    rec["title"] = next((it["title"] for it in group if it.get("title")), "")
    rec["text"] = max((it.get("text") or "" for it in group), key=len)
    created = [it["created"] for it in group if it.get("created")]
    for it in group:
        first_seen.setdefault(it["id"], iso(now))
    rec["published"] = min(created) if created else min(first_seen[it["id"]] for it in group)
    rec["updated"] = newest.get("updated") or rec["published"]
    links, seen_urls = [], set()
    for it in group:
        cand = [(it["source"], it["url"])]
        if it["source"] == "LUN" and it.get("original_url") and "olx" in (it.get("original_site") or ""):
            cand.append(("OLX", it["original_url"]))
        for site, url in cand:
            if url and url not in seen_urls and not any(l["site"] == site and l["url"] == url for l in links):
                seen_urls.add(url)
                links.append({"site": site, "url": url})
    # не більше одного посилання OLX і одного LUN на кнопках (решта — «ще»)
    rec["links"] = links
    rec["id"] = sorted(it["id"] for it in group)[0]
    rec["n_sources"] = len(group)
    return rec


# --------------------------------------------------------------------- вивід
def write_site(listings, state, stats, status, settings, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(ROOT / "web", out_dir)
    data = out_dir / "data"
    data.mkdir(parents=True, exist_ok=True)
    (out_dir / ".nojekyll").write_text("")
    cities_meta = []
    for city in settings.cities:
        rows = [r for r in listings if r.get("city") == city["slug"]]
        rows.sort(key=lambda r: r["published"] or "", reverse=True)
        for r in rows:
            r.pop("city", None)
        (data / f"{city['slug']}.json").write_text(
            json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        districts = sorted({r["district"] for r in rows if r.get("district")})
        cities_meta.append({"name": city["name"], "slug": city["slug"],
                            "count": len(rows), "districts": districts})
    meta = {"updated": iso(now_utc()), "cities": cities_meta, "status": status, "stats": stats}
    (data / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (data / "state.json").write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="викласти сайт на GitHub Pages")
    ap.add_argument("--city", action="append", help="лише це місто (адреса OLX), можна кілька")
    args = ap.parse_args()

    settings = Settings()
    log(f"Міст у налаштуваннях: {len(settings.cities)}")
    http = Http(settings, log)
    prev = load_previous_state(settings, log)
    items, status = gather(settings, http, prev, args.city)
    listings, state, stats = process(items, settings, prev, http)
    log("Підсумок: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    out_dir = ROOT / "site"
    write_site(listings, state, stats, status, settings, out_dir)
    log(f"Сайт зібрано в папці {out_dir}")
    if args.publish:
        publish(out_dir, settings, log)
    if status and not any(s["ok"] for s in status):
        log("УВАГА: жодне джерело не відповіло. Ймовірно, сайти блокують запити з цього комп'ютера/сервера.")
        sys.exit(2 if not listings else 0)


if __name__ == "__main__":
    main()
