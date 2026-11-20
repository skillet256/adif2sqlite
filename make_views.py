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
"""make_views.py - build analytical SQLite views over the 'qso' table and export
the removable same-second duplicates to CSV.

Non-destructive: it only creates views and writes a CSV; it never changes rows.
Run it after each (re)import with adif2sqlite.py.

Views:
  qso_deduped - one row per QSO: the lowest id per key (hides exact duplicates).
  qso_typed   - qso_deduped plus typed helper columns for reporting:
                freq_mhz, tx_pwr_w, stx_n, srx_n (numeric where present),
                year (INTEGER) and month ('YYYY-MM').

Dedup key: CALL + BAND + MODE + QSO_TS(to the second), plus 4-char GRIDSQUARE and
MY_GRIDSQUARE when those fields exist (so a rover on a grid line stays distinct).
The script adapts to whatever fields a log actually has.

Usage: python3 make_views.py [hamlog.db] [dups.csv]
"""
import csv
import os
import sqlite3
import sys


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "hamlog.db"
    out = (sys.argv[2] if len(sys.argv) > 2
           else os.path.join(os.path.dirname(os.path.abspath(db)) or ".", "dups_same_second.csv"))

    con = sqlite3.connect(db)
    c = con.cursor()
    cols = [r[1] for r in c.execute("PRAGMA table_info(qso)")]
    have = set(cols)

    # Dedup key: adapt to the fields that exist.
    part = [f"upper(trim({x}))" for x in ("call", "band", "mode") if x in have]
    part.append("qso_ts")
    for g in ("gridsquare", "my_gridsquare"):
        if g in have:
            part.append(f"substr(upper(trim(coalesce({g},''))),1,4)")
    partition = ", ".join(part)

    # qso_deduped: lowest id per key, all original columns unchanged.
    collist = ", ".join(f'"{x}"' for x in cols)
    c.execute("DROP VIEW IF EXISTS qso_deduped")
    c.execute(
        f"CREATE VIEW qso_deduped AS SELECT {collist} FROM ("
        f"  SELECT q.*, ROW_NUMBER() OVER (PARTITION BY {partition} ORDER BY id) AS _rn"
        f"  FROM qso q) WHERE _rn = 1"
    )

    # qso_typed: typed helpers for reporting (only for fields that exist).
    typed = []
    for src, dst in (("freq", "freq_mhz"), ("tx_pwr", "tx_pwr_w")):
        if src in have:
            typed.append(f"CAST(NULLIF({src},'') AS REAL) AS {dst}")
    for src, dst in (("stx", "stx_n"), ("srx", "srx_n")):
        if src in have:
            typed.append(f"CAST(NULLIF({src},'') AS INTEGER) AS {dst}")
    typed.append("CAST(substr(qso_ts,1,4) AS INTEGER) AS year")
    typed.append("substr(qso_ts,1,7) AS month")
    c.execute("DROP VIEW IF EXISTS qso_typed")
    c.execute(f"CREATE VIEW qso_typed AS SELECT *, {', '.join(typed)} FROM qso_deduped")
    con.commit()

    base = c.execute("SELECT COUNT(*) FROM qso").fetchone()[0]
    dd = c.execute("SELECT COUNT(*) FROM qso_deduped").fetchone()[0]

    # CSV of the rows qso_deduped drops, each pointing at the copy it keeps.
    fields = [x for x in ("call", "band", "mode", "qso_ts", "freq",
                          "gridsquare", "my_gridsquare", "station_callsign") if x in have]
    order = "call, qso_ts" if "call" in have else "qso_ts"
    inner = ", ".join(["id"] + fields)
    rows = c.execute(
        f"WITH r AS (SELECT {inner}, ROW_NUMBER() OVER w AS rn, MIN(id) OVER w AS keep_id "
        f"FROM qso WINDOW w AS (PARTITION BY {partition} ORDER BY id)) "
        f"SELECT id, keep_id AS dup_of, {', '.join(fields)} FROM r WHERE rn > 1 ORDER BY {order}"
    ).fetchall()
    hdr = ["id", "dup_of"] + fields
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)

    print(f"qso_deduped: {dd} rows  (base {base}, hides {base - dd})")
    print(f"qso_typed:   {dd} rows + typed helper columns")
    print(f"CSV:         {out}  ({len(rows)} rows)")


if __name__ == "__main__":
    main()
