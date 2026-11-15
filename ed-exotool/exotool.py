#!/usr/bin/env python3
"""
ED ExoTool - tracks exobiology samples from the Elite Dangerous journal and
shows them on a small web dashboard (for example on a tablet in your LAN).

Only Python's standard library is used, so there is nothing to install.

Start:    python3 exotool.py
Options:  python3 exotool.py --help

Where things live (kept apart from the program on purpose, so it can later be
packed into a read-only AppImage without changes):
  database: ~/.local/share/ed-exotool/exotool.db   (SQLite, safe to delete)
  settings: ~/.config/ed-exotool/config.json
"""

import argparse
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "ed-exotool"
APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"


def xdg_dir(env_var, fallback):
    return Path(os.environ.get(env_var) or (Path.home() / fallback))


DEFAULT_DATA_DIR = xdg_dir("XDG_DATA_HOME", ".local/share") / APP_NAME
DEFAULT_CONFIG_DIR = xdg_dir("XDG_CONFIG_HOME", ".config") / APP_NAME

DEFAULT_CONFIG = {
    "_help": "journal_dir: leave empty to auto-detect. port: web dashboard port. "
             "assume_first_footfall: add the first footfall bonus to all estimates.",
    "journal_dir": "",
    "port": 8765,
    "assume_first_footfall": True,
    "footfall_multiplier": 5,
}

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
# Base payouts per species (credits, without first footfall bonus).
# These are community figures and only used until you sell a species once:
# every sale writes the real value into the table learned_values, which then
# takes priority.
SPECIES_VALUES = {
    "Aleoida Arcus": 7252500, "Aleoida Coronamus": 6284600, "Aleoida Gravis": 12934900,
    "Aleoida Laminiae": 3385200, "Aleoida Spica": 3385200,
    "Bacterium Acies": 1000000, "Bacterium Alcyoneum": 1658500, "Bacterium Aurasus": 1000000,
    "Bacterium Bullaris": 1152500, "Bacterium Cerbrus": 1689800, "Bacterium Informem": 8418000,
    "Bacterium Nebulus": 5289900, "Bacterium Omentum": 4638900, "Bacterium Scopulum": 4934500,
    "Bacterium Tela": 1949000, "Bacterium Verrata": 3897000, "Bacterium Vesicula": 1000000,
    "Bacterium Volu": 7774700,
    "Cactoida Cortexum": 3667600, "Cactoida Lapis": 2483600, "Cactoida Peperatis": 2483600,
    "Cactoida Pullulanta": 3667600, "Cactoida Vermis": 16202800,
    "Clypeus Lacrimam": 8418000, "Clypeus Margaritus": 11873200, "Clypeus Speculumi": 16202800,
    "Concha Aureolas": 7774700, "Concha Biconcavis": 16777600, "Concha Labiata": 2352400,
    "Concha Renibus": 4572400,
    "Electricae Pluma": 6284600, "Electricae Radialem": 6284600,
    "Fonticulua Campestris": 1000000, "Fonticulua Digitos": 1804100, "Fonticulua Fluctus": 20000000,
    "Fonticulua Lapida": 3111000, "Fonticulua Segmentatus": 19010800, "Fonticulua Upupam": 5727600,
    "Frutexa Acus": 7774700, "Frutexa Collum": 1639800, "Frutexa Fera": 1632500,
    "Frutexa Flabellum": 1808900, "Frutexa Flammasis": 10326000, "Frutexa Metallicum": 1632500,
    "Frutexa Sponsae": 5988000,
    "Fumerola Aquatis": 6284600, "Fumerola Carbosis": 6284600, "Fumerola Extremus": 16202800,
    "Fumerola Nitris": 7500900,
    "Fungoida Bullarum": 3703200, "Fungoida Gelata": 3330300, "Fungoida Setisis": 1670100,
    "Fungoida Stabitis": 2680300,
    "Osseus Cornibus": 1483000, "Osseus Discus": 12934900, "Osseus Fractus": 4027800,
    "Osseus Pellebantus": 9739000, "Osseus Pumice": 3156300, "Osseus Spiralis": 2404700,
    "Recepta Conditivus": 14313700, "Recepta Deltahedronix": 16202800, "Recepta Umbrux": 12934900,
    "Stratum Araneamus": 2448900, "Stratum Cucumisis": 16202800, "Stratum Excutitus": 2448900,
    "Stratum Frigus": 2637500, "Stratum Laminamus": 2788300, "Stratum Limaxus": 1362000,
    "Stratum Paleas": 1362000, "Stratum Tectonicas": 19010800,
    "Tubus Cavas": 11873200, "Tubus Compagibus": 7774700, "Tubus Conifer": 2415500,
    "Tubus Rosarium": 2637500, "Tubus Sororibus": 5727600,
    "Tussock Albata": 3252500, "Tussock Capillum": 7025800, "Tussock Caputus": 3472400,
    "Tussock Catena": 1766600, "Tussock Cultro": 1766600, "Tussock Divisa": 1766600,
    "Tussock Ignis": 1849000, "Tussock Pennata": 5853800, "Tussock Pennatis": 1000000,
    "Tussock Propagito": 1000000, "Tussock Serrati": 4447100, "Tussock Stigmasis": 19010800,
    "Tussock Triticum": 7774700, "Tussock Ventusa": 3277700, "Tussock Virgam": 14313700,
}
SPECIES_VALUES_LC = {k.lower(): v for k, v in SPECIES_VALUES.items()}

