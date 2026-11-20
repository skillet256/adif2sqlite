#!/usr/bin/env python3
# Copyright 2026 SystemWise
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""find_dupes.py - report likely duplicate QSOs in a hamlog.db built by adif2sqlite.

A QSO "key" is normalized CALL + BAND + MODE + QSO_DATE. Duplicates are reported
at two tolerances:
  * exact  - same key AND identical TIME_ON (to the second)
  * window - same key with TIME_ON within --minutes of each other (default 2),
             which catches one contact logged by two apps at slightly different
             times.

Read-only: reports only, changes nothing.

Usage:
    python3 find_dupes.py [hamlog.db] [--minutes N] [--examples N]
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from datetime import datetime


def epoch(ts: str) -> float:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").timestamp()


def norm(s) -> str:
    return (s or "").strip().upper()


def grid4(s) -> str:
    """Maidenhead to 4-char field+square: the contest-scoring grid.

    Collapses 6-char precision artifacts (EM10kf == EM10) while keeping genuinely
    different grids distinct -- so a rover on a grid line (EL18 vs EL19, same
    minute) stays two valid contacts, not a duplicate.
    """
    return norm(s)[:4]


def main():
    ap = argparse.ArgumentParser(description="Report likely duplicate QSOs.")
    ap.add_argument("db", nargs="?", default="hamlog.db")
    ap.add_argument("--minutes", type=float, default=2.0, help="time window (default 2)")
    ap.add_argument("--examples", type=int, default=8)
    ap.add_argument("--ignore-grid", action="store_true",
                    help="exclude grid squares from the key (NOT advised for VHF/contest logs: "
                         "rover QSOs in different grids are distinct contacts)")
    a = ap.parse_args()
    tol = a.minutes * 60

    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    total = con.execute("SELECT COUNT(*) FROM qso").fetchone()[0]
    rows = con.execute(
        "SELECT id, call, band, mode, freq, qso_ts, station_callsign, "
        "gridsquare, my_gridsquare FROM qso WHERE qso_ts IS NOT NULL"
    ).fetchall()

    # Grid squares distinguish rover contacts (yours AND theirs), so they belong
    # in the key unless explicitly excluded.
    groups: dict[tuple, list] = {}
    for r in rows:
        key = [norm(r["call"]), norm(r["band"]), norm(r["mode"]), r["qso_ts"][:10]]
        if not a.ignore_grid:
            key += [grid4(r["gridsquare"]), grid4(r["my_gridsquare"])]
        groups.setdefault(tuple(key), []).append(r)

    exact_groups = 0
    exact_surplus = 0
    window_clusters: list[list] = []
    window_surplus = 0

    for rs in groups.values():
        if len(rs) < 2:
            continue
        rs.sort(key=lambda r: epoch(r["qso_ts"]))

        for ts, k in Counter(r["qso_ts"] for r in rs).items():
            if k > 1:
                exact_groups += 1
                exact_surplus += k - 1

        cluster = [rs[0]]
        for r in rs[1:]:
            if epoch(r["qso_ts"]) - epoch(cluster[-1]["qso_ts"]) <= tol:
                cluster.append(r)
            else:
                if len(cluster) > 1:
                    window_clusters.append(cluster)
                    window_surplus += len(cluster) - 1
                cluster = [r]
        if len(cluster) > 1:
            window_clusters.append(cluster)
            window_surplus += len(cluster) - 1

    print(f"Total QSOs:                          {total}")
    print(f"Exact duplicates (same second):      {exact_surplus} surplus in {exact_groups} groups")
    print(f"Within {a.minutes:g}-min window:               {window_surplus} surplus in {len(window_clusters)} clusters")
    pct = 100 * window_surplus / total if total else 0
    print(f"Distinct QSOs if deduped @ {a.minutes:g} min:    {total - window_surplus}  "
          f"({window_surplus} removable, {pct:.2f}%)")

    if window_clusters:
        print(f"\n--- largest clusters (up to {a.examples}) ---")
        for cl in sorted(window_clusters, key=lambda c: -len(c))[: a.examples]:
            r0 = cl[0]
            print(f"  {norm(r0['call']):11} {norm(r0['band']):5} {norm(r0['mode']):6} x{len(cl)}")
            for r in cl:
                print(f"     id={r['id']:<6} {r['qso_ts']}  freq={r['freq'] or '-':<9} "
                      f"grid={r['gridsquare'] or '-':<6} mygrid={r['my_gridsquare'] or '-':<6} "
                      f"by={r['station_callsign'] or '-'}")


if __name__ == "__main__":
    main()
