#!/usr/bin/env python3
"""Persist progress JSONL into VeriLib ``repostats``.

Colour pipelines (verus/aeneas) map the burn-up series to meaning-based columns
(1:1 values):

    tracked, verified, verified_trusted, translated
    in_progress <- yellow
    unspecified <- white
    failed      <- red

A leanblueprint history has no colour fields; it is folded into those same
columns using the combined mapping (``plot_progress.combined_svg``),
with ``translated`` always 0. Either way the untouched source record is stored
in ``raw_record`` so the derived columns stay reversible.

Only ``status == ok`` rows are written. Requires PyMySQL.

    python3 persist_progress_jsonl.py \\
      --jsonl data/<project>/progress.jsonl --project <project> --env prod
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from plot_progress import COMBINED_FIELDS, _coerce_ints, _present, _read_rows

PLOT_FIELDS = (
    "tracked",
    "verified",
    "verified_trusted",
    "translated",
    "in_progress",
    "unspecified",
    "failed",
)

PIPELINE_LEANBLUEPRINT = "leanblueprint"

DEFAULT_MAP = Path(__file__).resolve().parent / "repos.map.json"


def plot_categories_from_record(record: dict) -> dict[str, int]:
    """Counts matching ``plot_progress.burnup_svg`` for one sample."""
    return {
        "tracked": int(record["tracked"]),
        "verified": int(record["verified"]),
        "verified_trusted": int(record["verified_trusted"]),
        "translated": int(record["translated"]),
        "in_progress": int(record["yellow"]),
        "unspecified": int(record["white"]),
        "failed": int(record["red"]),
    }


def atoms_categories_from_record(record: dict) -> dict[str, int]:
    """Counts matching ``plot_progress.combined_svg`` for one sample.

    Every blueprint node is one atom; definitions and theorems are pooled.
    """
    verified = record["bp_def_verified"] + record["bp_thm_verified"]
    return {
        "tracked": record["bp_def_total"] + record["bp_thm_total"],
        "verified": verified,
        "verified_trusted": verified + record["bp_def_trusted"] + record["bp_thm_trusted"],
        # Aeneas-only intermediate; a blueprint history has no translation step.
        "translated": 0,
        "in_progress": record["bp_def_in_progress"] + record["bp_thm_in_progress"],
        "unspecified": (
            (record["bp_def_total"] - record["bp_def_formalized"])
            + (record["bp_thm_total"] - record["bp_thm_formalized"])
        ),
        "failed": record["bp_def_failed"] + record["bp_thm_failed"],
    }


def validate_atoms_categories(raw: dict, cats: dict[str, int]) -> list[str]:
    """Return frontier/nesting violations for an ok leanblueprint sample.

    Absent bp_* columns coerce to 0, so require them rather than persisting an
    empty series for a history that predates them.
    """
    missing = [f for f in COMBINED_FIELDS if not _present(raw, f)]
    if missing:
        return [
            "missing per-node proof-status columns "
            f"({', '.join(missing[:4])}{'…' if len(missing) > 4 else ''}); "
            "re-sample with a probe-leanblueprint that emits them"
        ]

    errors: list[str] = []
    if not (cats["verified"] <= cats["verified_trusted"] <= cats["tracked"]):
        errors.append(
            f"frontier nesting violated (verified {cats['verified']} <= "
            f"verified+trusted {cats['verified_trusted']} <= tracked {cats['tracked']})"
        )
    for name in ("in_progress", "failed", "unspecified"):
        if cats[name] > cats["tracked"]:
            errors.append(f"{name} ({cats[name]}) exceeds tracked ({cats['tracked']})")
    return errors


def validate_plot_categories(record: dict, cats: dict[str, int]) -> list[str]:
    """Return colors.py invariant violations for an ok sample."""
    errors: list[str] = []
    white = int(record["white"])
    red = int(record["red"])
    yellow = int(record["yellow"])
    light_green = int(record["light_green"])
    dark_green = int(record["dark_green"])
    purple = int(record["purple"])
    grey = int(record["grey"])
    exec_total = int(record["exec_total"])

    verified_from_bars = light_green + dark_green
    verified_trusted_from_bars = verified_from_bars + purple
    tracked_from_bars = white + red + yellow + verified_from_bars + purple
    tracked_from_exec = exec_total - grey

    if cats["verified"] != verified_from_bars:
        errors.append(
            f"verified ({cats['verified']}) != light_green+dark_green ({verified_from_bars})"
        )
    if cats["verified_trusted"] != verified_trusted_from_bars:
        errors.append(
            f"verified_trusted ({cats['verified_trusted']}) != "
            f"verified+purple ({verified_trusted_from_bars})"
        )
    if cats["tracked"] != tracked_from_bars:
        errors.append(
            f"tracked ({cats['tracked']}) != white+red+yellow+verified+purple "
            f"({tracked_from_bars})"
        )
    if cats["tracked"] != tracked_from_exec:
        errors.append(
            f"tracked ({cats['tracked']}) != exec_total-grey ({tracked_from_exec})"
        )
    if cats["unspecified"] != white:
        errors.append(f"unspecified ({cats['unspecified']}) != white ({white})")
    if cats["in_progress"] != yellow:
        errors.append(f"in_progress ({cats['in_progress']}) != yellow ({yellow})")
    if cats["verified_trusted"] < cats["verified"]:
        errors.append(
            f"verified_trusted ({cats['verified_trusted']}) < verified ({cats['verified']})"
        )
    if cats["tracked"] < cats["verified_trusted"]:
        errors.append(
            f"tracked ({cats['tracked']}) < verified_trusted ({cats['verified_trusted']})"
        )
    if record.get("pipeline") == "aeneas":
        if cats["translated"] < cats["verified"]:
            errors.append(
                f"translated ({cats['translated']}) < verified ({cats['verified']}) "
                "(Aeneas invariant)"
            )
        if cats["tracked"] < cats["translated"]:
            errors.append(
                f"tracked ({cats['tracked']}) < translated ({cats['translated']}) "
                "(Aeneas invariant)"
            )
    return errors


def record_to_row(
    record: dict,
    repo_id: int,
    *,
    raw: dict | None = None,
    strict: bool = True,
) -> dict[str, Any] | None:
    """Map one JSONL record to a repostats row, or None if not ``ok``.

    ``raw`` is the pre-coercion record; it is stored verbatim in ``raw_record``
    and used to tell an absent column from a genuine zero.
    """
    if record.get("status") != "ok":
        return None

    raw = record if raw is None else raw
    if record.get("pipeline") == PIPELINE_LEANBLUEPRINT:
        cats = atoms_categories_from_record(record)
        violations = validate_atoms_categories(raw, cats)
    else:
        cats = plot_categories_from_record(record)
        violations = validate_plot_categories(record, cats)
    if violations:
        commit = record.get("commit", "?")
        msg = f"commit={commit}: " + "; ".join(violations)
        if strict:
            raise ValueError(msg)
        print(f"warning: {msg}", file=sys.stderr)

    sample_date = record.get("sample_date")
    if not sample_date:
        raise ValueError(f"ok sample missing sample_date: commit={record.get('commit')}")

    commit_date_raw = record.get("commit_date") or None
    commit_date = None
    if commit_date_raw:
        try:
            commit_date = datetime.fromisoformat(str(commit_date_raw).replace("Z", "+00:00"))
            commit_date = commit_date.replace(tzinfo=None)
        except ValueError:
            commit_date = None

    return {
        "repo_id": repo_id,
        "verified": cats["verified"],
        "tracked": cats["tracked"],
        "verified_trusted": cats["verified_trusted"],
        "translated": cats["translated"],
        "unspecified": cats["unspecified"],
        "in_progress": cats["in_progress"],
        "failed": cats["failed"],
        "raw_record": json.dumps(raw, sort_keys=True, separators=(",", ":")),
        "commit": (record.get("commit") or None),
        "pipeline": (record.get("pipeline") or None),
        "commit_date": commit_date,
        "snapshot_date": sample_date,
        "created_at": commit_date,
    }


def load_ok_rows(
    jsonl_path: Path,
    repo_id: int,
    *,
    strict: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Return (rows_to_insert, skipped_non_ok_count)."""
    # Keep the pre-coercion rows: they preserve blank-vs-zero and are what gets
    # archived in raw_record.
    raw_rows = _read_rows(jsonl_path)
    records = _coerce_ints([dict(r) for r in raw_rows])
    rows: list[dict[str, Any]] = []
    skipped = 0
    for record, raw in zip(records, raw_rows, strict=True):
        row = record_to_row(record, repo_id, raw=raw, strict=strict)
        if row is None:
            skipped += 1
            continue
        rows.append(row)
    return rows, skipped


