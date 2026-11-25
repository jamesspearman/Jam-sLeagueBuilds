"""
Jam's League Builds
===================
Pick a role, a champion, a region and a patch, click Search, and get the most
popular high-win-rate build for Platinum+ (or the rank set in settings.json) ranked solo queue: runes, summoner spells,
skill order, starting items, the full item build in purchase order, and which
component pieces to buy first for your first major item.

Data sources
  * Build statistics: u.gg's public stats files (stats2.u.gg), ranked solo queue, Platinum+ by default.
  * Names, icons, recipes: Riot's official Data Dragon (ddragon.leagueoflegends.com).

Run:   python app.py        (then open http://localhost:8766 if it doesn't open by itself)

Only uses the Python standard library (plus Windows' built-in curl.exe when available).
"""

import argparse
import re
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP_NAME = "Jam's League Builds"
FROZEN = getattr(sys, "frozen", False)  # True when running as the packaged .exe
HERE = os.path.dirname(os.path.abspath(__file__))
# Bundled read-only files (page, icon): inside the .exe's temp folder when packaged, else this folder.
RES_DIR = getattr(sys, "_MEIPASS", HERE)
STATIC_DIR = os.path.join(RES_DIR, "static")
# Where settings.json is looked for: next to the .exe, or this folder.
APP_DIR = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else HERE
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
# Downloaded data: the user's AppData when packaged (the .exe may sit in Downloads), else ./cache.
DATA_DIR = (os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "JamsLeagueBuilds")
            if FROZEN else HERE)
CACHE_DIR = os.path.join(DATA_DIR, "cache")

DDRAGON = "https://ddragon.leagueoflegends.com"
UGG = "https://stats2.u.gg/lol/1.5"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DEFAULT_SETTINGS = {
    "port": 8766,
    "ugg_api_version": "1.5.0",
    # u.gg's internal number and name for the rank bracket. 10 = Platinum+, 16 = Emerald+, 11 = Diamond+.
    "ugg_rank_key": "10",
    "ugg_rank_name": "platinum_plus",
    "rank_label": "Platinum+",
    # u.gg's internal region numbers.
    "regions": {
        "any": {"label": "Any (all regions)", "key": "12", "name": "world"},
        "na": {"label": "NA", "key": "1", "name": "na1"},
        "euw": {"label": "EUW", "key": "2", "name": "euw1"},
        "kr": {"label": "KR", "key": "3", "name": "kr"},
        "eune": {"label": "EUNE", "key": "4", "name": "eun1"},
        "br": {"label": "BR", "key": "5", "name": "br1"},
        "lan": {"label": "LAN", "key": "6", "name": "la1"},
        "las": {"label": "LAS", "key": "7", "name": "la2"},
        "oce": {"label": "OCE", "key": "8", "name": "oc1"},
        "ru": {"label": "RU", "key": "9", "name": "ru"},
        "tr": {"label": "TR", "key": "10", "name": "tr1"},
        "jp": {"label": "JP", "key": "11", "name": "jp1"},
    },
    # Builds with fewer games than this get a "small sample" warning.
    "low_sample_games": 200,
    # Henry's rule for a recommended build: win rate strictly above this (percent)...
    "min_winrate": 50.0,
    # ...and played in at least this share of the champion's games (0.10 = 10%).
    "min_pick_share": 0.10,
    # ...and backed by at least this many games, so a high win rate isn't just luck
    # (at 1,000 games the win rate is accurate to roughly +/-1.5%).
    "min_build_games": 1000,
    # Same idea for the single 4th/5th/6th item picks (fewer games reach those slots).
    "min_item_games": 300,
    # A champion's own late item only counts as a situational pick with at least this many games.
    "min_situational_games": 100,
    # A champion shows in a role's dropdown if at least this share of that role's games are on it.
    "role_min_pick_rate": 0.002,
    "stats_cache_hours": 6,
}

ROLES = [
    {"id": "top", "label": "Top", "ugg": "4", "rank_name": "top"},
    {"id": "jungle", "label": "Jungle", "ugg": "1", "rank_name": "jungle"},
    {"id": "mid", "label": "Mid", "ugg": "5", "rank_name": "mid"},
    {"id": "adc", "label": "Bot (ADC)", "ugg": "3", "rank_name": "adc"},
    {"id": "support", "label": "Support", "ugg": "2", "rank_name": "supp"},
]
ROLE_BY_ID = {r["id"]: r for r in ROLES}

