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
"""adif2sqlite - convert an ADIF (.adi) ham-radio log export into a SQLite database.

Zero dependencies (Python 3.8+ stdlib only). Parses ADIF length-prefixed fields
correctly (data may itself contain '<' or '>'), skips the optional header, and
writes one row per QSO into a 'qso' table with every ADIF field as a TEXT column,
plus a derived ISO-8601 UTC 'qso_ts' (from QSO_DATE + TIME_ON) for easy sorting
and reporting.

Usage:
    python3 adif2sqlite.py LOG.adi [OUTPUT.db]

Re-run any time you re-export: the 'qso' table is rebuilt from scratch.
ADIF specification: https://adif.org
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone


def parse_adif(raw: bytes):
    """Return (header, records). Field names are upper-cased.

    ADIF .adi is a stream of ``<NAME:LEN[:TYPE]>DATA`` fields. LEN is the byte
    length of DATA, so DATA is read by length -- never by scanning for '>',
    which can legitimately appear inside a value. ``<EOH>`` ends the optional
    header; ``<EOR>`` ends each record.
    """
    header: dict[str, str] = {}
    records: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    # No header if the file's first non-whitespace byte is already a tag.
    in_body = raw.lstrip()[:1] == b"<"
    i = 0
    while True:
        lt = raw.find(b"<", i)
        if lt < 0:
            break
        gt = raw.find(b">", lt + 1)
        if gt < 0:
            break
        tag = raw[lt + 1 : gt].decode("ascii", "replace")
        i = gt + 1
        parts = tag.split(":")
        name = parts[0].strip().upper()

        if name == "EOH":
            in_body = True
            cur = {}
            continue
        if name == "EOR":
            if cur:
                records.append(cur)
            cur = {}
            continue

        length = 0
        if len(parts) >= 2:
            try:
                length = int(parts[1].strip())
            except ValueError:
                length = 0
        val = raw[i : i + length].decode("utf-8", "replace")
        i += length
        (cur if in_body else header)[name] = val

    if cur:  # tolerate a final record with no closing <EOR>
        records.append(cur)
    return header, records


def iso_ts(rec: dict) -> str | None:
    """ISO-8601 UTC timestamp from QSO_DATE (YYYYMMDD) + TIME_ON (HHMM[SS])."""
    d = rec.get("QSO_DATE", "")
    if len(d) != 8 or not d.isdigit():
        return None
    t = (rec.get("TIME_ON", "") + "000000")[:6]
    if not t.isdigit():
        t = "000000"
    try:
        datetime(
            int(d[0:4]), int(d[4:6]), int(d[6:8]),
            int(t[0:2]), int(t[2:4]), int(t[4:6]), tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}T{t[0:2]}:{t[2:4]}:{t[4:6]}Z"


def build_db(records, db_path):
    """(Re)create the 'qso' table and load every record. Returns the column list."""
    cols: list[str] = []
    seen: set[str] = set()
    for r in records:
        for k in r:
            lk = k.lower()
            if lk not in seen and lk not in ("id", "qso_ts"):
                seen.add(lk)
                cols.append(lk)

    con = sqlite3.connect(db_path)
    try:
        c = con.cursor()
        c.execute("DROP TABLE IF EXISTS qso")
        coldef = ", ".join(f'"{col}" TEXT' for col in cols)
        c.execute(
            "CREATE TABLE qso (id INTEGER PRIMARY KEY, qso_ts TEXT"
            + (", " + coldef if coldef else "")
            + ")"
        )

        insert_cols = ["qso_ts"] + cols
        quoted = ", ".join(f'"{col}"' for col in insert_cols)
        placeholders = ", ".join("?" for _ in insert_cols)
        rows = []
        for r in records:
            lower = {k.lower(): v for k, v in r.items()}
            rows.append([iso_ts(r)] + [lower.get(col) for col in cols])
        c.executemany(f"INSERT INTO qso ({quoted}) VALUES ({placeholders})", rows)

        for idx in ("call", "band", "mode", "qso_date", "qso_ts"):
            if idx == "qso_ts" or idx in seen:
                c.execute(f'CREATE INDEX IF NOT EXISTS ix_qso_{idx} ON qso("{idx}")')

        con.commit()
        return cols
    finally:
        con.close()


def summarize(db_path):
    con = sqlite3.connect(db_path)
    try:
        c = con.cursor()
        n = c.execute("SELECT COUNT(*) FROM qso").fetchone()[0]
        lo, hi = c.execute("SELECT MIN(qso_ts), MAX(qso_ts) FROM qso").fetchone()
        print(f"  QSOs:        {n}")
        print(f"  date range:  {lo or '?'}  ..  {hi or '?'}")

        def top(col, label):
            try:
                rows = c.execute(
                    f'SELECT "{col}", COUNT(*) AS n FROM qso '
                    f'WHERE "{col}" IS NOT NULL AND "{col}" <> "" '
                    f'GROUP BY "{col}" ORDER BY n DESC LIMIT 6'
                ).fetchall()
            except sqlite3.OperationalError:
                return
            if rows:
                print(f"  top {label}: " + ", ".join(f"{v}={k}" for v, k in rows))

        top("band", "bands")
        top("mode", "modes")
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert an ADIF (.adi) log to SQLite.")
    ap.add_argument("adif", help="input ADIF file (.adi)")
    ap.add_argument("db", nargs="?", help="output SQLite file (default: <input>.db)")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.adif):
        ap.error(f"no such file: {args.adif}")
    db_path = args.db or (os.path.splitext(args.adif)[0] + ".db")

    with open(args.adif, "rb") as f:
        raw = f.read()
    header, records = parse_adif(raw)
    if not records:
        print("No QSO records found - is this an ADIF file?", file=sys.stderr)
        return 1

    cols = build_db(records, db_path)
    print(f"Wrote {db_path}")
    print(f"  columns:     {len(cols)} ADIF fields + id + qso_ts")
    prog, ver = header.get("PROGRAMID", ""), header.get("ADIF_VER", "")
    if prog or ver:
        print(f"  source:      {prog}  (ADIF {ver})".rstrip())
    summarize(db_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
