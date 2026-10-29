"""
Обробка ЗАЗДАЛЕГІДЬ зібраних даних (папка raw/) — без звернень до OLX/LUN.

Демо-режим: оголошення один раз зібрані з домашнього браузера (сервери GitHub
OLX і LUN блокують), а тут вони проходять ті самі фільтри ріелторів і
пошук дублікатів, після чого сайт викладається на GitHub Pages.
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect  # noqa: E402
import lun  # noqa: E402
import olx  # noqa: E402
from common import ROOT, Http, Settings, iso, now_utc  # noqa: E402
from publish import publish  # noqa: E402

log = collect.log


def photos_reachable(items):
    """Чи пускають CDN з фото цей сервер (інакше не гаємо час на порівняння фото)."""
    urls = [u for it in items for u in (it.get("thumbs") or [])[:1]][:4]
    ok = 0
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                ok += r.status == 200
        except Exception:
            pass
    return ok >= 2


def main():
    s = Settings()
    http = Http(s, log)
    raw = ROOT / "raw"
    items, status = [], []
    collected_at = []
    for city in s.cities:
        for name in ("OLX", "LUN"):
            f = raw / f"{name.lower()}_{city['slug']}.json"
            if not f.exists():
                status.append({"city": city["name"], "source": name, "ok": False, "note": "немає зібраних даних"})
                continue
            d = json.loads(f.read_text(encoding="utf-8"))
            collected_at.append(d.get("collected") or "")
            got = []
            if name == "OLX":
                cid = d.get("city_id")
                for o in d.get("offers") or []:
                    if o.get("business") or (o.get("category") or {}).get("id") != olx.CATEGORY_ID:
                        continue
                    if cid and ((o.get("location") or {}).get("city") or {}).get("id") != cid:
                        continue
                    it = olx.normalize(o, city, s)
                    if it:
                        got.append(it)
            else:
                for r in d.get("list") or []:
                    if not r.get("is_owner") or r.get("section_id") not in (None, 2):
                        continue
                    it = lun.normalize(r, city, d.get("rate"), s)
                    if it:
                        got.append(it)
            for it in got:
                it["seen"] = d.get("collected") or iso(now_utc())
            items += got
            status.append({"city": city["name"], "source": name, "ok": True, "note": f"{len(got)} оголошень"})
            log(f"{name} {city['name']}: {len(got)}")

    if s.compare_photos and not photos_reachable(items):
        log("Фото-сервери недоступні з цього сервера — порівняння фото пропущено")
        s.compare_photos = False
    listings, state, stats = collect.process(items, s, {}, http)
    log("Підсумок: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    out = ROOT / "site"
    collect.write_site(listings, state, stats, status, s, out)

    # у демо-версії підвал має казати правду про оновлення
    app = out / "app.js"
    when = max(collected_at)[:10] if collected_at else ""
    app.write_text(app.read_text(encoding="utf-8").replace(
        "Дані оновлюються автоматично кожні ~3 години.",
        f"Демо-версія: оголошення зібрано одноразово ({when}), автооновлення вимкнене."), encoding="utf-8")
    meta_path = out / "data" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if collected_at:
        meta["updated"] = max(collected_at)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    publish(out, s, log, message="Демо: дані з папки raw/")


if __name__ == "__main__":
    main()
