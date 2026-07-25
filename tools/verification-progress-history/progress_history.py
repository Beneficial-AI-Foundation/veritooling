#!/usr/bin/env python3
"""Reconstruct a verification project's progress over git history.

Samples one commit per period (default: weekly, last commit on/before each
Friday), checks it out in a persistent work-clone, runs the matching probe
``extract`` (which runs the real verifier), and appends the full count-colors
metric set to an append-only JSONL time series (plus a regenerated CSV). The
output feeds the burn-up chart defined in the VeriLib engineering docs
("Atom statuses and colours", section "Progress chart (burn-up over time)").

Design notes (see the plan for rationale):
  * extract runs the verifier, so we sample sparsely and go oldest -> newest in
    ONE persistent clone to reuse cargo `target/` / Lean `.lake/` caches.
  * We never touch the user's checkout: a local path is cloned into --work-clone.
  * Checkout hygiene: `git checkout -f` each sample; never `git clean -x`
    (that would wipe the build caches). After extract we read the freshly
    written unified JSON and validate its `source.commit` == the sample SHA.
  * One PINNED probe version runs at every sample for consistent colour logic;
    commits the current probe cannot handle are recorded as failed, not fatal.
  * Verus determinism: a pinned SMT seed is forwarded via --verus-args.

Usage examples:
    progress_history.py /path/to/dalek-verus --pipeline verus \\
        --project-subdir curve25519-dalek --package curve25519-dalek \\
        --since 2025-07-14

    progress_history.py /path/to/SparsePostQuantumRatchet-verify \\
        --pipeline aeneas --since 2026-03-13 --sample-timeout 3600
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from colors import count_colors

# Repo root: tools/verification-progress-history/ -> veritooling/
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Cross-sample state (e.g. last-installed Verus release for setup-dedup).
_VERUS_STATE: dict = {}

# Fixed column order for the CSV / JSONL records.
METRIC_FIELDS = [
    "grey", "white", "red", "yellow", "light_green", "dark_green", "purple",
    "exec_total", "dot_red", "dot_yellow", "dot_green", "art_total",
    "tracked", "verified", "verified_trusted", "translated",
]
RECORD_FIELDS = [
    "repo", "pipeline", "sample_date", "commit", "commit_date",
    "tool", "tool_version", "status", "reason", "commit_validated",
    "duration_sec",
] + METRIC_FIELDS

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# --------------------------------------------------------------------------- #
# Subprocess helper with process-group timeout kill
# --------------------------------------------------------------------------- #
def run(cmd, cwd=None, timeout=None, env=None):
    """Run a command, capturing combined output. Returns (code, output).

    ``code`` is None on timeout. The child runs in its own process group so a
    hung tool (e.g. Charon) and all its children are killed on timeout.
    """
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            out, _ = proc.communicate(timeout=30)
        except Exception:
            out = ""
        return None, out


def git(args, cwd, timeout=600):
    code, out = run(["git", *args], cwd=cwd, timeout=timeout)
    if code != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({code}):\n{out}")
    return out.strip()


# --------------------------------------------------------------------------- #
# Repo resolution / work-clone
# --------------------------------------------------------------------------- #
def repo_name(repo: str) -> str:
    base = repo.rstrip("/").split("/")[-1]
    return re.sub(r"\.git$", "", base) or "repo"


def is_url(repo: str) -> bool:
    return "://" in repo or repo.startswith("git@")


def ensure_work_clone(repo: str, work_clone: Path) -> Path:
    """Create or reuse a persistent clone. Never touches the source checkout."""
    source = repo if is_url(repo) else str(Path(repo).resolve())
    work_clone = work_clone.resolve()
    if (work_clone / ".git").is_dir():
        print(f"[work-clone] reusing {work_clone}")
        try:
            git(["fetch", "--all", "--quiet"], cwd=work_clone)
        except RuntimeError as e:
            print(f"[work-clone] fetch warning: {e}", file=sys.stderr)
        return work_clone
    work_clone.parent.mkdir(parents=True, exist_ok=True)
    print(f"[work-clone] cloning {source} -> {work_clone}")
    code, out = run(["git", "clone", source, str(work_clone)], timeout=1800)
    if code != 0:
        raise RuntimeError(f"clone failed:\n{out}")
    return work_clone


# --------------------------------------------------------------------------- #
# Pipeline detection
# --------------------------------------------------------------------------- #
def detect_pipeline(project_dir: Path) -> str:
    if (project_dir / "aeneas-config.yml").is_file():
        return "aeneas"
    cargo = project_dir / "Cargo.toml"
    if cargo.is_file():
        text = cargo.read_text(encoding="utf-8", errors="ignore")
        if "metadata.verus" in text or "vstd" in text or "verus_builtin" in text:
            return "verus"
    if (project_dir / "lean-toolchain").is_file() or (project_dir / "lakefile.toml").is_file():
        return "lean"
    if cargo.is_file():
        return "verus"
    raise RuntimeError(f"could not auto-detect pipeline in {project_dir}")


def detect_verus_version(project_dir: Path, probe_verus: str) -> str | None:
    """Ask probe-verus which Verus release this commit pins.

    dalek-verus (and friends) pin Verus via the git ``rev`` of the ``vstd`` /
    ``verus_builtin`` dependencies in Cargo.toml, not a ``release =`` field, so
    we defer to probe-verus's own resolver (``setup --from-project
    --detect-version``), which maps the rev to a Verus release string such as
    ``0.2025.08.01.33c6cec``.
    """
    code, out = run([probe_verus, "setup", "--from-project", str(project_dir),
                     "--detect-version"], timeout=180)
    if code != 0:
        return None
    for line in reversed((out or "").splitlines()):
        s = line.strip()
        if re.match(r"^\d+\.\d+\.\d+", s):
            return s
    return None


# --------------------------------------------------------------------------- #
# Commit listing + periodic bucketing
# --------------------------------------------------------------------------- #
def default_ref(work_clone: Path) -> str:
    """A stable ref to enumerate history from, independent of the current
    (possibly detached) checkout. Prefer the remote default branch."""
    try:
        return git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=work_clone)
    except RuntimeError:
        pass
    try:
        return git(["symbolic-ref", "--short", "HEAD"], cwd=work_clone)
    except RuntimeError:
        return "HEAD"


def list_commits(work_clone: Path, ref: str, since: str | None, until: str | None):
    """Return [(sha, commit_datetime_utc)] oldest -> newest in range on `ref`.

    Enumerates from a stable ref, NOT the working checkout: per-sample
    `git checkout` detaches HEAD, and `git log` on a detached old commit would
    only see that commit's ancestors.
    """
    args = ["log", "--pretty=%H%x09%cI", "--reverse"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    args.append(ref)
    out = git(args, cwd=work_clone)
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, iso = line.split("\t", 1)
        dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        commits.append((sha, dt))
    return commits


def anchor_friday(dt: datetime, anchor_idx: int) -> datetime:
    """The anchor-day (default Friday) on or after dt's date, at end of day UTC."""
    days_ahead = (anchor_idx - dt.weekday()) % 7
    d = (dt + timedelta(days=days_ahead)).date()
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


