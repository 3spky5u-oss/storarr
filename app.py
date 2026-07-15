import json
import os
import shutil
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, jsonify

app = Flask(__name__)

DATA_DIR = os.environ.get("STORARR_DATA_DIR", "/data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
LOG_PATH = os.path.join(DATA_DIR, "storarr.log")

DEFAULT_CONFIG = {
    "plex_url": "http://plex:32400",
    "plex_token": "",
    "radarr_url": "http://radarr:7878",
    "radarr_api_key": "",
    "storage_path": "/data-storage",
    "disk_threshold_gb": 3000,
    "min_free_gb": 250,
    "stale_days": 90,
    "check_interval_minutes": 30,
    "dry_run": False,
    "enabled": True,
    "keep_tag": "",
    "max_evictions_per_run": 5,
    "movies_library_key": "1",
    # optional TV-show rollover, off by default -- most people want shows kept forever
    "tv_enabled": False,
    "sonarr_url": "http://sonarr:8989",
    "sonarr_api_key": "",
    "shows_library_key": "2",
    "tv_stale_days": 365,
}

_lock = threading.Lock()


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH) as f:
        return json.load(f)


def add_history(entry):
    hist = load_history()
    entry["time"] = datetime.now().isoformat(timespec="seconds")
    hist.insert(0, entry)
    hist = hist[:300]
    with open(HISTORY_PATH, "w") as f:
        json.dump(hist, f, indent=2)


def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def disk_used_bytes(path):
    return shutil.disk_usage(path).used


def disk_total_bytes(path):
    return shutil.disk_usage(path).total


def over_limit(cfg):
    """True if either the used-space threshold or the min-free-space floor is breached."""
    usage = shutil.disk_usage(cfg["storage_path"])
    over_used = usage.used >= cfg["disk_threshold_gb"] * 1024**3
    under_free = usage.free <= cfg["min_free_gb"] * 1024**3
    return over_used or under_free


def total_freed_gb():
    return round(sum(h.get("size_gb", 0) for h in load_history() if not h.get("dry_run")), 1)


def get_stale_plex_items(cfg, library_key, stale_days, kind):
    """kind: 'movie' -> top-level Video items. 'show' -> Directory items (shows),
    using their aggregate lastViewedAt/viewedLeafCount."""
    url = f"{cfg['plex_url']}/library/sections/{library_key}/all?X-Plex-Token={cfg['plex_token']}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        root = ET.fromstring(resp.read())

    cutoff = time.time() - stale_days * 86400
    candidates = []
    tag = "Video" if kind == "movie" else "Directory"
    for item in root.findall(tag):
        last_viewed = item.get("lastViewedAt")
        if kind == "movie":
            view_count = item.get("viewCount")
            watched = bool(view_count) and int(view_count) >= 1
        else:
            viewed_leaf = item.get("viewedLeafCount")
            watched = bool(viewed_leaf) and int(viewed_leaf) >= 1
        if not watched or not last_viewed:
            continue
        last_viewed = int(last_viewed)
        if last_viewed > cutoff:
            continue

        file_path = None
        size = 0
        if kind == "movie":
            media = item.find("Media")
            if media is not None:
                part = media.find("Part")
                if part is not None:
                    file_path = part.get("file")
                    size = int(part.get("size") or 0)
            if not file_path:
                continue
        candidates.append({
            "title": item.get("title"),
            "lastViewedAt": last_viewed,
            "file": file_path,
            "size": size,
        })
    candidates.sort(key=lambda c: c["lastViewedAt"])
    return candidates


def get_arr_items(base_url, api_key, endpoint):
    req = urllib.request.Request(f"{base_url}/api/v3/{endpoint}", headers={"X-Api-Key": api_key})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def delete_arr_item(base_url, api_key, endpoint, item_id):
    req = urllib.request.Request(
        f"{base_url}/api/v3/{endpoint}/{item_id}?deleteFiles=true&addImportExclusion=false",
        headers={"X-Api-Key": api_key},
        method="DELETE",
    )
    urllib.request.urlopen(req, timeout=30)


def has_keep_tag(arr_item, all_tags, keep_tag):
    if not keep_tag:
        return False
    tag_id = None
    for t in all_tags:
        if t.get("label", "").lower() == keep_tag.lower():
            tag_id = t.get("id")
            break
    if tag_id is None:
        return False
    return tag_id in (arr_item.get("tags") or [])


def evict_stale(cfg, kind, evictions_left):
    """Returns (evicted_titles, evictions_left_remaining)."""
    if kind == "movie":
        library_key = cfg["movies_library_key"]
        stale_days = cfg["stale_days"]
        arr_url, arr_key, endpoint = cfg["radarr_url"], cfg["radarr_api_key"], "movie"
        file_field = "path"
    else:
        library_key = cfg["shows_library_key"]
        stale_days = cfg["tv_stale_days"]
        arr_url, arr_key, endpoint = cfg["sonarr_url"], cfg["sonarr_api_key"], "series"
        file_field = "path"

    stale = get_stale_plex_items(cfg, library_key, stale_days, kind)
    if not stale:
        return [], evictions_left

    arr_items = get_arr_items(arr_url, arr_key, endpoint)
    all_tags = get_arr_items(arr_url, arr_key, "tag")

    by_path = {}
    for m in arr_items:
        if kind == "movie":
            mf = m.get("movieFile")
            p = mf.get("path") if mf else None
        else:
            p = m.get("path")  # series root folder
        if p:
            by_path[os.path.normpath(p)] = m

    evicted = []
    for candidate in stale:
        if evictions_left <= 0:
            break
        if not over_limit(cfg):
            break

        if kind == "movie":
            norm = os.path.normpath(candidate["file"])
            item = by_path.get(norm)
        else:
            # match show by title against series root folder name, best-effort
            item = next((m for m in arr_items if m.get("title") == candidate["title"]), None)

        if not item:
            log(f"WARNING: no {endpoint} match for '{candidate['title']}'")
            continue

        if has_keep_tag(item, all_tags, cfg["keep_tag"]):
            log(f"Skipping '{candidate['title']}' — has keep tag '{cfg['keep_tag']}'")
            continue

        watched_days_ago = int((time.time() - candidate["lastViewedAt"]) / 86400)
        if cfg["dry_run"]:
            log(f"[DRY RUN] Would evict {kind} '{candidate['title']}' (watched {watched_days_ago}d ago)")
        else:
            log(f"Evicting {kind} '{candidate['title']}' (watched {watched_days_ago}d ago)")
            delete_arr_item(arr_url, arr_key, endpoint, item["id"])

        add_history({"title": candidate["title"], "kind": kind, "watched_days_ago": watched_days_ago,
                     "size_gb": round(candidate["size"] / 1024**3, 2), "dry_run": cfg["dry_run"]})
        evicted.append(candidate["title"])
        evictions_left -= 1

    return evicted, evictions_left