def load_repo_map(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_repo_id(
    repo_map: dict,
    project: str,
    env: str,
    override: int | None,
) -> int:
    if override is not None:
        if override <= 0:
            raise ValueError("--repo-id must be a positive integer")
        return override
    entry = repo_map.get(project)
    if not entry:
        known = ", ".join(sorted(repo_map)) or "(empty map)"
        raise ValueError(f"project {project!r} not in repo map; known: {known}")
    ids = entry.get("repo_ids") or {}
    rid = ids.get(env)
    if rid is None:
        raise ValueError(
            f"no repo_id for project={project!r} env={env!r} in map "
            f"(set repo_ids.{env} or pass --repo-id)"
        )
    rid = int(rid)
    if rid <= 0:
        raise ValueError(f"invalid repo_id {rid} for {project}/{env}")
    return rid


def connect_mysql(args: argparse.Namespace):
    try:
        import pymysql
    except ImportError as e:
        raise SystemExit(
            "PyMySQL is required: pip install PyMySQL\n" + str(e)
        ) from e

    return pymysql.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=args.db_password,
        database=args.db_name,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.Cursor,
    )


INSERT_SQL = """
INSERT INTO repostats (
    repo_id, verified,
    tracked, verified_trusted, translated, unspecified, in_progress, failed,
    raw_record, commit, pipeline, commit_date,
    snapshot_date, created_at
) VALUES (
    %(repo_id)s, %(verified)s,
    %(tracked)s, %(verified_trusted)s, %(translated)s, %(unspecified)s,
    %(in_progress)s, %(failed)s,
    %(raw_record)s, %(commit)s, %(pipeline)s, %(commit_date)s,
    %(snapshot_date)s, COALESCE(%(created_at)s, CURRENT_TIMESTAMP)
)
"""