def bucket_samples(commits, anchor_idx: int, cadence_weeks: int):
    """Group commits into cadence periods anchored on anchor-day.

    One sample per period that contains >=1 commit (weeks with no commit are
    gaps, not interpolated); the sample is the latest commit in the period.
    Returns [(sample_date_iso, sha, commit_datetime)] oldest -> newest, always
    including the newest commit overall (HEAD).
    """
    periods: dict[int, tuple[datetime, str, datetime]] = {}
    for sha, dt in commits:
        friday = anchor_friday(dt, anchor_idx)
        week_index = friday.toordinal() // 7
        period = week_index // max(1, cadence_weeks)
        prev = periods.get(period)
        # keep the latest commit in the period; label with that commit's Friday
        if prev is None or dt >= prev[2]:
            periods[period] = (friday, sha, dt)
    samples = [periods[p] for p in sorted(periods)]
    result = [(f.date().isoformat(), sha, dt) for (f, sha, dt) in samples]

    if commits:
        head_sha, head_dt = commits[-1]
        if not any(sha == head_sha for _, sha, _ in result):
            result.append((head_dt.date().isoformat(), head_sha, head_dt))
    return result


# --------------------------------------------------------------------------- #
# Extract JSON discovery + validation
# --------------------------------------------------------------------------- #
UNIFIED_SCHEMA = {"verus": "probe-verus/extract", "aeneas": "probe-aeneas/extract",
                  "lean": "probe-lean/extract"}