# Minimum distance (metres) between two samples of the same genus.
COLONY_DISTANCE = {
    "Aleoida": 150, "Bacterium": 500, "Cactoida": 300, "Clypeus": 150, "Concha": 150,
    "Electricae": 1000, "Fonticulua": 500, "Frutexa": 150, "Fumerola": 100, "Fungoida": 300,
    "Osseus": 800, "Recepta": 150, "Stratum": 500, "Tubus": 800, "Tussock": 200,
}


def genus_max_value(genus_name):
    """Highest base value of any species in a genus ('up to ...')."""
    if not genus_name:
        return None
    prefix = genus_name.lower() + " "
    values = [v for k, v in SPECIES_VALUES_LC.items() if k.startswith(prefix)]
    return max(values) if values else None


def genus_from_id(genus_id):
    """'$Codex_Ent_Stratum_Genus_Name;' -> 'Stratum' (fallback only)."""
    m = re.search(r"Codex_Ent_(\w+?)_Genus", genus_id or "")
    return m.group(1) if m else genus_id


# ---------------------------------------------------------------------------
# Settings and journal location
# ---------------------------------------------------------------------------
def load_config(config_dir):
    path = config_dir / "config.json"
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:
            print(f"! Could not read {path}: {e} - using defaults.")
    else:
        config_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    return cfg


JOURNAL_SUBPATH = Path(
    "steamapps/compatdata/359320/pfx/drive_c/users/steamuser/"
    "Saved Games/Frontier Developments/Elite Dangerous"
)
STEAM_ROOTS = [
    Path.home() / ".local/share/Steam",
    Path.home() / ".steam/steam",
    Path.home() / ".steam/root",
    Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",  # Flatpak Steam
    Path.home() / ".var/app/com.valvesoftware.Steam/data/Steam",
]