# Stat shards (the small row under the runes). Riot doesn't publish names for these in Data Dragon.
SHARDS = {
    5001: ("Health Scaling", "StatModsHealthPlusIcon.png"),
    5002: ("Armor", "StatModsArmorIcon.png"),
    5003: ("Magic Resist", "StatModsMagicResIcon.MagicResist_Fix.png"),
    5005: ("Attack Speed", "StatModsAttackSpeedIcon.png"),
    5007: ("Ability Haste", "StatModsCDRScalingIcon.png"),
    5008: ("Adaptive Force", "StatModsAdaptiveForceIcon.png"),
    5010: ("Move Speed", "StatModsMovementSpeedIcon.png"),
    5011: ("Health", "StatModsHealthScalingIcon.png"),  # Riot's file names for these two icons are the wrong way round
    5013: ("Tenacity and Slow Resist", "StatModsTenacityIcon.png"),
}

# The three rows of stat shards, as offered in the client (offense, flex, defense).
SHARD_ROWS = [[5008, 5005, 5007], [5008, 5010, 5001], [5011, 5013, 5001]]

BOOT_IDS = {1001, 3006, 3009, 3020, 3047, 3111, 3117, 3158, 2422, 3005, 3010, 3013}


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def load_settings():
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                user = json.load(f)
            s.update({k: v for k, v in user.items() if not k.startswith("_")})
        except Exception as e:  # noqa: BLE001
            log(f"settings.json couldn't be read ({e}); using defaults.")
    return s


SETTINGS = load_settings()


# --------------------------------------------------------------------------------------
# HTTP helpers. u.gg sits behind Cloudflare, which tends to reject Python's TLS
# fingerprint but accepts curl (built into Windows 10/11), so curl is tried first.
# --------------------------------------------------------------------------------------

class FetchError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


CURL = shutil.which("curl")


def _fetch_curl(url, timeout):
    marker = "\n__HTTP_STATUS__:"
    cmd = [CURL, "-s", "-L", "--compressed", "--max-time", str(timeout),
           "-H", f"User-Agent: {BROWSER_UA}", "-H", "Accept: application/json,*/*",
           "-w", marker + "%{http_code}", url]
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    p = subprocess.run(cmd, capture_output=True, timeout=timeout + 5, **kw)
    out = p.stdout
    idx = out.rfind(marker.encode())
    if p.returncode != 0 or idx < 0:
        raise FetchError(f"curl failed (exit {p.returncode}) for {url}")
    body, status = out[:idx], int(out[idx + len(marker):].strip() or 0)
    if status != 200:
        raise FetchError(f"HTTP {status} for {url}", status)
    return body


def _fetch_urllib(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "application/json,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code} for {url}", e.code) from e
    except Exception as e:  # noqa: BLE001
        raise FetchError(f"{type(e).__name__}: {e} for {url}") from e


def fetch_json(url, timeout=20):
    errors = []
    for fn in ([_fetch_curl] if CURL else []) + [_fetch_urllib]:
        try:
            body = fn(url, timeout)
            return json.loads(body.decode("utf-8"))
        except FetchError as e:
            if e.status == 404:
                raise  # not there; no point trying another way
            errors.append(str(e))
        except (ValueError, subprocess.SubprocessError, OSError) as e:
            errors.append(f"{type(e).__name__}: {e}")
    raise FetchError("; ".join(errors) or f"couldn't fetch {url}")