def find_fresh_extract(project_dir: Path, pipeline: str, since_ts: float):
    """Return (path, envelope) for the unified extract JSON written after since_ts."""
    probes = project_dir / ".verilib" / "probes"
    if not probes.is_dir():
        return None, None
    want = UNIFIED_SCHEMA[pipeline]
    prefix = {"verus": "verus_", "aeneas": "aeneas_", "lean": "lean_"}[pipeline]
    best = None
    for p in probes.glob(f"{prefix}*.json"):
        try:
            mtime = p.stat().st_mtime
            if mtime + 1e-6 < since_ts:
                continue  # stale (from a previous checkout), ignore
            with open(p, encoding="utf-8") as f:
                env = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if env.get("schema") != want:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, p, env)
    if best is None:
        return None, None
    return best[1], best[2]


def envelope_commit(env: dict) -> str | None:
    src = env.get("source")
    if isinstance(src, dict) and src.get("commit"):
        return src["commit"]
    for inp in env.get("inputs", []) or []:
        s = inp.get("source") if isinstance(inp, dict) else None
        if isinstance(s, dict) and s.get("commit"):
            return s["commit"]
    return None


def commits_match(sample_sha: str, recorded: str | None) -> bool:
    if not recorded:
        return False
    return sample_sha.startswith(recorded) or recorded.startswith(sample_sha)


def envelope_tool(env: dict):
    tool = env.get("tool", {})
    if isinstance(tool, dict):
        return tool.get("name", ""), tool.get("version", "")
    return "", ""


# --------------------------------------------------------------------------- #
# Per-pipeline extract
# --------------------------------------------------------------------------- #
def verus_setup(project_dir, args, state):
    """Install the matching Verus for this commit, deduped by release. Returns
    None on success, or a failure reason string."""
    if args.skip_verify:
        return None
    release = detect_verus_version(project_dir, args.probe_verus)
    if not release:
        return "could not detect Verus version (probe-verus --detect-version failed)"
    if release == state.get("verus_release"):
        return None
    print(f"  [setup] verus release {release} (changed) -> probe-verus setup")
    code, out = run([args.probe_verus, "setup", "--from-project", str(project_dir)],
                    timeout=args.setup_timeout)
    if code != 0:
        return f"verus setup failed (release {release}, code {code})"
    state["verus_release"] = release
    return None


def detect_lean_toolchain(project_dir: Path) -> str | None:
    """Read the pinned Lean toolchain (``lean-toolchain`` file), if present."""
    f = project_dir / "lean-toolchain"
    if f.is_file():
        return f.read_text(encoding="utf-8", errors="ignore").strip()
    return None