def steam_libraries():
    """Steam root folders plus extra library folders (e.g. on a second drive)."""
    found = []
    for root in STEAM_ROOTS:
        if not root.is_dir():
            continue
        found.append(root)
        vdf = root / "steamapps/libraryfolders.vdf"
        try:
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                found.append(Path(m.group(1)))
        except OSError:
            pass
    unique, seen = [], set()
    for p in found:
        key = p.resolve() if p.exists() else p
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def find_journal_dir(configured):
    if configured:
        p = Path(configured).expanduser()
        return p if p.is_dir() else None
    best, best_mtime = None, -1.0
    for lib in steam_libraries():
        cand = lib / JOURNAL_SUBPATH
        if not cand.is_dir():
            continue
        mtime = max((f.stat().st_mtime for f in cand.glob("Journal.*.log")), default=0.0)
        if mtime > best_mtime:
            best, best_mtime = cand, mtime
    return best


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS files (          -- how far each journal file has been read
    name   TEXT PRIMARY KEY,
    offset INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (             -- current position, commander, scan in progress
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS systems (
    address    INTEGER PRIMARY KEY,
    name       TEXT,
    x REAL, y REAL, z REAL,
    last_visit TEXT
);
CREATE TABLE IF NOT EXISTS bodies (
    system_address INTEGER NOT NULL,
    body_id        INTEGER NOT NULL,
    name           TEXT,
    planet_class   TEXT,
    atmosphere     TEXT,
    gravity        REAL,                    -- m/s²
    temperature    REAL,                    -- K
    distance_ls    REAL,
    landable       INTEGER,
    was_discovered INTEGER,
    was_mapped     INTEGER,
    was_footfalled INTEGER,
    bio_signals    INTEGER,
    genuses        TEXT,                    -- JSON list of genus names (after surface scan)
    PRIMARY KEY (system_address, body_id)
);
CREATE TABLE IF NOT EXISTS scans (          -- every single ScanOrganic event, raw history
    id             INTEGER PRIMARY KEY,
    ts             TEXT,
    system_address INTEGER,
    body_id        INTEGER,
    scan_type      TEXT,                    -- Log / Sample / Analyse
    species        TEXT,
    species_name   TEXT,
    variant_name   TEXT
);
CREATE TABLE IF NOT EXISTS samples (        -- completed samples (third scan done)
    id             INTEGER PRIMARY KEY,
    ts             TEXT,
    system_address INTEGER,
    body_id        INTEGER,
    genus          TEXT,
    genus_name     TEXT,
    species        TEXT,
    species_name   TEXT,
    variant_name   TEXT,
    status         TEXT NOT NULL DEFAULT 'unsold',   -- unsold / sold / lost
    status_ts      TEXT,
    sold_value     INTEGER,
    death_id       INTEGER
);
CREATE TABLE IF NOT EXISTS deaths (
    id             INTEGER PRIMARY KEY,
    ts             TEXT,
    system_address INTEGER,
    system_name    TEXT,
    body_name      TEXT
);
CREATE TABLE IF NOT EXISTS learned_values ( -- real base values seen at Vista Genomics
    species      TEXT PRIMARY KEY,
    species_name TEXT,
    value        INTEGER,
    ts           TEXT
);
CREATE INDEX IF NOT EXISTS ix_samples_status ON samples(status);
CREATE INDEX IF NOT EXISTS ix_samples_body ON samples(system_address, body_id);
"""


def open_db(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


# ---------------------------------------------------------------------------
# Journal event handling
# ---------------------------------------------------------------------------
class Processor:
    """Turns journal events into rows. One method per event: on_<EventName>."""

    def __init__(self, db):
        self.db = db

    # small key/value store
    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)", (key, json.dumps(value)))

    def handle(self, ev):
        handler = getattr(self, "on_" + str(ev.get("event")), None)
        if handler:
            handler(ev)
            self.set("last_event_ts", ev.get("timestamp"))

    # helpers
    def upsert_system(self, ev):
        sa = ev.get("SystemAddress")
        if sa is None:
            return
        pos = ev.get("StarPos") or [None, None, None]
        self.db.execute("INSERT OR IGNORE INTO systems(address) VALUES(?)", (sa,))
        self.db.execute(
            "UPDATE systems SET name=COALESCE(?, name), x=COALESCE(?, x), y=COALESCE(?, y), "
            "z=COALESCE(?, z), last_visit=? WHERE address=?",
            (ev.get("StarSystem"), pos[0], pos[1], pos[2], ev.get("timestamp"), sa),
        )
        self.set("system", {"address": sa, "name": ev.get("StarSystem")})

    def upsert_body(self, sa, body_id, **fields):
        if sa is None or body_id is None:
            return
        self.db.execute("INSERT OR IGNORE INTO bodies(system_address, body_id) VALUES(?, ?)", (sa, body_id))
        fields = {k: v for k, v in fields.items() if v is not None}
        if fields:
            assignments = ", ".join(f"{k}=?" for k in fields)
            self.db.execute(
                f"UPDATE bodies SET {assignments} WHERE system_address=? AND body_id=?",
                (*fields.values(), sa, body_id),
            )

    def set_body(self, sa, body_id, name):
        if body_id is None:
            self.set("body", None)
            return
        self.upsert_body(sa, body_id, name=name)
        self.set("body", {"system_address": sa, "body_id": body_id, "name": name})

    @staticmethod
    def bio_count(signals):
        for s in signals or []:
            if "Biological" in (s.get("Type") or ""):
                return s.get("Count")
        return None

    # commander
    def on_Commander(self, ev):
        self.set("cmdr", ev.get("Name"))

    def on_LoadGame(self, ev):
        self.set("cmdr", ev.get("Commander"))

    # position
    def on_Location(self, ev):
        self.upsert_system(ev)
        if ev.get("BodyType") == "Planet":
            self.set_body(ev.get("SystemAddress"), ev.get("BodyID"), ev.get("Body"))
        else:
            self.set("body", None)

    on_FSDJump = on_Location
    on_CarrierJump = on_Location

    def on_SupercruiseExit(self, ev):
        if ev.get("BodyType") == "Planet":
            self.set_body(ev.get("SystemAddress"), ev.get("BodyID"), ev.get("Body"))

    def on_ApproachBody(self, ev):
        self.set_body(ev.get("SystemAddress"), ev.get("BodyID"), ev.get("Body"))

    on_Touchdown = on_ApproachBody
    on_Liftoff = on_ApproachBody

    def on_Disembark(self, ev):
        if ev.get("OnPlanet"):
            self.set_body(ev.get("SystemAddress"), ev.get("BodyID"), ev.get("Body"))

    def on_LeaveBody(self, ev):
        self.set("body", None)

    # bodies and signals
    def on_Scan(self, ev):
        if "PlanetClass" not in ev:
            return  # stars, belts: not interesting here
        self.upsert_body(
            ev.get("SystemAddress"), ev.get("BodyID"),
            name=ev.get("BodyName"), planet_class=ev.get("PlanetClass"),
            atmosphere=ev.get("Atmosphere") or None, gravity=ev.get("SurfaceGravity"),
            temperature=ev.get("SurfaceTemperature"), distance_ls=ev.get("DistanceFromArrivalLS"),
            landable=ev.get("Landable"), was_discovered=ev.get("WasDiscovered"),
            was_mapped=ev.get("WasMapped"), was_footfalled=ev.get("WasFootfalled"),
        )

    def on_FSSBodySignals(self, ev):
        self.upsert_body(ev.get("SystemAddress"), ev.get("BodyID"),
                         name=ev.get("BodyName"), bio_signals=self.bio_count(ev.get("Signals")))

    def on_SAASignalsFound(self, ev):
        genuses = [g.get("Genus_Localised") or genus_from_id(g.get("Genus")) for g in ev.get("Genuses") or []]
        self.upsert_body(ev.get("SystemAddress"), ev.get("BodyID"),
                         name=ev.get("BodyName"), bio_signals=self.bio_count(ev.get("Signals")),
                         genuses=json.dumps(genuses) if genuses else None)

    # exobiology
    def on_ScanOrganic(self, ev):
        scan_type = ev.get("ScanType")
        sa, body_id = ev.get("SystemAddress"), ev.get("Body")
        info = {
            "system_address": sa,
            "body_id": body_id,
            "genus": ev.get("Genus"),
            "genus_name": ev.get("Genus_Localised") or genus_from_id(ev.get("Genus")),
            "species": ev.get("Species"),
            "species_name": ev.get("Species_Localised") or ev.get("Species"),
            "variant_name": ev.get("Variant_Localised"),
        }
        self.db.execute(
            "INSERT INTO scans(ts, system_address, body_id, scan_type, species, species_name, variant_name) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (ev.get("timestamp"), sa, body_id, scan_type, info["species"], info["species_name"], info["variant_name"]),
        )
        self.upsert_body(sa, body_id)

        if scan_type == "Analyse":
            self.db.execute(
                "INSERT INTO samples(ts, system_address, body_id, genus, genus_name, species, species_name, variant_name) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (ev.get("timestamp"), sa, body_id, info["genus"], info["genus_name"],
                 info["species"], info["species_name"], info["variant_name"]),
            )
            self.set("in_progress", None)
            return

        current = self.get("in_progress")
        same = bool(current) and current.get("species") == info["species"] \
            and current.get("body_id") == body_id and current.get("system_address") == sa
        if scan_type == "Log":
            step = 1
        else:
            step = min(current["step"] + 1, 3) if same else 2
        self.set("in_progress", {**info, "step": step, "ts": ev.get("timestamp")})

    def on_SellOrganicData(self, ev):
        ts = ev.get("timestamp")
        for item in ev.get("BioData") or []:
            species = item.get("Species")
            value = item.get("Value") or 0
            bonus = item.get("Bonus") or 0
            row = self.db.execute(
                "SELECT id FROM samples WHERE status='unsold' AND species=? ORDER BY ts LIMIT 1", (species,)
            ).fetchone()
            if row:
                self.db.execute("UPDATE samples SET status='sold', status_ts=?, sold_value=? WHERE id=?",
                                (ts, value + bonus, row["id"]))
            if value:
                self.db.execute(
                    "INSERT OR REPLACE INTO learned_values(species, species_name, value, ts) VALUES(?, ?, ?, ?)",
                    (species, item.get("Species_Localised"), value, ts),
                )

    def on_Died(self, ev):
        ts = ev.get("timestamp")
        system = self.get("system") or {}
        body = self.get("body") or {}
        cur = self.db.execute(
            "INSERT INTO deaths(ts, system_address, system_name, body_name) VALUES(?, ?, ?, ?)",
            (ts, system.get("address"), system.get("name"), body.get("name")),
        )
        self.db.execute("UPDATE samples SET status='lost', status_ts=?, death_id=? WHERE status='unsold'",
                        (ts, cur.lastrowid))
        self.set("in_progress", None)


RELEVANT_EVENTS = {name[3:] for name in dir(Processor) if name.startswith("on_")}
EVENT_RE = re.compile(rb'"event"\s*:\s*"([A-Za-z]+)"')
NEW_NAME_RE = re.compile(r"Journal\.(\d{4})-(\d{2})-(\d{2})T(\d{6})\.(\d+)\.log$")
OLD_NAME_RE = re.compile(r"Journal\.(\d{2})(\d{4})(\d{6})\.(\d+)\.log$")


def journal_sort_key(path):
    """Chronological order for both journal file name formats."""
    m = NEW_NAME_RE.match(path.name)
    if m:
        return (f"{m[1]}{m[2]}{m[3]}{m[4]}", int(m[5]))
    m = OLD_NAME_RE.match(path.name)
    if m:
        return (f"20{m[1]}{m[2]}{m[3]}", int(m[4]))
    return (time.strftime("%Y%m%d%H%M%S", time.gmtime(path.stat().st_mtime)), 0)


class JournalWatcher:
    def __init__(self, journal_dir, db, lock):
        self.journal_dir = journal_dir
        self.db = db
        self.lock = lock
        self.proc = Processor(db)
        self.offsets = {r["name"]: r["offset"] for r in db.execute("SELECT name, offset FROM files")}

    def pending_files(self):
        result = []
        for f in sorted(self.journal_dir.glob("Journal.*.log"), key=journal_sort_key):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size != self.offsets.get(f.name, 0):
                result.append(f)
        return result

    def read_file(self, path):
        offset = self.offsets.get(path.name, 0)
        with open(path, "rb") as fh:
            if fh.seek(0, os.SEEK_END) < offset:
                offset = 0  # file was replaced, read it again
            fh.seek(offset)
            data = fh.read()
        end = data.rfind(b"\n")
        if end < 0:
            return 0  # no complete line yet
        handled = 0
        with self.lock:
            for line in data[: end + 1].splitlines():
                m = EVENT_RE.search(line)
                if not m or m.group(1).decode() not in RELEVANT_EVENTS:
                    continue  # cheap pre-filter: skip json parsing for uninteresting events
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                self.proc.handle(ev)
                handled += 1
            new_offset = offset + end + 1
            self.db.execute("INSERT OR REPLACE INTO files(name, offset) VALUES(?, ?)", (path.name, new_offset))
            self.db.commit()
        self.offsets[path.name] = new_offset
        return handled

    def catch_up(self, verbose=False):
        files = self.pending_files()
        handled = 0
        for i, f in enumerate(files, 1):
            handled += self.read_file(f)
            if verbose and len(files) > 20 and (i % 50 == 0 or i == len(files)):
                print(f"  {i}/{len(files)} journal files read")
        return handled


# ---------------------------------------------------------------------------
# Dashboard data
# ---------------------------------------------------------------------------
def short_body_name(body_name, system_name):
    if body_name and system_name and body_name.startswith(system_name + " "):
        return body_name[len(system_name) + 1:]
    return body_name


def build_state(app):
    db = app.db
    kv = Processor(db)
    multiplier = app.cfg.get("footfall_multiplier", 5) if app.cfg.get("assume_first_footfall", True) else 1
    learned = {r["species"]: r["value"] for r in db.execute("SELECT species, value FROM learned_values")}

    def base_value(species, species_name):
        if species in learned:
            return learned[species]
        return SPECIES_VALUES_LC.get((species_name or "").lower().strip())

    def estimate(species, species_name):
        b = base_value(species, species_name)
        return b * multiplier if b else None

    def sample_dict(r):
        return {
            "species_name": r["species_name"],
            "variant_name": r["variant_name"],
            "genus_name": r["genus_name"],
            "status": r["status"],
            "ts": r["ts"],
            "base_value": base_value(r["species"], r["species_name"]),
            "value": r["sold_value"] if r["status"] == "sold" and r["sold_value"] else estimate(r["species"], r["species_name"]),
        }

    system = kv.get("system") or {}
    body = kv.get("body") or {}
    system_name = system.get("name")

    # bodies with biology in the current system
    bodies = []
    if system.get("address") is not None:
        rows = db.execute(
            """SELECT * FROM bodies b
               WHERE b.system_address = ?
                 AND (b.bio_signals > 0 OR EXISTS (SELECT 1 FROM samples s
                      WHERE s.system_address = b.system_address AND s.body_id = b.body_id))
               ORDER BY b.distance_ls IS NULL, b.distance_ls, b.body_id""",
            (system["address"],),
        ).fetchall()
        for b in rows:
            done = [sample_dict(r) for r in db.execute(
                "SELECT * FROM samples WHERE system_address=? AND body_id=? ORDER BY ts",
                (b["system_address"], b["body_id"]))]
            done_genera = {d["genus_name"] for d in done}
            genuses = json.loads(b["genuses"]) if b["genuses"] else []
            bodies.append({
                "body_id": b["body_id"],
                "name": short_body_name(b["name"], system_name) or f"Body {b['body_id']}",
                "planet_class": b["planet_class"],
                "atmosphere": b["atmosphere"],
                "gravity_g": round(b["gravity"] / 9.81, 2) if b["gravity"] else None,
                "temperature": round(b["temperature"]) if b["temperature"] else None,
                "distance_ls": round(b["distance_ls"]) if b["distance_ls"] is not None else None,
                "bio_signals": b["bio_signals"] or len(done),
                "genuses": [{
                    "name": g,
                    "max_base": genus_max_value(g),
                    "max_value": (genus_max_value(g) or 0) * multiplier or None,
                    "done": g in done_genera,
                } for g in genuses],
                "samples": done,
                "is_current": body.get("body_id") == b["body_id"] and body.get("system_address") == system.get("address"),
            })

    # unsold samples, grouped by system and body
    unsold_rows = db.execute(
        """SELECT s.*, b.name AS body_name, sy.name AS system_name
           FROM samples s
           LEFT JOIN bodies b ON b.system_address = s.system_address AND b.body_id = s.body_id
           LEFT JOIN systems sy ON sy.address = s.system_address
           WHERE s.status = 'unsold'
           ORDER BY s.ts DESC""").fetchall()
    unsold_systems = {}
    for r in unsold_rows:
        sysgroup = unsold_systems.setdefault(r["system_address"], {
            "address": r["system_address"], "name": r["system_name"] or "Unknown system",
            "bodies": {}, "value": 0, "count": 0,
        })
        bname = short_body_name(r["body_name"], r["system_name"]) or f"Body {r['body_id']}"
        sd = sample_dict(r)
        sysgroup["bodies"].setdefault(bname, []).append(sd)
        sysgroup["value"] += sd["value"] or 0
        sysgroup["count"] += 1
    unsold = [{**g, "bodies": [{"name": n, "samples": s} for n, s in g["bodies"].items()]}
              for g in unsold_systems.values()]

    # deaths that cost samples
    deaths = []
    for d in db.execute("SELECT * FROM deaths ORDER BY ts DESC LIMIT 20"):
        lost_rows = db.execute(
            """SELECT s.*, b.name AS body_name, sy.name AS system_name
               FROM samples s
               LEFT JOIN bodies b ON b.system_address = s.system_address AND b.body_id = s.body_id
               LEFT JOIN systems sy ON sy.address = s.system_address
               WHERE s.death_id = ? ORDER BY s.ts""", (d["id"],)).fetchall()
        if not lost_rows:
            continue
        lost = []
        for r in lost_rows:
            sd = sample_dict(r)
            sd["system_name"] = r["system_name"] or "Unknown system"
            sd["body_name"] = short_body_name(r["body_name"], r["system_name"]) or f"Body {r['body_id']}"
            sd["body_full_name"] = r["body_name"]
            lost.append(sd)
        deaths.append({
            "ts": d["ts"], "system_name": d["system_name"], "body_name": d["body_name"],
            "samples": lost, "value": sum(s["value"] or 0 for s in lost),
        })
        if len(deaths) >= 5:
            break

    # scan in progress
    in_progress = kv.get("in_progress")
    if in_progress:
        brow = db.execute("SELECT b.name AS body_name, sy.name AS system_name FROM bodies b "
                          "LEFT JOIN systems sy ON sy.address = b.system_address "
                          "WHERE b.system_address=? AND b.body_id=?",
                          (in_progress["system_address"], in_progress["body_id"])).fetchone()
        in_progress = {
            **in_progress,
            "body_name": short_body_name(brow["body_name"], brow["system_name"]) if brow else None,
            "colony_distance": COLONY_DISTANCE.get(in_progress.get("genus_name")),
            "value": estimate(in_progress.get("species"), in_progress.get("species_name")),
            "on_this_body": body.get("body_id") == in_progress.get("body_id")
                            and body.get("system_address") == in_progress.get("system_address"),
        }

    totals = db.execute(
        """SELECT
             SUM(status = 'unsold') AS unsold_count,
             COUNT(DISTINCT CASE WHEN status = 'unsold' THEN system_address || ':' || body_id END) AS unsold_bodies,
             SUM(CASE WHEN status = 'sold' THEN sold_value END) AS sold_value,
             COUNT(DISTINCT species) AS species_count
           FROM samples""").fetchone()

    return {
        "version": app.version,
        "cmdr": kv.get("cmdr"),
        "system": system_name,
        "body": short_body_name(body.get("name"), system_name) if body else None,
        "last_event_ts": kv.get("last_event_ts"),
        "in_progress": in_progress,
        "bodies": bodies,
        "unsold": unsold,
        "unsold_value": sum(g["value"] for g in unsold),
        "unsold_count": totals["unsold_count"] or 0,
        "unsold_bodies": totals["unsold_bodies"] or 0,
        "sold_value": totals["sold_value"] or 0,
        "species_count": totals["species_count"] or 0,
        "deaths": deaths,
        "footfall": {"assumed": bool(app.cfg.get("assume_first_footfall", True)), "multiplier": multiplier},
        "dashboard_url": app.dashboard_url,
    }


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------
class App:
    def __init__(self, db, cfg, journal_dir):
        self.db = db
        self.cfg = cfg
        self.lock = threading.Lock()
        self.watcher = JournalWatcher(journal_dir, db, self.lock)
        self.version = 1
        self.dashboard_url = None


STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/index.html": ("index.html", "text/html; charset=utf-8"),
                "/icon.svg": ("icon.svg", "image/svg+xml")}


class Handler(BaseHTTPRequestHandler):
    server_version = "EDExoTool"

    def log_message(self, *args):
        pass  # keep the terminal quiet

    def reply(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        app = self.server.app
        path = urlparse(self.path).path
        if path == "/api/state":
            with app.lock:
                state = build_state(app)
            self.reply(200, json.dumps(state).encode("utf-8"), "application/json")
        elif path in STATIC_FILES:
            name, ctype = STATIC_FILES[path]
            try:
                self.reply(200, (WEB_DIR / name).read_bytes(), ctype)
            except OSError:
                self.reply(500, b"Dashboard files are missing next to exotool.py", "text/plain")
        else:
            self.reply(404, b"Not found", "text/plain")


def watch_loop(app):
    while True:
        try:
            if app.watcher.catch_up():
                app.version += 1
        except Exception as e:  # never let the watcher thread die
            print(f"! Error while reading the journal: {e}")
        time.sleep(1)


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # sends nothing, just picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return None


def wait_and_exit(code):
    if sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window.")
        except EOFError:
            pass
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(description="Elite Dangerous exobiology dashboard")
    ap.add_argument("--journal-dir", help="folder with Journal.*.log files (default: auto-detect)")
    ap.add_argument("--port", type=int, help="web dashboard port")
    ap.add_argument("--data-dir", help=f"where the database lives (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--config-dir", help=f"where config.json lives (default: {DEFAULT_CONFIG_DIR})")
    ap.add_argument("--reimport", action="store_true", help="delete the database and read all journals again")
    args = ap.parse_args()

    cfg = load_config(Path(args.config_dir) if args.config_dir else DEFAULT_CONFIG_DIR)
    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
    port = args.port or int(cfg.get("port", 8765))

    print("ED ExoTool")
    journal_dir = find_journal_dir(args.journal_dir or cfg.get("journal_dir"))
    if not journal_dir:
        print("! No Elite Dangerous journal folder found.")
        print(f"  Set \"journal_dir\" in {DEFAULT_CONFIG_DIR / 'config.json'}")
        print("  or start with --journal-dir \"/path/to/Elite Dangerous\".")
        wait_and_exit(1)
    print(f"  Journals: {journal_dir}")

    db_path = data_dir / "exotool.db"
    if args.reimport:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
    db = open_db(db_path)
    print(f"  Database: {db_path}")

    app = App(db, cfg, journal_dir)
    started = time.time()
    print("  Reading new journal entries ...")
    handled = app.watcher.catch_up(verbose=True)
    print(f"  {handled} relevant events processed in {time.time() - started:.1f} s")

    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    except OSError as e:
        print(f"! Cannot open port {port}: {e}")
        print("  Is ExoTool already running? Otherwise choose another port in config.json.")
        wait_and_exit(1)
    server.app = app

    ip = lan_ip()
    app.dashboard_url = f"http://{ip}:{port}" if ip else f"http://localhost:{port}"
    print()
    print(f"  Dashboard on this PC:  http://localhost:{port}")
    if ip:
        print(f"  Dashboard on tablet:   http://{ip}:{port}")
    print("\n  Close this window to stop ExoTool.\n")

    threading.Thread(target=watch_loop, args=(app,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
