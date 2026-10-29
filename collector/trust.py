"""Відсіювання ріелторів: стоп-слова, слова-сумніви, підрахунок оголошень автора."""
import re

from common import norm_text, read_word_list


def _compile(word):
    w = norm_text(word)
    exact = len(w) > 1 and w[0] == w[-1] == '"'
    if exact:
        w = w[1:-1].strip()
    if not w:
        return None
    body = re.escape(w).replace(r"\ ", r"\s+")
    starts_with_letter = w[0].isalnum()
    ends_with_letter = w[-1].isalnum()
    left = r"(?<![\w])" if starts_with_letter else ""
    right = r"(?![\w])" if (exact and ends_with_letter) else ""
    return word.strip(), re.compile(left + body + right)


class TrustRules:
    def __init__(self):
        self.stop = [c for c in map(_compile, read_word_list("stop_words.txt")) if c]
        self.doubt = [c for c in map(_compile, read_word_list("doubt_words.txt")) if c]
        allow = sorted({norm_text(p) for p in read_word_list("allow_phrases.txt")}, key=len, reverse=True)
        self.allow = [re.compile(re.escape(p).replace(r"\ ", r"\s+")) for p in allow if p]

    def _prepared(self, item):
        t = norm_text(item.get("title", "") + " \n " + item.get("text", ""))
        for rx in self.allow:
            t = rx.sub(" ", t)
        return t

    def stop_hit(self, item):
        t = self._prepared(item)
        for word, rx in self.stop:
            if rx.search(t):
                return word
        return None

    def doubt_hit(self, item):
        t = self._prepared(item)
        for word, rx in self.doubt:
            if rx.search(t):
                return word
        return None


def flat_signature(item):
    """Груба «прикмета» квартири, щоб одна квартира автора рахувалась один раз."""
    area = round(item["area"]) if item.get("area") else None
    return (item.get("city"), item.get("rooms"), area, item.get("floor"))


def author_counts(items):
    """Скільки РІЗНИХ квартир має кожен автор / номер телефону."""
    by_key = {}
    for it in items:
        keys = []
        if it.get("author"):
            keys.append(it["author"])
        keys += [f"tel:{p}" for p in it.get("phones") or []]
        for k in keys:
            by_key.setdefault(k, set()).add(flat_signature(it))
    return {k: len(v) for k, v in by_key.items()}
