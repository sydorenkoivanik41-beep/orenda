"""Пошук дублікатів: одна квартира = одне оголошення на сайті."""
import io
import re
import time

from common import norm_text

# ------------------------------------------------------------- схожість фото
def dhash(image_bytes):
    """64-бітний «відбиток» фото: схожі фото дають схожі відбитки."""
    from PIL import Image  # імпорт тут, щоб без Pillow усе інше працювало
    img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((9, 8), Image.LANCZOS)
    px = list(img.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
    return f"{bits:016x}"


def hamming(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def add_photo_hashes(items, cache, http, log, max_new=1500):
    """Рахує відбитки перших 3 фото кожного оголошення (з кешем між запусками)."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        log("  (Pillow не встановлено — порівняння фото пропущено)")
        return
    new = 0
    for it in items:
        hashes = []
        for url in (it.get("thumbs") or [])[:3]:
            h = cache.get(url)
            if h is None and new < max_new:
                try:
                    time.sleep(0.15)  # фото віддає CDN, але все одно не поспішаємо
                    h = dhash(http.get(url, accept="image/*", pause=False, tries=1))
                except Exception:
                    h = ""
                cache[url] = h
                new += 1
            if h:
                hashes.append(h)
        it["ph"] = hashes
    log(f"  фото: нових відбитків {new}")


# ------------------------------------------------------------- схожість тексту
def shingles(text):
    words = re.findall(r"[\w']+", norm_text(text))
    if len(words) < 12:
        return None
    return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ------------------------------------------------------------- об'єднання
class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _close(a, b, abs_tol, rel_tol):
    return abs(a - b) <= max(abs_tol, rel_tol * max(a, b))


def compatible(a, b):
    if a.get("rooms") and b.get("rooms") and a["rooms"] != b["rooms"]:
        return False
    if a.get("area") and b.get("area") and not _close(a["area"], b["area"], 2, 0.06):
        return False
    if a.get("floor") and b.get("floor") and a["floor"] != b["floor"]:
        return False
    return True


def same_flat(a, b):
    """Повертає причину, якщо a і b — це одна квартира, інакше None."""
    if not compatible(a, b):
        return None
    # 1) однакові фото
    for ha in a.get("ph") or []:
        for hb in b.get("ph") or []:
            if hamming(ha, hb) <= 5:
                return "фото"
    # 2) той самий телефон
    if set(a.get("phones") or []) & set(b.get("phones") or []):
        if a.get("area") and b.get("area"):
            return "телефон"
    # 3) район + площа + поверх + кімнати
    if (a.get("district") and a.get("district") == b.get("district")
            and a.get("area") and b.get("area") and abs(a["area"] - b["area"]) <= 0.6
            and a.get("floor") and a.get("floor") == b.get("floor")
            and a.get("rooms") and a.get("rooms") == b.get("rooms")
            and (not a.get("floors") or not b.get("floors") or a["floors"] == b["floors"])):
        return "район+площа+поверх"
    # 4) дуже схожий текст
    if jaccard(a.get("_sh"), b.get("_sh")) >= 0.55:
        return "текст"
    return None


def cluster(items):
    """Групує оголошення однієї квартири. Повертає список груп (списків)."""
    n = len(items)
    dsu = DSU(n)
    for it in items:
        it["_sh"] = shingles(it.get("title", "") + " " + it.get("text", ""))
    # точні збіги: той самий код OLX (LUN часто показує копію оголошення OLX)
    for key in ("olx_code", "lun_group"):
        first = {}
        for i, it in enumerate(items):
            k = it.get(key)
            if k:
                if (it["city"], k) in first:
                    dsu.union(first[(it["city"], k)], i)
                else:
                    first[(it["city"], k)] = i
    # попарне порівняння в межах міста
    by_city = {}
    for i, it in enumerate(items):
        by_city.setdefault(it["city"], []).append(i)
    for idxs in by_city.values():
        for x in range(len(idxs)):
            a = items[idxs[x]]
            for y in range(x + 1, len(idxs)):
                i, j = idxs[x], idxs[y]
                if dsu.find(i) == dsu.find(j):
                    continue
                if same_flat(a, items[j]):
                    dsu.union(i, j)
    groups = {}
    for i in range(n):
        groups.setdefault(dsu.find(i), []).append(items[i])
    for it in items:
        it.pop("_sh", None)
    return list(groups.values())