def cache_path(*parts):
    p = os.path.join(CACHE_DIR, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def cached_json(path, max_age_s, loader):
    """Return JSON from `path` if fresh, else call loader() and store it.
    If loader fails and any old copy exists, use the old copy (so the app keeps working offline)."""
    if os.path.exists(path) and (max_age_s is None or time.time() - os.path.getmtime(path) < max_age_s):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    try:
        data = loader()
    except Exception:
        if os.path.exists(path):
            log(f"Using older cached copy of {os.path.relpath(path, DATA_DIR)} (couldn't refresh).")
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        raise
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    return data


# --------------------------------------------------------------------------------------
# Riot Data Dragon: champions, items (with recipes), runes, summoner spells
# --------------------------------------------------------------------------------------

class GameData:
    def __init__(self):
        self.lock = threading.Lock()
        self.loaded_at = 0
        self.version = None
        self.patches = []          # [{"id": "16_23", "label": "16.23", "ddragon": "16.23.1"}, ...] newest first
        self.champions = {}        # numeric key (str) -> {key, id, name, image}
        self.items = {}            # str id -> item dict
        self.perks = {}            # int id -> {name, icon, tree, slot}
        self.trees = {}            # int id -> {name, icon}
        self.spells = {}           # numeric key (str) -> {name, image}

    def ensure(self):
        with self.lock:
            if self.version and time.time() - self.loaded_at < 3600:
                return
            self._load()

    def _load(self):
        versions = cached_json(cache_path("ddragon_versions.json"), 3600,
                               lambda: fetch_json(f"{DDRAGON}/api/versions.json"))
        versions = [v for v in versions if v.count(".") >= 2 and not v.startswith("lolpatch")]
        v = versions[0]
        seen, patches = set(), []
        for ver in versions:
            mm = ".".join(ver.split(".")[:2])
            if mm not in seen:
                seen.add(mm)
                patches.append({"id": mm.replace(".", "_"), "label": mm, "ddragon": ver})
            if len(patches) == 2:
                break

        def dd(name):
            return cached_json(cache_path("ddragon", v, name), None,
                               lambda: fetch_json(f"{DDRAGON}/cdn/{v}/data/en_US/{name}"))

        champ_json, item_json, runes_json, spell_json = (dd("champion.json"), dd("item.json"),
                                                         dd("runesReforged.json"), dd("summoner.json"))
        champions = {}
        for c in champ_json["data"].values():
            champions[str(c["key"])] = {"key": str(c["key"]), "id": c["id"], "name": c["name"],
                                        "image": c["image"]["full"]}
        items = {}
        for iid, it in item_json["data"].items():
            items[iid] = {
                "id": int(iid), "name": it.get("name", f"Item {iid}"),
                "gold": it.get("gold", {}).get("total", 0),
                "from": [int(x) for x in it.get("from", [])],
                "into": [int(x) for x in it.get("into", [])],
                "tags": it.get("tags", []),
                "depth": it.get("depth", 1),
                "stats": it.get("stats", {}),
                "desc": re.sub(r"<[^>]+>", " ", it.get("description", "")).lower(),
                "maps11": it.get("maps", {}).get("11", True),
            }
        perks, trees = {}, {}
        for tree in runes_json:
            trees[tree["id"]] = {"name": tree["name"], "icon": tree["icon"],
                                 "slots": [[r["id"] for r in slot["runes"]] for slot in tree["slots"]]}
            for si, slot in enumerate(tree["slots"]):
                for r in slot["runes"]:
                    perks[r["id"]] = {"name": r["name"], "icon": r["icon"], "tree": tree["id"], "slot": si,
                                      "desc": re.sub(r"<[^>]+>", "", r.get("shortDesc", ""))}
        spells = {str(s["key"]): {"name": s["name"], "image": s["image"]["full"]}
                  for s in spell_json["data"].values()}

        self.version, self.patches = v, patches
        self.champions, self.items, self.perks, self.trees, self.spells = champions, items, perks, trees, spells
        self.loaded_at = time.time()
        log(f"Data Dragon {v}: {len(champions)} champions, {len(items)} items. "
            f"Patches available: {', '.join(p['label'] for p in patches)}")

    def item(self, iid):
        it = self.items.get(str(iid))
        if it:
            return it
        return {"id": int(iid), "name": f"Item {iid}", "gold": 0, "from": [], "into": [], "tags": [], "depth": 1,
                "stats": {}, "desc": "", "unknown": True}

    def by_name(self, name):
        key = _norm(name)
        best = None
        for it in self.items.values():
            if _norm(it["name"]) == key and it.get("maps11", True):
                if best is None or it["id"] < best["id"]:  # lowest id = the normal Summoner's Rift version
                    best = it
        return best


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


GD = GameData()
LAST_PING = 0.0  # last time an open page said it's still there (used by the desktop launcher)


# --------------------------------------------------------------------------------------
# u.gg statistics
# --------------------------------------------------------------------------------------

def ugg_overview(champ_key, patch_id):
    ver = SETTINGS["ugg_api_version"]
    url = f"{UGG}/overview/{patch_id}/ranked_solo_5x5/{champ_key}/{ver}.json"
    path = cache_path("ugg", patch_id, f"overview_{champ_key}.json")
    return cached_json(path, SETTINGS["stats_cache_hours"] * 3600, lambda: fetch_json(url, timeout=30))


def ugg_role_pickrates(patch_id):
    """{role_id: {champ_key: share_of_role_games}} for the chosen rank, all regions. Used only to filter the dropdown."""
    ver = SETTINGS["ugg_api_version"]
    rank = SETTINGS["ugg_rank_name"]
    url = f"{UGG}/champion_ranking/world/{patch_id}/ranked_solo_5x5/{rank}/{ver}.json"
    path = cache_path("ugg", patch_id, "champion_ranking.json")
    raw = cached_json(path, 24 * 3600, lambda: fetch_json(url, timeout=30))
    data = raw[0] if isinstance(raw, list) else raw
    out = {}
    for role in ROLES:
        rows = data.get(role["rank_name"], []) if isinstance(data, dict) else []
        total = sum(_num(r[3]) for r in rows if isinstance(r, list) and len(r) > 3) or 1
        out[role["id"]] = {str(r[0]): _num(r[3]) / total for r in rows if isinstance(r, list) and len(r) > 3}
    return out


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _wr(wins, games):
    return round(100.0 * wins / games, 1) if games else None


def _pair(a, b):
    """u.gg stores counts as [matches, wins] in some places and [wins, matches] in others.
    Wins can never exceed matches, so sort them out by size."""
    a, b = _num(a), _num(b)
    return (max(a, b), min(a, b))  # (games, wins)


def find_role_block(raw, region_key, role_key):
    rank_key = SETTINGS["ugg_rank_key"]
    try:
        entry = raw[region_key][rank_key][role_key]
    except (KeyError, TypeError, IndexError):
        return None
    # entry is [overview_array, last_updated] in current files
    if isinstance(entry, list) and entry and isinstance(entry[0], list) and entry[0] and isinstance(entry[0][0], list):
        return entry[0]
    if isinstance(entry, list) and entry and isinstance(entry[0], list):
        return entry
    return None


def rank_sanity(raw, region_key, role_key, ov):
    """Platinum+ includes every Emerald+ game, so it must have at least as many games. If it doesn't, the
    rank number in settings.json is probably wrong (u.gg renumbered); say so instead of silently using it."""
    if SETTINGS["ugg_rank_key"] != "10":
        return None
    try:
        emer = raw[region_key]["16"][role_key]
        emer = emer[0] if isinstance(emer[0][0], list) else emer
        emer_games = _pair(emer[6][0], emer[6][1])[0]
    except Exception:  # noqa: BLE001
        return None
    mine = ov.get("total", {}).get("games") or 0
    if mine and emer_games and mine < emer_games:
        return (f"Check: this rank bracket has fewer games ({int(mine)}) than Emerald+ ({int(emer_games)}), so the "
                f"rank setting may not be Platinum+. Tell Claude if you see this.")
    return None


def parse_overview(ov):
    """Turn u.gg's positional overview array into named sections. Every section is optional so a
    format change degrades to 'not available' instead of crashing."""
    out = {"warnings": []}

    def sec(i):
        return ov[i] if len(ov) > i and isinstance(ov[i], list) else None

    r = sec(0)
    if r and len(r) >= 5 and isinstance(r[4], list):
        games, wins = _pair(r[0], r[1])
        out["runes"] = {"games": games, "wins": wins, "primary": int(r[2]), "sub": int(r[3]),
                        "perks": [int(x) for x in r[4]]}
    else:
        out["warnings"].append("Rune data missing.")

    s = sec(1)
    if s and len(s) >= 3 and isinstance(s[2], list):
        games, wins = _pair(s[0], s[1])
        out["spells"] = {"games": games, "wins": wins, "ids": [str(int(x)) for x in s[2]]}

    for name, i in (("starting", 2), ("core", 3)):
        x = sec(i)
        if x and len(x) >= 3 and isinstance(x[2], list):
            games, wins = _pair(x[0], x[1])
            out[name] = {"games": games, "wins": wins, "ids": [int(v) for v in x[2]]}
        else:
            out["warnings"].append(f"{name.title()} item data missing.")

    k = sec(4)
    if k and len(k) >= 3:
        games, wins = _pair(k[0], k[1])
        order = [str(c) for c in k[2]] if isinstance(k[2], list) else []
        priority = k[3] if len(k) > 3 and isinstance(k[3], str) else ""
        out["skills"] = {"games": games, "wins": wins, "order": order, "priority": priority}

    late = sec(5)
    if late:
        slots = []
        for slot in late[:3]:
            opts = []
            if isinstance(slot, list):
                for o in slot:
                    if isinstance(o, list) and len(o) >= 3:
                        games, wins = _pair(o[1], o[2])
                        opts.append({"id": int(o[0]), "games": games, "wins": wins})
            opts.sort(key=lambda o: o["games"], reverse=True)
            slots.append(opts)
        out["late"] = slots

    tot = sec(6)
    if tot and len(tot) >= 2:
        games, wins = _pair(tot[0], tot[1])
        out["total"] = {"games": games, "wins": wins}

    sh = sec(8)
    if sh and len(sh) >= 3 and isinstance(sh[2], list):
        games, wins = _pair(sh[0], sh[1])
        out["shards"] = {"games": games, "wins": wins, "ids": [int(x) for x in sh[2]]}
    return out


# --------------------------------------------------------------------------------------
# Turning stats into what the page shows
# --------------------------------------------------------------------------------------

def item_view(iid, games=None, wins=None):
    it = GD.item(iid)
    v = {"id": it["id"], "name": it["name"], "gold": it["gold"], "boots": it["id"] in BOOT_IDS or "Boots" in it["tags"]}
    if games is not None:
        v["games"] = int(games)
        v["winrate"] = _wr(wins, games)
    return v


def first_item_plan(item_id):
    """Components of the first major item, in the order to buy them.
    Rule of thumb used by most guides: on your first back buy the most expensive component you can afford
    (it carries the most stats per back), and build the cheap basic pieces into it later. So: components
    sorted by cost, highest first, each with its own sub-pieces for when you can't afford the whole thing."""
    it = GD.item(item_id)
    comps = []
    for cid in it["from"]:
        c = GD.item(cid)
        subs = [item_view(s) for s in c["from"]]
        comps.append({**item_view(cid), "subparts": subs,
                      "combine_cost": max(0, c["gold"] - sum(GD.item(s)["gold"] for s in c["from"]))})
    comps.sort(key=lambda c: c["gold"], reverse=True)
    recipe_cost = max(0, it["gold"] - sum(GD.item(c)["gold"] for c in it["from"]))
    return {"item": item_view(item_id), "components": comps, "recipe_cost": recipe_cost}


def rune_view(runes, shards):
    def perk(pid):
        p = GD.perks.get(pid)
        return {"id": pid, "name": p["name"] if p else f"Rune {pid}", "icon": p["icon"] if p else None}

    prim = [perk(p) for p in runes["perks"] if GD.perks.get(p, {}).get("tree") == runes["primary"]]
    sub = [perk(p) for p in runes["perks"] if GD.perks.get(p, {}).get("tree") == runes["sub"]]
    unknown = [perk(p) for p in runes["perks"] if p not in GD.perks]
    prim.sort(key=lambda p: GD.perks.get(p["id"], {}).get("slot", 9))
    sub.sort(key=lambda p: GD.perks.get(p["id"], {}).get("slot", 9))
    tree = lambda t: {"id": t, "name": GD.trees.get(t, {}).get("name", f"Tree {t}"), "icon": GD.trees.get(t, {}).get("icon")}  # noqa: E731
    view = {"primary_tree": tree(runes["primary"]), "sub_tree": tree(runes["sub"]),
            "keystone": prim[0] if prim else None, "primary": prim[1:], "secondary": sub + unknown,
            "games": runes["games"], "winrate": _wr(runes["wins"], runes["games"])}
    if view["keystone"]:
        view["keystone"]["desc"] = GD.perks.get(view["keystone"]["id"], {}).get("desc", "")
    # Full trees so the page can show every rune, with the chosen ones lit up.
    chosen = set(runes["perks"])

    def slots(t, skip_keystones=False):
        rows = GD.trees.get(t, {}).get("slots", [])
        rows = rows[1:] if skip_keystones else rows
        return [[{**perk(pid), "on": pid in chosen} for pid in row] for row in rows]
    view["primary_slots"] = slots(runes["primary"])
    view["sub_slots"] = slots(runes["sub"], skip_keystones=True)
    if shards:
        view["shards"] = [{"id": s, "name": SHARDS.get(s, (f"Shard {s}", None))[0],
                           "icon": SHARDS.get(s, (None, None))[1]} for s in shards["ids"]]
        view["shard_rows"] = []
        for n, row in enumerate(SHARD_ROWS):
            pick = shards["ids"][n] if n < len(shards["ids"]) else None
            if pick is not None and pick not in row:
                row = row + [pick]
            view["shard_rows"].append([{"id": x, "name": SHARDS.get(x, (f"Shard {x}", None))[0],
                                        "icon": SHARDS.get(x, (None, None))[1], "on": x == pick} for x in row])
    return view


def build_result(champ_key, role_id, region_id, patch_id):
    GD.ensure()
    champ = GD.champions.get(champ_key)
    if not champ:
        return {"error": "Unknown champion."}
    role = ROLE_BY_ID.get(role_id)
    if not role:
        return {"error": "Unknown role."}
    region = SETTINGS["regions"].get(region_id)
    if not region:
        return {"error": "Unknown region."}
    patch = next((p for p in GD.patches if p["id"] == patch_id), None)
    if not patch:
        return {"error": f"Patch {patch_id} isn't one of the two latest patches."}

    try:
        raw = ugg_overview(champ_key, patch_id)
    except FetchError as e:
        if e.status in (403, 404):
            return {"error": f"No {SETTINGS['rank_label']} stats file for {champ['name']} on patch {patch['label']}"
                             f" (the stats site returned {e.status}). A brand-new patch or champion takes a day or"
                             f" two to fill in, so try the previous patch. If every search shows this, the stats"
                             f" site may be blocking the app; see README troubleshooting.", "detail": str(e)}
        return {"error": "Couldn't download build stats. Check your internet connection and try again.",
                "detail": str(e)}

    block = find_role_block(raw, region["key"], role["ugg"])
    if not block:
        # Tell the user which roles DO have data for this champ in this region
        others = [r["label"] for r in ROLES if r["id"] != role_id and find_role_block(raw, region["key"], r["ugg"])]
        msg = f"No {SETTINGS['rank_label']} games of {champ['name']} {role['label']} in {region['label']} on patch {patch['label']}."
        if others:
            msg += f" Data exists for: {', '.join(others)}."
        if region_id != "any":
            msg += " Try region 'Any' for a bigger sample."
        return {"error": msg}

    ov = parse_overview(block)
    rank_check = rank_sanity(raw, region["key"], role["ugg"], ov)
    res = {
        "champion": champ, "role": role["label"], "region": region["label"], "patch": patch["label"],
        "rank": SETTINGS["rank_label"], "ddragon": GD.version, "warnings": ov["warnings"],
        "source_url": f"https://u.gg/lol/champions/{champ['id'].lower()}/build/{role_id}"
                      f"?rank={SETTINGS['ugg_rank_name']}&region={region['name']}&patch={patch_id}",
    }
    if rank_check:
        res["warnings"].append(rank_check)
    games = ov.get("total", {}).get("games") or 0
    res["games"] = int(games or ov.get("runes", {}).get("games") or 0)
    if ov.get("total"):
        res["winrate"] = _wr(ov["total"]["wins"], ov["total"]["games"])
    if res["games"] and res["games"] < SETTINGS["low_sample_games"]:
        res["warnings"].append(f"Small sample ({res['games']} games). Treat this build with caution, "
                               f"or switch region to 'Any' / the other patch.")
    res["rule"] = {"min_winrate": SETTINGS["min_winrate"], "min_share": round(SETTINGS["min_pick_share"] * 100),
                   "min_games": SETTINGS["min_build_games"]}
    if not games:
        res["warnings"].append("The stats file doesn't say how many games this champion played, so pick share "
                               "can't be checked; only the win rate rule is applied.")

    def chk(sec, base=games):
        return check_rule(sec["games"], sec["wins"], base)

    if "runes" in ov:
        res["runes"] = {**rune_view(ov["runes"], ov.get("shards")), **chk(ov["runes"])}
    if "spells" in ov:
        res["spells"] = [{"name": GD.spells.get(s, {}).get("name", f"Spell {s}"),
                          "image": GD.spells.get(s, {}).get("image")} for s in ov["spells"]["ids"]]
        res["spells_rule"] = chk(ov["spells"])
    if "skills" in ov:
        res["skills"] = {**ov["skills"], **chk(ov["skills"])}
    if "starting" in ov:
        res["starting"] = {"items": [item_view(i) for i in ov["starting"]["ids"]], **chk(ov["starting"])}

    # Full build in purchase order.
    # Items 1-3: u.gg's core path (the first three completed items, in the order bought), checked against the rule
    #   as a share of ALL the champion's games.
    # Items 4-6: in each slot, the most-bought item that passes the rule. Share there is out of the games that
    #   reached that slot (most games end before a 5th or 6th item, so "% of all games" would rule everything out).
    # ---- Main build: the 3 core items + boots. Henry's rule is applied to this core.
    core_ids = list(ov.get("core", {}).get("ids", []))
    core_ok = True
    if "core" in ov:
        res["core"] = chk(ov["core"])
        core_ok = res["core"]["passes"]
    res["fallback"] = not core_ok

    late_totals = {}   # item id -> {"games", "wins"} summed over item slots 4-6
    for opts in ov.get("late", []):
        for o in opts:
            t = late_totals.setdefault(o["id"], {"games": 0, "wins": 0})
            t["games"] += o["games"]
            t["wins"] += o["wins"]

    legendaries = [i for i in core_ids if not is_boots(i)]
    core_boots = next((i for i in core_ids if is_boots(i)), None)
    filled = []
    # u.gg counts boots as one of the first 3 items; if so, add the most common next item to make 3 real items.
    for opts in ov.get("late", []):
        if len(legendaries) >= 3:
            break
        nxt = next((o for o in opts if o["id"] not in legendaries and not is_boots(o["id"])), None)
        if nxt:
            legendaries.append(nxt["id"])
            filled.append(nxt["id"])
    res["build"] = [{**item_view(i), "slot": n + 1, "filled": i in filled} for n, i in enumerate(legendaries[:3])]

    boot_counts = {i: t["games"] for i, t in late_totals.items() if is_boots(i)}
    if core_boots:
        boot_counts[core_boots] = boot_counts.get(core_boots, 0) + 10 ** 9  # the core path's boots come first
    boot_opts = sorted(boot_counts, key=boot_counts.get, reverse=True)
    if boot_opts:
        res["boots"] = {"base": item_view(1001), "options": [item_view(i) for i in boot_opts[:5]],
                        "in_core": bool(core_boots),
                        "after_item": (core_ids.index(core_boots) if core_boots else 1)}
    elif champ["id"] != "Cassiopeia":
        res["warnings"].append(f"No boots show up in this champion's {SETTINGS['rank_label']} builds.")

    if res["build"]:
        res["first_item"] = first_item_plan(res["build"][0]["id"])

    # ---- Situational items for the rest of the game, by enemy type
    res["situational"] = situational(late_totals, set(legendaries) | set(boot_opts), legendaries)
    return res


# Situational categories. Items are sorted into them by what they do (Riot's item text and tags), using the
# champion's own late items first, then well-known picks for the champion's build type.
SITUATIONS = [
    {"id": "heal", "label": "vs Healing & Shields",
     "why": "Enemies who heal or shield a lot (Soraka, Aatrox, Vladimir, Yuumi, lots of lifesteal). Grievous Wounds cuts it."},
    {"id": "tank", "label": "vs Tanks",
     "why": "Two or more tanky enemies stacking health, armor or magic resist. Penetration and max-health damage."},
    {"id": "burst", "label": "vs Burst & Assassins",
     "why": "Enemies who can kill you in one combo (Zed, Kha'Zix, Syndra, LeBlanc). Survival items buy you time."},
]
FALLBACK_PICKS = {
    "ap": {"heal": ["Morellonomicon", "Chemtech Putrifier"],
           "tank": ["Void Staff", "Liandry's Torment", "Cryptbloom", "Riftmaker"],
           "burst": ["Zhonya's Hourglass", "Banshee's Veil"]},
    "ad": {"heal": ["Mortal Reminder", "Chempunk Chainsword", "Serpent's Fang"],
           "tank": ["Lord Dominik's Regards", "Black Cleaver", "Blade of the Ruined King", "Serylda's Grudge", "Terminus"],
           "burst": ["Guardian Angel", "Maw of Malmortius", "Death's Dance", "Sterak's Gage", "Edge of Night"]},
    "tank": {"heal": ["Thornmail"],
             "tank": ["Jak'Sho, The Protean", "Black Cleaver", "Abyssal Mask"],
             "burst": ["Randuin's Omen", "Force of Nature", "Kaenic Rookern", "Frozen Heart", "Dead Man's Plate"]},
}
ANTI_TANK_WORDS = ("armor penetration", "magic penetration", "max health damage", "maximum health damage",
                   "% max health", "% maximum health", "shred", "reduce their armor", "reduces armor")
ANTI_BURST_WORDS = ("stasis", "revive", "lifeline", "spell shield", "spellshield", "removes all crowd control",
                    "untargetable")


def is_boots(iid):
    it = GD.item(iid)
    return "Boots" in it["tags"] or it["id"] in BOOT_IDS


def build_type(item_ids):
    ap = ad = tank = 0.0
    for i in item_ids:
        st = GD.item(i)["stats"]
        ap += st.get("FlatMagicDamageMod", 0)
        ad += st.get("FlatPhysicalDamageMod", 0) * 1.6  # AD numbers are smaller than AP numbers
        tank += st.get("FlatHPPoolMod", 0) / 10 + st.get("FlatArmorMod", 0) + st.get("FlatSpellBlockMod", 0)
    if tank > max(ap, ad) * 1.5 or (ap == 0 and ad == 0 and tank > 0):
        return "tank"
    return "ap" if ap >= ad else "ad"


def item_category(iid, kind):
    it = GD.item(iid)
    d, tags = it["desc"], it["tags"]
    for cat, names in FALLBACK_PICKS.get(kind, {}).items():
        if any(_norm(n) == _norm(it["name"]) for n in names):
            return cat
    if "grievous wounds" in d:
        return "heal"
    if "ArmorPenetration" in tags or "MagicPenetration" in tags or any(w in d for w in ANTI_TANK_WORDS):
        return "tank"
    if any(w in d for w in ANTI_BURST_WORDS):
        return "burst"
    if kind == "tank" and ("Armor" in tags or "SpellBlock" in tags):
        return "burst"
    return None


def situational(late_totals, exclude, core_items):
    kind = build_type(core_items)
    groups = {s["id"]: [] for s in SITUATIONS}
    for iid, t in sorted(late_totals.items(), key=lambda kv: kv[1]["games"], reverse=True):
        if iid in exclude or not GD.item(iid)["from"] or t["games"] < SETTINGS["min_situational_games"]:
            continue  # skip core items, boots, basic components, and picks with too few games
        cat = item_category(iid, kind)
        if cat and len(groups[cat]) < 3:
            groups[cat].append({**item_view(iid, t["games"], t["wins"]), "source": "stats"})
    for cat, picks in groups.items():
        for name in FALLBACK_PICKS[kind][cat]:
            if len(picks) >= 2:
                break
            it = GD.by_name(name)
            if it and it["id"] not in exclude and all(p["id"] != it["id"] for p in picks):
                picks.append({**item_view(it["id"]), "source": "suggested"})
    return {"build_type": kind,
            "groups": [{**s, "items": groups[s["id"]]} for s in SITUATIONS]}


def check_rule(games, wins, base_games, min_games=None):
    """Henry's rule: win rate above min_winrate AND at least min_pick_share of the games AND enough games."""
    if min_games is None:
        min_games = SETTINGS["min_build_games"]
    wr = _wr(wins, games)
    share = (games / base_games) if base_games else None
    reasons = []
    if wr is None or wr <= SETTINGS["min_winrate"]:
        reasons.append(f"win rate {wr}% is not above {SETTINGS['min_winrate']}%")
    if games < min_games:
        reasons.append(f"only {int(games)} games (needs {min_games})")
    if share is not None and share < SETTINGS["min_pick_share"]:
        reasons.append(f"only {share * 100:.0f}% of games (needs {SETTINGS['min_pick_share'] * 100:.0f}%)")
    return {"games": int(games), "winrate": wr, "share": round(share * 100, 1) if share is not None else None,
            "passes": not reasons, "fail_reasons": reasons}


# --------------------------------------------------------------------------------------
# Web server
# --------------------------------------------------------------------------------------

def meta():
    GD.ensure()
    champs = sorted(GD.champions.values(), key=lambda c: c["name"])
    roles_by_champ, note = {}, None
    try:
        pr = ugg_role_pickrates(GD.patches[0]["id"])
        if not any(pr.values()) and len(GD.patches) > 1:
            pr = ugg_role_pickrates(GD.patches[1]["id"])
        thr = SETTINGS["role_min_pick_rate"]
        for role_id, shares in pr.items():
            for k, share in shares.items():
                if share >= thr:
                    roles_by_champ.setdefault(k, []).append(role_id)
    except Exception as e:  # noqa: BLE001
        note = "Couldn't load role stats, so every champion is listed under every role."
        log(f"Role filter unavailable: {e}")
    return {
        "version": GD.version,
        "patches": GD.patches,
        "roles": [{"id": r["id"], "label": r["label"]} for r in ROLES],
        "regions": [{"id": k, "label": v["label"]} for k, v in SETTINGS["regions"].items()],
        "champions": [{**c, "roles": roles_by_champ.get(c["key"], [])} for c in champs],
        "role_filter": bool(roles_by_champ),
        "note": note,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html")
            if u.path == "/logo.png":
                with open(os.path.join(STATIC_DIR, "logo.png"), "rb") as f:
                    return self._send(200, f.read(), "image/png")
            if u.path == "/favicon.ico":
                with open(os.path.join(RES_DIR, "icon.ico"), "rb") as f:
                    return self._send(200, f.read(), "image/x-icon")
            if u.path == "/api/ping":
                global LAST_PING
                LAST_PING = time.time()
                return self._send(200, {"ok": True, "app": "league-build-finder"})
            if u.path == "/api/meta":
                return self._send(200, meta())
            if u.path == "/api/build":
                t = time.time()
                res = build_result(q.get("champion", ""), q.get("role", ""), q.get("region", "any"),
                                   q.get("patch", ""))
                log(f"Search {q} -> {'error: ' + res['error'] if 'error' in res else 'ok'} "
                    f"({time.time() - t:.1f}s)")
                return self._send(200, res)
            return self._send(404, {"error": "not found"})
        except FetchError as e:
            log(f"Download error: {e}")
            return self._send(200, {"error": "Couldn't reach Riot's or u.gg's servers. Check your internet "
                                             "connection and try again.", "detail": str(e)})
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            return self._send(200, {"error": f"Something went wrong: {type(e).__name__}: {e}",
                                    "detail": "See the black app window for the full error."})


def main():
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("--port", type=int, default=SETTINGS["port"])
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    log("Loading champion and item data from Riot (first run downloads ~3 MB)...")
    try:
        GD.ensure()
    except Exception as e:  # noqa: BLE001
        log(f"Couldn't load Riot data yet ({e}). The page will retry when you open it.")

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        log(f"Port {args.port} is busy. Is the app already open? Otherwise run: py app.py --port {args.port + 1}")
        sys.exit(1)
    url = f"http://localhost:{args.port}"
    log(f"Ready: {url}  (keep this window open; close it to stop the app)")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