def persist_rows(
    conn,
    repo_id: int,
    rows: list[dict[str, Any]],
    *,
    replace: bool,
    dry_run: bool,
) -> tuple[int, int]:
    """Delete (if replace) and insert rows. Returns (deleted, inserted)."""
    deleted = 0
    if dry_run:
        if replace:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM repostats WHERE repo_id = %s", (repo_id,))
                deleted = int(cur.fetchone()[0])
        return deleted, len(rows)

    with conn.cursor() as cur:
        if replace:
            cur.execute("DELETE FROM repostats WHERE repo_id = %s", (repo_id,))
            deleted = cur.rowcount
        for row in rows:
            cur.execute(INSERT_SQL, row)
    conn.commit()
    return deleted, len(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Persist progress JSONL into VeriLib repostats."
    )
    p.add_argument("--jsonl", type=Path, required=True, help="Path to progress.jsonl")
    p.add_argument(
        "--project",
        required=True,
        help="Project key in repos.map.json",
    )
    p.add_argument(
        "--env",
        choices=("dev", "staging", "prod"),
        required=True,
        help="Target environment (selects repo_id from the map)",
    )
    p.add_argument(
        "--map",
        type=Path,
        default=DEFAULT_MAP,
        help=f"Repo id map JSON (default: {DEFAULT_MAP})",
    )
    p.add_argument("--repo-id", type=int, default=None, help="Override repo_id from the map")
    p.add_argument(
        "--keep-existing",
        action="store_true",
        help="Append instead of replacing this repo_id's repostats series",
    )
    p.add_argument("--dry-run", action="store_true", help="Parse and resolve; do not write")
    p.add_argument(
        "--no-strict",
        action="store_true",
        help="Warn on invariant mismatches instead of aborting",
    )

    p.add_argument("--db-host", default=os.environ.get("VERILIB_DB_HOST", "127.0.0.1"))
    p.add_argument("--db-port", type=int, default=int(os.environ.get("VERILIB_DB_PORT", "3306")))
    p.add_argument("--db-name", default=os.environ.get("VERILIB_DB_NAME", "verilib"))
    p.add_argument("--db-user", default=os.environ.get("VERILIB_DB_USER", "root"))
    p.add_argument("--db-password", default=os.environ.get("VERILIB_DB_PASSWORD", ""))
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.jsonl.is_file():
        print(f"error: JSONL not found: {args.jsonl}", file=sys.stderr)
        return 1
    if not args.map.is_file():
        print(f"error: repo map not found: {args.map}", file=sys.stderr)
        return 1

    repo_map = load_repo_map(args.map)
    try:
        repo_id = resolve_repo_id(repo_map, args.project, args.env, args.repo_id)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        rows, skipped = load_ok_rows(
            args.jsonl, repo_id, strict=not args.no_strict
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    replace = not args.keep_existing
    print(
        f"project={args.project} env={args.env} repo_id={repo_id} "
        f"ok_rows={len(rows)} skipped_non_ok={skipped} replace={replace}"
    )
    if not rows:
        print("nothing to insert", file=sys.stderr)
        return 1

    if args.dry_run:
        if replace:
            conn = connect_mysql(args)
            try:
                deleted, inserted = persist_rows(
                    conn, repo_id, rows, replace=True, dry_run=True
                )
            finally:
                conn.close()
            print(f"[dry-run] would delete {deleted} existing row(s), insert {inserted}")
        else:
            print(f"[dry-run] would append {len(rows)} row(s) (keep-existing)")
        sample = {k: rows[0][k] for k in PLOT_FIELDS}
        sample["snapshot_date"] = rows[0]["snapshot_date"]
        sample["commit"] = rows[0]["commit"]
        print(f"[dry-run] first row metrics: {sample}")
        return 0

    conn = connect_mysql(args)
    try:
        deleted, inserted = persist_rows(
            conn, repo_id, rows, replace=replace, dry_run=False
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"deleted={deleted} inserted={inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
