#!/usr/bin/env python3
"""
NDW laadpaal-status collector.

Downloadt charging_point_locations_ocpi.json.gz van opendata.ndw.nu en logt
per EVSE de actuele status naar gecomprimeerde CSV-snapshots:
- snelladers (DC): elke run (elk half uur)
- reguliere palen (AC): alleen als de vorige AC-snapshot ouder is dan ~55 min,
  effectief dus elk uur
Onderhoudt daarnaast een referentiebestand (locations.csv.gz) met statische
locatiegegevens (EVSE -> locatie, coördinaten, operator, vermogen).

Draaien: python3 collect.py  (elke 30 min via GitHub Actions, zie
         .github/workflows/collect.yml)
Output:  ./snapshots_dc/status_YYYYMMDD_HHMM.csv.gz  (evse_uid,status)
         ./snapshots_ac/status_YYYYMMDD_HHMM.csv.gz  (evse_uid,status)
         ./locations.csv.gz                           (referentie, wekelijks ververst)
         ./collect.log                                (logregel per run)
"""
import csv
import gzip
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

URL = "https://opendata.ndw.nu/charging_point_locations_ocpi.json.gz"
BASE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR_DC = os.path.join(BASE, "snapshots_dc")
SNAP_DIR_AC = os.path.join(BASE, "snapshots_ac")
REF_FILE = os.path.join(BASE, "locations.csv.gz")
REF_META = os.path.join(BASE, "locations_updated.txt")
LOG_FILE = os.path.join(BASE, "collect.log")
REF_MAX_AGE = 7 * 24 * 3600  # referentie wekelijks verversen
AC_MAX_AGE = 55 * 60         # AC loggen als vorige snapshot ouder is dan 55 min


def is_dc(evse: dict) -> bool:
    return any((c.get("power_type") or "").startswith("DC")
               for c in evse.get("connectors") or [])


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def download() -> list:
    req = urllib.request.Request(URL, headers={"User-Agent": "laadpaal-monitor/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
    return json.loads(gzip.decompress(raw))


def newest_age(snap_dir: str) -> float:
    """Leeftijd (s) van de nieuwste snapshot o.b.v. de bestandsnaam (UTC).

    Git bewaart geen bestandstijden, dus mtime is na een checkout onbruikbaar.
    """
    try:
        newest = max(f for f in os.listdir(snap_dir) if f.startswith("status_"))
        ts = datetime.strptime(newest, "status_%Y%m%d_%H%M.csv.gz")
        return (datetime.now(timezone.utc) - ts.replace(tzinfo=timezone.utc)).total_seconds()
    except (OSError, ValueError):
        return None


def write_snapshot(locations: list, ts: datetime, snap_dir: str, dc: bool):
    os.makedirs(snap_dir, exist_ok=True)
    fname = os.path.join(snap_dir, f"status_{ts.strftime('%Y%m%d_%H%M')}.csv.gz")
    rows = []
    for loc in locations:
        for evse in loc.get("evses") or []:
            if is_dc(evse) != dc:
                continue
            uid = evse.get("evse_id") or evse.get("uid") or ""
            rows.append((uid, evse.get("status") or "UNKNOWN"))
    rows.sort()
    with gzip.open(fname, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["evse_uid", "status"])
        w.writerows(rows)
    return fname, len(rows)


def write_reference(locations: list) -> int:
    """EVSE -> statische kenmerken, voor koppeling in analyses."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "evse_uid", "location_id", "location_name", "address", "city",
        "postal_code", "lat", "lon", "operator", "party_id",
        "max_power_w", "power_type", "connector_types",
    ])
    n = 0
    for loc in locations:
        coords = loc.get("coordinates") or {}
        op = (loc.get("operator") or {}).get("name") or ""
        for evse in loc.get("evses") or []:
            conns = evse.get("connectors") or []
            powers = [c.get("max_electric_power") for c in conns if c.get("max_electric_power")]
            # fallback: schatting uit V*A (per fase; AC_3_PHASE x3)
            if not powers:
                for c in conns:
                    v, a = c.get("max_voltage"), c.get("max_amperage")
                    if v and a:
                        mult = 3 if c.get("power_type") == "AC_3_PHASE" else 1
                        powers.append(v * a * mult)
            w.writerow([
                evse.get("evse_id") or evse.get("uid") or "",
                loc.get("id") or "",
                loc.get("name") or "",
                loc.get("address") or "",
                loc.get("city") or "",
                loc.get("postal_code") or "",
                coords.get("latitude") or "",
                coords.get("longitude") or "",
                op,
                loc.get("party_id") or "",
                max(powers) if powers else "",
                ";".join(sorted({c.get("power_type") or "" for c in conns})),
                ";".join(sorted({c.get("standard") or "" for c in conns})),
            ])
            n += 1
    with gzip.open(REF_FILE, "wt") as f:
        f.write(buf.getvalue())
    return n


def main() -> int:
    ts = datetime.now(timezone.utc)
    t0 = time.time()
    try:
        locations = download()
    except Exception as e:
        log(f"FOUT bij downloaden: {e!r}")
        return 1
    fname, n = write_snapshot(locations, ts, SNAP_DIR_DC, dc=True)
    msg = f"DC {n} EVSEs"
    ac_age = newest_age(SNAP_DIR_AC)
    if ac_age is None or ac_age > AC_MAX_AGE:
        _, n_ac = write_snapshot(locations, ts, SNAP_DIR_AC, dc=False)
        msg += f", AC {n_ac} EVSEs"
    ref_msg = ""
    try:
        with open(REF_META) as f:
            ref_ts = datetime.fromisoformat(f.read().strip())
        ref_age = (ts - ref_ts).total_seconds()
    except (OSError, ValueError):
        ref_age = None
    if ref_age is None or ref_age > REF_MAX_AGE:
        nref = write_reference(locations)
        with open(REF_META, "w") as f:
            f.write(ts.isoformat(timespec="seconds"))
        ref_msg = f", referentie ververst ({nref} EVSEs)"
    log(f"OK {ts.strftime('%Y%m%d_%H%M')}: {msg} in {time.time()-t0:.1f}s{ref_msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
