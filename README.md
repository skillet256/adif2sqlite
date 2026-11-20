# adif2sqlite — ADIF ham log → SQLite, with dedup & reports

A small, dependency-light toolkit to turn an **ADIF** (`.adi`) amateur-radio log
export into a **SQLite** database you can query in [DBeaver](https://dbeaver.io/)
and report on in [Jupyter](https://jupyter.org/). Built for logs that have moved
between many apps over the years (CQRLOG, WSJT-X, N1MM, LoTW, eQSL, …) and
therefore carry lots of app-specific fields and real-world messiness.

- **Faithful ADIF parsing** — length-aware, so values containing `<`/`>` parse
  correctly; every field (including app-defined ones) becomes a column.
- **Cross-platform** — pure Python standard library for the core tools; runs on
  Linux, macOS and Windows.
- **Duplicate analysis that understands VHF/contest logs** — grid-aware, so a
  rover worked in multiple grids is *not* mistaken for a duplicate.
- **Reporting-ready views** and a starter Jupyter notebook.

## Requirements

- **Python 3.8+** (with SQLite 3.25+, which ships with any recent Python — needed
  for the analytical views).
- The core tools need **nothing else**.
- The reports (`notebooks/report.ipynb`) need `pandas`, `matplotlib`, `jupyterlab`
  (see [`requirements.txt`](requirements.txt)).

## Install

```sh
git clone https://github.com/<you>/adif2sqlite.git
cd adif2sqlite
```

For the reports only, optionally use a virtual environment:

```sh
python3 -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

python3 -m pip install -r requirements.txt
```

> On Windows, use `python` instead of `python3` if that's how Python is installed.

## Quick start

1. **Export your log to ADIF** from your logging program (e.g. CQRLOG:
   *File → Export → ADIF*). Call it `log.adi`.
2. **Convert to SQLite:**
   ```sh
   python3 adif2sqlite.py log.adi hamlog.db
   ```
3. **Build the analytical views:**
   ```sh
   python3 make_views.py hamlog.db
   ```
4. **Explore** — open `hamlog.db` in DBeaver, or launch the notebook:
   ```sh
   jupyter lab notebooks/report.ipynb
   ```

## The tools

| Script | What it does |
|---|---|
| `adif2sqlite.py` | Parse an ADIF `.adi` file into a SQLite `qso` table (every field a column, plus `id` and a derived UTC `qso_ts`). |
| `make_views.py` | Add non-destructive views `qso_deduped` and `qso_typed`, and export removable same-second duplicates to CSV. |
| `find_dupes.py` | Report likely duplicate QSOs at configurable tolerances (read-only). |
| `notebooks/report.ipynb` | Starter reports: QSOs over time, band × mode, modes, geography, confirmation rates. |

Each script takes `--help`. All of them accept the database (or ADIF) path as an
argument, so nothing is hard-coded.

## Tables & views

| Name | Rows | Use |
|---|---|---|
| `qso` | all | Raw import — every ADIF field as `TEXT`. |
| `qso_deduped` | deduped | One row per QSO (lowest `id` per key). Non-destructive view. |
| `qso_typed` | deduped | `qso_deduped` + numeric `freq_mhz`, `tx_pwr_w`, `stx_n`, `srx_n`, and `year`/`month`. Use this for reporting. |

Values in `qso` are text (ADIF `.adi` is text); `CAST` when you need numbers, or
just use `qso_typed`.

### Query in DBeaver

New Connection → **SQLite** → point at `hamlog.db` (the driver is built in):

```sql
SELECT band, mode, COUNT(*) AS qsos
FROM qso_typed GROUP BY band, mode ORDER BY qsos DESC;
```

### Report in Jupyter

```python
import sqlite3, pandas as pd
con = sqlite3.connect("hamlog.db")
df = pd.read_sql("SELECT * FROM qso_typed", con, parse_dates=["qso_ts"])
df.groupby("year").size()
```

## Duplicate handling

Deduping a multi-source log is subtle, so the key is deliberate:

**`CALL + BAND + MODE + QSO_TS(to the second)`**, plus **4-char `GRIDSQUARE` and
`MY_GRIDSQUARE`** when present.

- Grids are included because in VHF/UHF work a **rover** gives you a new valid QSO
  in each grid it enters — same call, band, mode and minute, different grid. Those
  must stay.
- Grids are truncated to **4 characters** (the contest-scoring grid) so a copy
  logged as `EM10` and another as `EM10kf` collapse to one true duplicate, while
  genuinely different grids (`EL18` vs `EL19`) stay distinct.

`make_views.py` keeps the lowest `id` per key in `qso_deduped` and writes the
dropped rows to `dups_same_second.csv` for you to verify. Nothing is deleted. To
actually remove verified duplicates:

```sql
DELETE FROM qso WHERE id NOT IN (SELECT id FROM qso_deduped);
```

`find_dupes.py` explores other tolerances (`--minutes N`, `--ignore-grid`).

## Re-importing

Logs grow. After a fresh export, just re-run the two build steps — both are
idempotent and rebuild from scratch:

```sh
python3 adif2sqlite.py log.adi hamlog.db && python3 make_views.py hamlog.db
```

## Notes & limitations

- ADIF times are UTC; `qso_ts` keeps them UTC (trailing `Z`).
- `DXCC` is stored as the ADIF entity *code*, not a country name (no offline name
  map is bundled).
- Before committing the notebook to a repo, clear its outputs (they can embed your
  data): *Kernel → Restart Kernel and Clear Outputs*.
- Your `.adi`, `.db` and `.csv` files are **git-ignored** so a personal log is
  never committed. Keep it that way.

## License

[Apache License 2.0](LICENSE). Copyright 2026 SystemWise.

## See also

- ADIF specification: https://adif.org