def lean_prepare(project_dir: Path):
    """Clean the Lean build when the toolchain changed since the last build in
    this work-clone. Cross-commit ``.lake`` cache reuse speeds up same-toolchain
    samples, but ``.olean`` compiled by one Lean version fail to import under
    another ("stale .olean" error), so we must ``lake clean`` on a toolchain
    change (the Lean analog of per-release Verus setup).

    Uses an on-disk sentinel under ``.lake`` so the decision survives across
    resume/retry runs (in-memory state would be empty on a fresh process while
    the build cache on disk is from a different toolchain).
    """
    tc = detect_lean_toolchain(project_dir)
    if not tc:
        return
    lake_dir = project_dir / ".lake"
    sentinel = lake_dir / ".vph-lean-toolchain"
    prev = sentinel.read_text(encoding="utf-8").strip() if sentinel.is_file() else None
    if prev == tc:
        return
    build_exists = (lake_dir / "build").exists()
    if prev is not None or build_exists:
        # Toolchain changed, or a pre-existing cache of unknown toolchain: clean
        # the project build and refresh dependency oleans for the new toolchain.
        print(f"  [lean] toolchain -> {tc} (changed/unknown cache) -> lake clean")
        run(["lake", "clean"], cwd=project_dir, timeout=600)
        # mathlib and similar ship a `cache get` exe that fetches prebuilt
        # oleans matching the pinned rev + toolchain; harmless no-op elsewhere.
        run(["lake", "exe", "cache", "get"], cwd=project_dir, timeout=1800)
    lake_dir.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(tc, encoding="utf-8")


def run_extract_cmd(pipeline, project_dir, args):
    """Run the extract command. Returns (code, output); code is None on timeout.

    Note: a non-zero code is NOT treated as fatal here -- probe-verus exits 1
    when verification has failures/errors, yet still writes a valid unified
    JSON. The caller decides based on the produced JSON.
    """
    if pipeline == "verus":
        cmd = [args.probe_verus, "extract", str(project_dir)]
        if args.package:
            cmd += ["-p", args.package]
        if args.skip_verify:
            cmd.append("--skip-verify")
        elif args.verus_args:
            cmd += ["--verus-args", *args.verus_args]
    elif pipeline == "aeneas":
        cmd = [args.probe_aeneas, "extract", str(project_dir)]
    else:
        return 127, f"pipeline {pipeline} not supported"
    return run(cmd, timeout=args.sample_timeout)


# --------------------------------------------------------------------------- #
# Output: JSONL append + CSV regeneration
# --------------------------------------------------------------------------- #
def load_recorded(jsonl: Path):
    """Return (all_shas, ok_shas) already present in the JSONL output."""
    all_shas, ok_shas = set(), set()
    if not jsonl.is_file():
        return all_shas, ok_shas
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sha = rec.get("commit")
            if sha:
                all_shas.add(sha)
                if rec.get("status") == "ok":
                    ok_shas.add(sha)
    return all_shas, ok_shas


def append_record(jsonl: Path, csv_path: Path, record: dict):
    """Upsert a record by commit (last write wins), so a `--retry-failed` re-run
    supersedes the prior row for that commit rather than duplicating it."""
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    kept = []
    if jsonl.is_file():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("commit") != record.get("commit"):
                kept.append(r)
    kept.append(record)
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r) + "\n")
    regenerate_csv(jsonl, csv_path)


