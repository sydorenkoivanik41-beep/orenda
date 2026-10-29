"""Публікація готового сайту на GitHub Pages (гілка gh-pages) і читання попереднього стану."""
import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from common import ROOT

API = "https://api.github.com"
BRANCH = "gh-pages"


def get_token():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip()
    f = ROOT / "github_token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8-sig").strip()
    return None


def get_repo(settings):
    return os.environ.get("GITHUB_REPOSITORY") or settings.repo or None


def _call(method, path, token, payload=None, accept="application/vnd.github+json"):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orenda-collector",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    if accept.endswith("raw"):
        return body
    return json.loads(body) if body else {}


def load_previous_state(settings, log):
    """Забирає з GitHub дані минулого запуску (щоб не втрачати історію)."""
    local = ROOT / "site" / "data" / "state.json"
    token, repo = get_token(), get_repo(settings)
    if token and repo:
        try:
            raw = _call("GET", f"/repos/{repo}/contents/data/state.json?ref={BRANCH}", token,
                        accept="application/vnd.github.raw")
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                log(f"  не вдалося прочитати попередній стан з GitHub: {e}")
        except Exception as e:
            log(f"  не вдалося прочитати попередній стан з GitHub: {e}")
    if local.exists():
        try:
            return json.loads(local.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def publish(site_dir: Path, settings, log, message="Оновлення оголошень"):
    token, repo = get_token(), get_repo(settings)
    if not token or not repo:
        raise SystemExit(
            "Немає даних для публікації: потрібен токен (файл github_token.txt) "
            "і назва репозиторію (рядок «репозиторій» у settings.ini)."
        )
    tree = []
    for path in sorted(site_dir.rglob("*")):
        if path.is_file():
            blob = _call("POST", f"/repos/{repo}/git/blobs", token, {
                "content": base64.b64encode(path.read_bytes()).decode(),
                "encoding": "base64",
            })
            tree.append({"path": path.relative_to(site_dir).as_posix(), "mode": "100644",
                         "type": "blob", "sha": blob["sha"]})
    t = _call("POST", f"/repos/{repo}/git/trees", token, {"tree": tree})
    # коміт без «батьків» — історія гілки не розростається
    c = _call("POST", f"/repos/{repo}/git/commits", token,
              {"message": message, "tree": t["sha"], "parents": []})
    try:
        _call("PATCH", f"/repos/{repo}/git/refs/heads/{BRANCH}", token, {"sha": c["sha"], "force": True})
    except urllib.error.HTTPError as e:
        if e.code not in (404, 422):
            raise
        _call("POST", f"/repos/{repo}/git/refs", token, {"ref": f"refs/heads/{BRANCH}", "sha": c["sha"]})
    owner, name = repo.split("/", 1)
    log(f"Опубліковано. Сайт: https://{owner.lower()}.github.io/{name}/")