def run_check(manual=False):
    cfg = load_config()
    if not cfg["enabled"] and not manual:
        return {"ran": False, "reason": "disabled"}
    if not cfg["plex_token"] or not cfg["radarr_api_key"]:
        return {"ran": False, "reason": "not configured"}

    with _lock:
        used_gb = disk_used_bytes(cfg["storage_path"]) / 1024**3

        if not over_limit(cfg) and not manual:
            return {"ran": True, "action": "none", "used_gb": round(used_gb, 1)}

        if not over_limit(cfg):
            # manual preview run, under limits: just report what's eligible
            try:
                stale = get_stale_plex_items(cfg, cfg["movies_library_key"], cfg["stale_days"], "movie")
            except Exception as e:
                return {"ran": True, "action": "error", "error": str(e)}
            return {"ran": True, "action": "preview", "used_gb": round(used_gb, 1), "eligible": stale}

        evictions_left = cfg["max_evictions_per_run"]
        all_evicted = []
        try:
            evicted, evictions_left = evict_stale(cfg, "movie", evictions_left)
            all_evicted += evicted
            if cfg["tv_enabled"] and evictions_left > 0:
                evicted, evictions_left = evict_stale(cfg, "show", evictions_left)
                all_evicted += evicted
        except Exception as e:
            log(f"ERROR during eviction: {e}")
            return {"ran": True, "action": "error", "error": str(e)}

        final_used = disk_used_bytes(cfg["storage_path"]) / 1024**3
        if over_limit(cfg) and all_evicted and evictions_left <= 0:
            log(f"Hit max evictions per run ({cfg['max_evictions_per_run']}) while still over limits. Will continue next check.")
        elif over_limit(cfg) and all_evicted:
            log(f"Still over limits after evicting all eligible stale media ({final_used:.1f}GB used).")

        return {"ran": True, "action": "evicted", "count": len(all_evicted), "titles": all_evicted,
                "used_gb": round(final_used, 1)}


def background_loop():
    while True:
        cfg = load_config()
        try:
            run_check()
        except Exception as e:
            log(f"ERROR in background check: {e}")
        time.sleep(max(cfg["check_interval_minutes"], 5) * 60)


@app.route("/")
def dashboard():
    cfg = load_config()
    history = load_history()
    configured = bool(cfg["plex_token"] and cfg["radarr_api_key"])
    disk_info = None
    if os.path.exists(cfg["storage_path"]):
        used = disk_used_bytes(cfg["storage_path"])
        total = disk_total_bytes(cfg["storage_path"])
        disk_info = {
            "used_gb": round(used / 1024**3, 1),
            "total_gb": round(total / 1024**3, 1),
            "free_gb": round((total - used) / 1024**3, 1),
            "threshold_gb": cfg["disk_threshold_gb"],
            "min_free_gb": cfg["min_free_gb"],
            "pct": round(used / total * 100, 1),
            "over_threshold": over_limit(cfg),
        }
    return render_template("dashboard.html", cfg=cfg, history=history[:15],
                            configured=configured, disk_info=disk_info,
                            total_freed_gb=total_freed_gb())


@app.route("/history")
def history_page():
    return render_template("history.html", history=load_history(), total_freed_gb=total_freed_gb())


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        cfg = load_config()
        for field in ["plex_url", "plex_token", "movies_library_key", "radarr_url", "radarr_api_key",
                      "storage_path", "keep_tag", "sonarr_url", "sonarr_api_key", "shows_library_key"]:
            cfg[field] = request.form.get(field, cfg[field]).strip()
        for field in ["disk_threshold_gb", "min_free_gb", "stale_days", "check_interval_minutes",
                      "max_evictions_per_run", "tv_stale_days"]:
            cfg[field] = int(request.form.get(field, cfg[field]))
        cfg["dry_run"] = "dry_run" in request.form
        cfg["enabled"] = "enabled" in request.form
        cfg["tv_enabled"] = "tv_enabled" in request.form
        save_config(cfg)
        return redirect(url_for("settings", saved=1))
    cfg = load_config()
    return render_template("settings.html", cfg=cfg, saved=request.args.get("saved"))


@app.route("/run-now", methods=["POST"])
def run_now():
    result = run_check(manual=True)
    return jsonify(result)


@app.route("/api/status")
def api_status():
    cfg = load_config()
    used = disk_used_bytes(cfg["storage_path"]) if os.path.exists(cfg["storage_path"]) else 0
    return jsonify({"used_gb": round(used / 1024**3, 1), "threshold_gb": cfg["disk_threshold_gb"]})


if __name__ == "__main__":
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8585)