def regenerate_csv(jsonl: Path, csv_path: Path):
    rows = []
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    rows.sort(key=lambda r: (r.get("commit_date") or "", r.get("sample_date") or ""))
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RECORD_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def blank_metrics():
    return {k: "" for k in METRIC_FIELDS}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("repo", help="GitHub URL or local path to the project repo.")
    p.add_argument("--pipeline", choices=["auto", "verus", "aeneas", "lean"], default="auto")
    p.add_argument("--project-subdir", default=".", help="Subdir containing the project (Cargo.toml / aeneas-config.yml).")
    p.add_argument("--package", help="Verus workspace package name (probe-verus -p).")
    p.add_argument("--anchor-day", choices=WEEKDAYS, default="friday")
    p.add_argument("--cadence", choices=["weekly", "biweekly", "monthly"], default="weekly",
                   help="Sampling cadence (monthly = 4-week periods).")
    p.add_argument("--cadence-weeks", type=int, default=None,
                   help="Override --cadence with an explicit period length in weeks (coarser sampling).")
    p.add_argument("--since", help="Only sample commits since this date/rev (git --since).")
    p.add_argument("--until", help="Only sample commits until this date/rev (git --until).")
    p.add_argument("--branch", help="Ref to enumerate history from (default: origin/HEAD).")
    p.add_argument("--work-clone", type=Path, help="Persistent clone dir (default: temp, reused).")
    p.add_argument("--output", type=Path, help="JSONL output path (default: data/progress-<name>.jsonl).")
    p.add_argument("--csv", type=Path, help="CSV output path (default: alongside JSONL).")
    p.add_argument("--sample-timeout", type=int, default=7200, help="Per-sample extract timeout (s).")
    p.add_argument("--setup-timeout", type=int, default=3600, help="probe-verus setup timeout (s).")
    p.add_argument("--resume", action="store_true", help="Skip commits already in the output.")
    p.add_argument("--retry-failed", action="store_true", help="With --resume, re-run non-ok samples.")
    p.add_argument("--probe-verus", default="probe-verus", help="Pinned probe-verus binary.")
    p.add_argument("--probe-aeneas", default="probe-aeneas", help="Pinned probe-aeneas binary.")
    p.add_argument("--smt-seed", type=int, default=0, help="Verus SMT random seed (determinism); -1 to disable.")
    p.add_argument("--verus-args", nargs=argparse.REMAINDER, help="Extra args forwarded to Verus (override).")
    p.add_argument("--skip-verify", action="store_true", help="Structure-only (no verified counts); for dry runs.")
    p.add_argument("--dry-run", action="store_true", help="List the samples that would be processed, then exit.")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.verus_args is None:
        args.verus_args = []
        if args.smt_seed >= 0:
            args.verus_args = ["--smt-option", f"smt.random_seed={args.smt_seed}"]

    name = repo_name(args.repo)
    jsonl = (args.output or DATA_DIR / f"progress-{name}.jsonl").resolve()
    csv_path = (args.csv or jsonl.with_suffix(".csv")).resolve()
    work_clone = args.work_clone or Path(tempfile.gettempdir()) / "verification-progress-history" / name

    work_clone = ensure_work_clone(args.repo, work_clone)
    project_dir = (work_clone / args.project_subdir).resolve()

    pipeline = args.pipeline
    if pipeline == "auto":
        pipeline = detect_pipeline(project_dir)
    print(f"[pipeline] {pipeline}  project={project_dir}")
    if pipeline == "aeneas" and args.skip_verify:
        print("[warn] --skip-verify is ignored for aeneas (probe-aeneas does not forward it)")

    ref = args.branch or default_ref(work_clone)
    commits = list_commits(work_clone, ref, args.since, args.until)
    print(f"[history] ref={ref}")
    anchor_idx = WEEKDAYS.index(args.anchor_day)
    cadence_weeks = args.cadence_weeks or {"weekly": 1, "biweekly": 2, "monthly": 4}[args.cadence]
    cadence_label = f"{cadence_weeks}-week" if args.cadence_weeks else args.cadence
    samples = bucket_samples(commits, anchor_idx, cadence_weeks)
    print(f"[samples] {len(samples)} periods from {len(commits)} commits "
          f"({cadence_label}, anchor={args.anchor_day})")

    if args.dry_run:
        for sd, sha, dt in samples:
            print(f"  {sd}  {sha[:12]}  (commit {dt.date().isoformat()})")
        print(f"[dry-run] output would be {jsonl}")
        return 0

    all_shas, ok_shas = load_recorded(jsonl) if args.resume else (set(), set())

    tool_versions = {}
    for pl, binp in (("verus", args.probe_verus), ("aeneas", args.probe_aeneas)):
        if pl == pipeline:
            code, out = run([binp, "--version"])
            tool_versions[pl] = out.strip().splitlines()[0] if out else ""

    processed = 0
    for idx, (sample_date, sha, commit_dt) in enumerate(samples, 1):
        tag = f"[{idx}/{len(samples)}] {sample_date} {sha[:12]}"
        if args.resume and sha in ok_shas:
            print(f"{tag} -> skip (already ok)")
            continue
        if args.resume and sha in all_shas and not args.retry_failed:
            print(f"{tag} -> skip (already present)")
            continue

        print(f"{tag} -> checkout + extract")
        started = time.time()
        record = {
            "repo": name, "pipeline": pipeline, "sample_date": sample_date,
            "commit": sha, "commit_date": commit_dt.isoformat(),
            "tool": "", "tool_version": tool_versions.get(pipeline, ""),
            "status": "", "reason": "", "commit_validated": False,
            "duration_sec": 0, **blank_metrics(),
        }
        try:
            git(["checkout", "-f", sha], cwd=work_clone)
        except RuntimeError as e:
            record["status"] = "checkout_failed"
            record["reason"] = str(e).splitlines()[-1][:300]
            record["duration_sec"] = round(time.time() - started, 1)
            append_record(jsonl, csv_path, record)
            print(f"     {record['status']}: {record['reason']}")
            continue

        if pipeline == "verus":
            setup_reason = verus_setup(project_dir, args, _VERUS_STATE)
            if setup_reason:
                record["status"] = "setup_failed"
                record["reason"] = setup_reason[:300]
                record["duration_sec"] = round(time.time() - started, 1)
                append_record(jsonl, csv_path, record)
                print(f"     {record['status']}: {record['reason']}")
                continue
        elif pipeline == "aeneas":
            lean_prepare(project_dir)

        # Freshness anchor: only JSON written by THIS extract counts (excludes
        # any committed .verilib JSON that `git checkout` just restored).
        ext_start = time.time()
        code, out = run_extract_cmd(pipeline, project_dir, args)
        record["duration_sec"] = round(time.time() - started, 1)

        path, env = find_fresh_extract(project_dir, pipeline, ext_start)
        if env is None:
            record["status"] = "timeout" if code is None else "extract_failed"
            tail = "\n".join((out or "").splitlines()[-6:])
            record["reason"] = (f"no fresh unified JSON; exit={code}; {tail}")[:300]
            append_record(jsonl, csv_path, record)
            print(f"     {record['status']}: exit={code}")
            continue

        rec_commit = envelope_commit(env)
        record["commit_validated"] = commits_match(sha, rec_commit)
        tname, tver = envelope_tool(env)
        record["tool"] = tname
        record["tool_version"] = tver or record["tool_version"]

        if rec_commit and not record["commit_validated"]:
            record["status"] = "commit_mismatch"
            record["reason"] = f"extract source.commit {rec_commit} != sample {sha[:12]}"
            append_record(jsonl, csv_path, record)
            print(f"     {record['status']}: {record['reason']}")
            continue

        metrics = count_colors(env)
        for k in METRIC_FIELDS:
            record[k] = metrics[k]
        # Classify: exit 0 => verify ran cleanly. Non-zero but dynamic statuses
        # present (some failed/verified/unverified) => verify ran, record it.
        # Non-zero with only none/trusted => verify did not run (build/toolchain
        # error) -> a visible gap, not a real "0 verified" data point.
        dynamic = metrics["red"] + metrics["yellow"] + metrics["light_green"] + metrics["dark_green"]
        if args.skip_verify or code == 0 or dynamic > 0:
            record["status"] = "ok"
            record["reason"] = "; ".join(metrics["warnings"])
            if code not in (0, None):
                record["reason"] = (record["reason"] + f"; extract exit={code}").strip("; ")
            processed += 1
        else:
            record["status"] = "verify_error"
            record["reason"] = f"verify produced no statuses (exit={code}); likely build/toolchain error"
        append_record(jsonl, csv_path, record)
        print(f"     {record['status']}: tracked={metrics['tracked']} verified={metrics['verified']} "
              f"v+t={metrics['verified_trusted']} translated={metrics['translated']} "
              f"({record['duration_sec']}s)")

    print(f"[done] processed {processed} new sample(s); output: {jsonl}")
    print(f"       CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
