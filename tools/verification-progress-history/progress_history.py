#!/usr/bin/env python3
"""Reconstruct a verification project's progress over git history.

Samples one commit per period (default: weekly, last commit on/before each
Friday), checks it out in a persistent work-clone, runs the matching probe
``extract`` (which runs the real verifier), and records the full count-colors
metric set to a JSONL time series, upserted by commit (plus a regenerated CSV). The
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
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from blueprint_progress import count_blueprint
from colors import count_colors

# Outputs live next to the tool, one folder per repo: data/<name>/.
DATA_DIR = Path(__file__).resolve().parent / "data"

# Cross-sample state (e.g. last-installed Verus release for setup-dedup).
_VERUS_STATE: dict = {}
# Cross-sample state for leanblueprint (managed bin dir + last probe-lean version).
_LEANBP_STATE: dict = {}

# Fixed column order for the CSV / JSONL records.
METRIC_FIELDS = [
    "grey",
    "white",
    "red",
    "yellow",
    "light_green",
    "dark_green",
    "purple",
    "exec_total",
    "dot_red",
    "dot_yellow",
    "dot_green",
    "art_total",
    "tracked",
    "verified",
    "verified_trusted",
    "translated",
]
# probe-leanblueprint two-axis progress metrics; blank for the colour pipelines
# (same convention as `translated` being Aeneas-only). Prefixed `bp_` in the
# record; count_blueprint returns them unprefixed.
BLUEPRINT_METRIC_KEYS = [
    "nodes_total",
    "nodes_bound",
    "nodes_planned",
    "nodes_decl_missing",
    "def_total",
    "def_formalized",
    "thm_total",
    "thm_formalized",
    "thm_proved",
    "thm_proved_confirmed",
    # Per-kind probe-lean proof-status partition over the formalized nodes
    # (the combined-atoms chart). See blueprint_progress._kind_buckets.
    "def_verified",
    "def_trusted",
    "def_in_progress",
    "def_failed",
    "def_unrealized",
    "thm_verified",
    "thm_trusted",
    "thm_in_progress",
    "thm_failed",
    "thm_unrealized",
]
BLUEPRINT_FIELDS = [f"bp_{k}" for k in BLUEPRINT_METRIC_KEYS]
RECORD_FIELDS = (
    [
        "repo",
        "pipeline",
        "sample_date",
        "commit",
        "commit_date",
        "tool",
        "tool_version",
        "status",
        "reason",
        "commit_validated",
        "duration_sec",
    ]
    + METRIC_FIELDS
    + BLUEPRINT_FIELDS
)

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Absolute paths scrubbed from recorded `reason` strings before they are written
# (the history files are committed, so must stay machine-independent). Populated
# per run in main(); empty otherwise, so scrubbing is a no-op in unit tests.
_REDACT_PATHS: set[str] = set()


def _scrub_paths(text: str, *paths) -> str:
    """Replace absolute work-clone / project / bin paths in recorded output with a
    stable ``<path>`` placeholder. Longest first, so a nested project dir is
    scrubbed before its parent clone."""
    for p in sorted({str(x) for x in paths if x}, key=len, reverse=True):
        text = text.replace(p, "<path>")
    return text


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + ``os.replace`` so an interrupted run cannot
    truncate the committed history file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Subprocess helper with process-group timeout kill
# --------------------------------------------------------------------------- #
def run(cmd, cwd=None, timeout=None, env=None):
    """Run a command, capturing combined output. Returns (code, output).

    ``code`` is None on timeout. The child runs in its own process group so a
    hung tool (e.g. Charon) and all its children are killed on timeout.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
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
def _has_verso_blueprint(project_dir: Path) -> bool:
    """True if a lakefile in the project (or its ``docs/`` subdir) declares the
    versoBlueprint dependency -- the signal probe-leanblueprint uses to pick the
    Verso adapter. Line comments (``#`` in TOML, ``--`` in Lean) are stripped
    first so a mention in a comment doesn't mis-detect the pipeline."""
    for base in (project_dir, project_dir / "docs"):
        for name in ("lakefile.toml", "lakefile.lean"):
            f = base / name
            if not f.is_file():
                continue
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                code = line.split("#", 1)[0].split("--", 1)[0]
                if "versoBlueprint" in code:
                    return True
    return False


def detect_pipeline(project_dir: Path) -> str:
    if (project_dir / "aeneas-config.yml").is_file():
        return "aeneas"
    if (
        _has_verso_blueprint(project_dir)
        or (project_dir / "blueprint" / "src" / "web.tex").is_file()
    ):
        return "leanblueprint"
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
    code, out = run(
        [probe_verus, "setup", "--from-project", str(project_dir), "--detect-version"], timeout=180
    )
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


def anchor_weekday(dt: datetime, anchor_idx: int) -> datetime:
    """The anchor-day (default Wednesday) on or after dt's date, at end of day UTC."""
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
        anchor = anchor_weekday(dt, anchor_idx)
        week_index = anchor.toordinal() // 7
        period = week_index // max(1, cadence_weeks)
        prev = periods.get(period)
        # keep the latest commit in the period; label with that commit's anchor-day
        if prev is None or dt >= prev[2]:
            periods[period] = (anchor, sha, dt)
    samples = [periods[p] for p in sorted(periods)]
    result = [(a.date().isoformat(), sha, dt) for (a, sha, dt) in samples]

    if commits:
        head_sha, head_dt = commits[-1]
        if not any(sha == head_sha for _, sha, _ in result):
            result.append((head_dt.date().isoformat(), head_sha, head_dt))
    return result


def resolve_commits(work_clone: Path, refs: list[str], anchor_idx: int):
    """Resolve explicit commit refs to samples, sorted oldest -> newest.

    Each ref is validated and expanded to a full SHA (fetching once if it is not
    present yet); the sample_date reuses the same anchor-day label the periodic
    path produces, so re-running a commit upserts cleanly onto the existing grid.
    Returns [(sample_date_iso, sha, commit_datetime)].
    """
    resolved, seen = [], set()
    for ref in refs:
        try:
            sha = git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=work_clone)
        except RuntimeError:
            git(["fetch", "--all", "--tags", "--quiet"], cwd=work_clone)
            sha = git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=work_clone)
        if sha in seen:  # same commit passed twice / short+full of one commit
            continue
        seen.add(sha)
        iso = git(["show", "-s", "--format=%cI", sha], cwd=work_clone)
        dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        resolved.append((sha, dt))
    resolved.sort(key=lambda c: c[1])
    return [(anchor_weekday(dt, anchor_idx).date().isoformat(), sha, dt) for sha, dt in resolved]


# --------------------------------------------------------------------------- #
# Extract JSON discovery + validation
# --------------------------------------------------------------------------- #
UNIFIED_SCHEMA = {
    "verus": "probe-verus/extract",
    "aeneas": "probe-aeneas/extract",
    "lean": "probe-lean/extract",
    "leanblueprint": "probe-leanblueprint/extract",
}


def find_fresh_extract(project_dir: Path, pipeline: str, since_ts: float):
    """Return (path, envelope) for the unified extract JSON written after since_ts."""
    probes = project_dir / ".verilib" / "probes"
    if not probes.is_dir():
        return None, None
    want = UNIFIED_SCHEMA[pipeline]
    prefix = {
        "verus": "verus_",
        "aeneas": "aeneas_",
        "lean": "lean_",
        "leanblueprint": "leanblueprint_",
    }[pipeline]
    best = None
    for p in probes.glob(f"{prefix}*.json"):
        try:
            mtime = p.stat().st_mtime
            # Stale = written by a previous checkout, which is always many
            # seconds/minutes old (a sample re-verifies). Allow a 2s grace so a
            # coarse-resolution mtime (e.g. 1s on some filesystems) on a file
            # written just after `since_ts` isn't misread as stale.
            if mtime < since_ts - 2:
                continue
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
    code, out = run(
        [args.probe_verus, "setup", "--from-project", str(project_dir)], timeout=args.setup_timeout
    )
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


def _lean_version_from_toolchain(tc: str | None) -> str | None:
    """``leanprover/lean4:v4.30.0`` -> ``v4.30.0`` (keeps an ``-rcN`` suffix)."""
    if not tc:
        return None
    m = re.search(r"v\d+\.\d+\.\d+(?:-rc\d+)?", tc)
    return m.group(0) if m else None


def leanblueprint_setup(project_dir, args, state):
    """Point ``probe-lean`` at the binary matching this commit's Lean toolchain.

    probe-lean reads ``.olean``s, whose binary format is Lean-version-specific,
    so the probe-lean used at each sample must match the target's
    ``lean-toolchain`` -- unlike Verus/Aeneas, one pinned probe cannot span a
    toolchain change. Versioned binaries are expected as
    ``<probe-lean-dir>/probe-lean-v<version>`` (the standard per-version install
    layout). We expose the match as ``probe-lean`` on a tool-managed PATH prefix
    (never touching the user's own ``probe-lean`` symlink), refreshed per sample.
    probe-leanblueprint then invokes bare ``probe-lean`` and picks it up.
    Returns None on success, or a failure reason string."""
    tc = detect_lean_toolchain(project_dir)
    if not tc:
        return "no lean-toolchain file in the project; cannot pick a probe-lean version"
    ver = _lean_version_from_toolchain(tc)
    if not ver:
        return f"could not parse a Lean version from lean-toolchain {tc!r}"
    if not args.probe_lean_dir:
        return "probe-lean not on PATH; install it or pass --probe-lean-dir"
    binary = args.probe_lean_dir / f"probe-lean-{ver}"
    if not binary.is_file():
        return f"no probe-lean-{ver} at {binary}; install it or set --probe-lean-dir"
    link = state["managed_bin"] / "probe-lean"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(binary.resolve())
    if ver != state.get("probe_lean_version"):
        print(f"  [setup] probe-lean -> probe-lean-{ver} (matches {tc})")
        state["probe_lean_version"] = ver
    return None


def _norm_url(u: str | None) -> str | None:
    if not u:
        return None
    return u.strip().rstrip("/").removesuffix(".git").lower()


def _last_line(s: str) -> str:
    """Last non-empty line of ``s`` (for concise one-line warnings), or ''."""
    lines = [ln.strip() for ln in (s or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _aeneas_crate_dir(project_dir: Path) -> str:
    """Read ``crate.dir`` from aeneas-config.yml (stdlib-only, no PyYAML)."""
    cfg = project_dir / "aeneas-config.yml"
    if not cfg.is_file():
        return "."
    in_crate = False
    for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
        if re.match(r"^\S", line):  # top-level key -> leaving any block
            in_crate = line.strip().startswith("crate:")
            continue
        if in_crate:
            m = re.match(r"\s+dir:\s*[\"']?([^\"'#\n]+?)[\"']?\s*$", line)
            if m:
                return m.group(1).strip()
    return "."


def lean_clear_extract_cache(project_dir: Path):
    """Delete untracked probe caches so each sample regenerates them from ITS
    commit. probe-aeneas reuses an existing ``<crate>/data/charon.llbc`` and
    probe-rust reuses ``index.scip[.json]`` ("Using cached ..."), which would
    otherwise carry an earlier commit's Rust atoms into every later sample."""
    data = project_dir / _aeneas_crate_dir(project_dir) / "data"
    for name in ("charon.llbc", "index.scip", "index.scip.json"):
        f = data / name
        try:
            if f.is_file():
                f.unlink()
        except OSError:
            pass


def leanblueprint_clear_render_cache(project_dir: Path):
    """Delete the Verso render output so each sample re-renders from ITS commit.

    probe-leanblueprint's zero-config path discovers manifests under
    ``<render_root>/_out/site`` and only runs ``lake exe vbp build`` when none
    exist -- so a reused work-clone would serve an earlier commit's blueprint to
    every later sample. The extract's ``source.commit`` is git-derived, so the
    commit-match guard would NOT catch this; we must drop the render ourselves.
    Cover the project root and ``docs/`` (either may hold the versoBlueprint
    lakefile). Pure render output, safe to remove."""
    for base in (project_dir, project_dir / "docs"):
        site = base / "_out" / "site"
        if site.exists():
            shutil.rmtree(site, ignore_errors=True)


def lean_sync_deps(project_dir: Path):
    """Check out each git dependency at its manifest-pinned rev.

    Two problems this solves for historical samples in a reused work-clone:
      * ``lake`` cannot fetch a now-unadvertised historical rev (an old branch
        tip that moved/was deleted): its own ``git fetch`` won't retrieve it and
        the build dies with "fatal: unable to read tree <rev>".
      * ``lake clean`` / ``cache get`` reset dep clones back to their default
        branch, so fetching earlier in the run isn't enough.

    We fetch the exact rev by SHA (GitHub serves reachable-but-unadvertised SHAs)
    and check the dep out ourselves. Lake then sees the dep already at the pinned
    rev and builds it without re-fetching. Packages are matched to manifest
    entries by remote URL (dir names don't always equal manifest names, e.g.
    ``ProofWidgets4`` -> ``proofwidgets``). Runs LAST in ``lean_prepare`` so it
    is not undone by a preceding lake clean/cache-get.
    """
    manifest = project_dir / "lake-manifest.json"
    pkgs = project_dir / ".lake" / "packages"
    if not (manifest.is_file() and pkgs.is_dir()):
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return
    want = {
        _norm_url(p.get("url")): p.get("rev")
        for p in data.get("packages", [])
        if p.get("url") and p.get("rev")
    }
    for d in sorted(pkgs.iterdir()):
        if not (d / ".git").exists():
            continue
        code, url = run(["git", "-C", str(d), "remote", "get-url", "origin"])
        rev = want.get(_norm_url(url)) if code == 0 else None
        if not rev:
            continue
        # Only intervene when the rev's TREE is missing (lake can't fetch this
        # now-unadvertised historical rev). If the tree is present, lake resolves
        # it normally -- do NOT force-checkout, or we'd churn deps like
        # ProofWidgets whose prebuilt JS is keyed to a specific rev's source hash
        # ("ProofWidgets not up-to-date"). We check ^{tree} (not just ^{commit})
        # because lake's dep clones can be shallow/partial.
        have, _ = run(["git", "-C", str(d), "cat-file", "-e", f"{rev}^{{tree}}"])
        if have == 0:
            continue
        print(f"  [lean] fetch+checkout {d.name} @ {rev[:12]} (unadvertised rev)")
        code, _ = run(["git", "-C", str(d), "fetch", "--quiet", "origin", rev], timeout=900)
        if code != 0:  # server may refuse fetch-by-sha; fall back to full fetch
            run(["git", "-C", str(d), "fetch", "--quiet", "--all", "--tags"], timeout=1800)
        code, _ = run(["git", "-C", str(d), "checkout", "--detach", "--force", rev])
        if code != 0:
            print(f"  [lean] WARNING: could not check out {d.name} @ {rev[:12]}")


# --------------------------------------------------------------------------- #
# Dependency-build cache (leanblueprint): reuse compiled deps across runs
# --------------------------------------------------------------------------- #
def _dep_cache_key(project_dir: Path, tc: str) -> str | None:
    """Cache key for the dependency build: a pure function of the Lean toolchain
    and the full lake manifest (which pins every dep's rev). Two samples with the
    same (toolchain, manifest) have byte-identical dep oleans, so their compiled
    deps are interchangeable -- e.g. every secure-messaging v4.30 commit pins the
    same VCVio rev, so one build serves them all.

    Returns None when there is no ``lake-manifest.json``: keying on the toolchain
    alone would collide different dependency sets on the same Lean version, so we
    refuse to cache rather than risk replaying the wrong build."""
    manifest = project_dir / "lake-manifest.json"
    if not manifest.is_file():
        return None
    mtext = manifest.read_text(encoding="utf-8", errors="ignore")
    digest = hashlib.sha256(f"{tc}\n{mtext}".encode()).hexdigest()[:16]
    return f"{_lean_version_from_toolchain(tc) or 'lean'}-{digest}"


def _dep_pkg_build_dirs(project_dir: Path) -> list[Path]:
    """Package dirs under ``.lake/packages`` that have a built ``.lake/build``."""
    pkgs = project_dir / ".lake" / "packages"
    if not pkgs.is_dir():
        return []
    return [d for d in sorted(pkgs.iterdir()) if (d / ".lake" / "build").is_dir()]


def restore_dep_cache(project_dir: Path, cache_dir: Path, key: str) -> bool:
    """Restore cached dependency build trees for ``key``. Returns True on a hit.

    Copies with ``cp -a`` to preserve the mtimes lake's trace-checking relies on,
    so restored deps are seen as up to date and are not recompiled."""
    src = Path(cache_dir) / key
    if not src.is_dir():
        return False
    pkgs = project_dir / ".lake" / "packages"
    if not pkgs.is_dir():
        # Fresh clone: dep sources not fetched yet. Restoring a build into a
        # non-existent package checkout would leave lake to reconcile a
        # half-materialized package; skip so `cache get` + a source build runs.
        return False
    restored = 0
    for entry in sorted(src.iterdir()):
        cached_build = entry / "build"
        pkg_dir = pkgs / entry.name
        # Only restore into a real package checkout (source present); a build with
        # no source dir is worse than no cache.
        if not cached_build.is_dir() or not pkg_dir.is_dir():
            continue
        dest = pkg_dir / ".lake" / "build"
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        code, out = run(["cp", "-a", str(cached_build), str(dest)])
        if code != 0:
            print(f"  [lean][warn] dep-cache restore failed for {entry.name}: {_last_line(out)}")
            return False
        restored += 1
    return restored > 0


def save_dep_cache(project_dir: Path, cache_dir: Path, key: str) -> None:
    """Snapshot dependency build trees to the cache under ``key`` (idempotent: a
    no-op if the key is already cached). Written to a temp dir then renamed, so an
    interrupted snapshot never leaves a half-populated entry."""
    dest = Path(cache_dir) / key
    if dest.exists():
        return
    deps = _dep_pkg_build_dirs(project_dir)
    if not deps:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(cache_dir) / f".{key}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    for d in deps:
        target = tmp / d.name / "build"
        target.parent.mkdir(parents=True, exist_ok=True)
        code, out = run(["cp", "-a", str(d / ".lake" / "build"), str(target)])
        if code != 0:
            print(f"  [lean][warn] dep-cache save failed for {d.name}: {_last_line(out)}")
            shutil.rmtree(tmp, ignore_errors=True)
            return
    try:
        os.replace(tmp, dest)
        print(f"  [lean] cached dep builds ({key})")
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)


def lean_prepare(project_dir: Path, dep_cache_dir: Path | None = None, state: dict | None = None):
    """Prepare the Lean/Aeneas build for a fresh sample in the shared work-clone.

    Two cross-commit hazards, both handled here:
      * Stale ``.olean``: a build compiled by one Lean toolchain can't be imported
        by another. On a toolchain change we ``lake clean`` + refresh the Mathlib
        cache. An on-disk sentinel records the last toolchain so the decision
        survives resume/retry runs (in-memory state would be empty on a fresh
        process while the on-disk cache is from a different toolchain).
      * Module collisions: Aeneas regenerates the root project's Lean sources
        every commit, so on same-toolchain samples we drop the ROOT project build
        (``.lake/build``) so regenerated modules don't collide with stale oleans
        ("environment already contains <module>").
      * Missing / moved dep revs: the manifest re-pins dep revs per commit and
        lake can't fetch unadvertised historical revs. ``lean_sync_deps`` fetches
        + checks out only such deps at their pinned rev. It runs BEFORE ``cache
        get`` (so lake's dep resolution doesn't die on the missing rev) and AGAIN
        after (in case a lake step reset it) -- and is surgical, so advertised
        deps like ProofWidgets (whose prebuilt JS is keyed to a rev) are left
        untouched.
    """
    tc = detect_lean_toolchain(project_dir)
    if not tc:
        return
    lake_dir = project_dir / ".lake"
    sentinel = lake_dir / ".vph-lean-toolchain"
    prev = sentinel.read_text(encoding="utf-8").strip() if sentinel.is_file() else None
    key = _dep_cache_key(project_dir, tc) if dep_cache_dir else None
    if state is not None and key:
        state["dep_cache_key"] = key
    if prev != tc:
        # Toolchain changed (or first build in this clone): clean any prior build
        # and restore/(re)fetch prebuilt oleans for this toolchain.
        if (lake_dir / "build").exists():
            print(f"  [lean] toolchain -> {tc} (changed) -> lake clean")
            code, out = run(["lake", "clean"], cwd=project_dir, timeout=600)
            if code != 0:
                print(f"  [lean][warn] lake clean exit={code}: {_last_line(out)}")
        # Make unadvertised dep revs available before cache-get resolves deps,
        # otherwise resolution dies ("unable to read tree") and oleans aren't
        # fetched (forcing a slow Mathlib source build).
        lean_sync_deps(project_dir)
        # Prefer a full dependency-build restore: it skips both `cache get` and the
        # from-source compile of cacheless deps (e.g. VCVio, which alone can be an
        # hour+). Falls back to `cache get` (mathlib) + a source build on a miss;
        # the result is snapshotted after a successful extract (see the main loop).
        restored = bool(dep_cache_dir and key) and restore_dep_cache(
            project_dir, dep_cache_dir, key
        )
        if restored:
            print(f"  [lean] restored dep builds from cache ({key})")
        else:
            # mathlib ships a `cache get` exe that fetches prebuilt oleans matching
            # the pinned rev + toolchain; harmless no-op elsewhere. Not fatal on
            # failure (lake falls back to a source build) but worth surfacing,
            # since it turns a fast sample into a very slow one.
            print(f"  [lean] lake exe cache get ({tc})")
            code, out = run(["lake", "exe", "cache", "get"], cwd=project_dir, timeout=1800)
            if code != 0:
                print(
                    f"  [lean][warn] lake exe cache get exit={code} "
                    f"(may force a slow source build): {_last_line(out)}"
                )
    else:
        # Same toolchain: keep dep/Mathlib builds (expensive), but drop the ROOT
        # project build so this commit's regenerated modules rebuild cleanly.
        build = lake_dir / "build"
        if build.exists():
            print(f"  [lean] same toolchain {tc} -> drop root .lake/build (fresh regen)")
            shutil.rmtree(build, ignore_errors=True)
    # Final: re-pin unadvertised dep revs in case a lake step reset them.
    lean_sync_deps(project_dir)
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
    elif pipeline == "leanblueprint":
        cmd = [args.probe_leanblueprint, "extract", str(project_dir)]
        if args.verso_render_cmd:
            cmd += ["--verso-render-cmd", args.verso_render_cmd]
    else:
        return 127, f"pipeline {pipeline} not supported"
    return run(cmd, timeout=args.sample_timeout)


# --------------------------------------------------------------------------- #
# Output: JSONL append + CSV regeneration
# --------------------------------------------------------------------------- #
def _read_jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file into records, skipping blank and corrupt lines."""
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def load_recorded(jsonl: Path):
    """Return (all_shas, ok_shas) already present in the JSONL output."""
    all_shas, ok_shas = set(), set()
    for rec in _read_jsonl(jsonl):
        sha = rec.get("commit")
        if sha:
            all_shas.add(sha)
            if rec.get("status") == "ok":
                ok_shas.add(sha)
    return all_shas, ok_shas


def append_record(jsonl: Path, csv_path: Path, record: dict):
    """Upsert a record by commit (last write wins), so a `--retry-failed` re-run
    supersedes the prior row for that commit rather than duplicating it.

    This rewrites the whole JSONL (and CSV) per sample -- O(n) in file size. That
    is deliberate: upsert-by-commit needs the existing rows, and n is small (one
    row per sampled period, tens over a multi-year history) while each sample
    costs minutes of real verification, so the rewrite is never the bottleneck."""
    if record.get("reason") and _REDACT_PATHS:
        record["reason"] = _scrub_paths(record["reason"], *_REDACT_PATHS)
    kept = [r for r in _read_jsonl(jsonl) if r.get("commit") != record.get("commit")]
    kept.append(record)
    _atomic_write(jsonl, "".join(json.dumps(r) + "\n" for r in kept))
    regenerate_csv(jsonl, csv_path)


def regenerate_csv(jsonl: Path, csv_path: Path):
    rows = _read_jsonl(jsonl)
    rows.sort(key=lambda r: (r.get("commit_date") or "", r.get("sample_date") or ""))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=RECORD_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    _atomic_write(csv_path, buf.getvalue())


def blank_metrics():
    return {k: "" for k in METRIC_FIELDS + BLUEPRINT_FIELDS}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args(argv):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("repo", help="GitHub URL or local path to the project repo.")
    p.add_argument(
        "--pipeline",
        choices=["auto", "verus", "aeneas", "lean", "leanblueprint"],
        default="auto",
    )
    p.add_argument(
        "--project-subdir",
        default=".",
        help="Subdir containing the project (Cargo.toml / aeneas-config.yml).",
    )
    p.add_argument("--package", help="Verus workspace package name (probe-verus -p).")
    p.add_argument(
        "--anchor-day",
        choices=WEEKDAYS,
        default="wednesday",
        help="Weekday the sample-date grid snaps to (default: wednesday).",
    )
    p.add_argument(
        "--cadence",
        choices=["weekly", "biweekly", "monthly"],
        default="weekly",
        help="Sampling cadence (monthly = 4-week periods).",
    )
    p.add_argument(
        "--cadence-weeks",
        type=int,
        default=None,
        help="Override --cadence with an explicit period length in weeks (coarser sampling).",
    )
    p.add_argument(
        "--commit",
        action="append",
        metavar="REF",
        help="Sample exactly this commit instead of walking history by cadence "
        "(repeatable). Each is upserted into the JSONL by commit. Overrides "
        "--since/--until/--cadence/--branch and always (re)runs the named commits.",
    )
    p.add_argument("--since", help="Only sample commits since this date/rev (git --since).")
    p.add_argument("--until", help="Only sample commits until this date/rev (git --until).")
    p.add_argument("--branch", help="Ref to enumerate history from (default: origin/HEAD).")
    p.add_argument("--work-clone", type=Path, help="Persistent clone dir (default: temp, reused).")
    p.add_argument(
        "--output", type=Path, help="JSONL output path (default: data/<name>/progress.jsonl)."
    )
    p.add_argument("--csv", type=Path, help="CSV output path (default: alongside JSONL).")
    p.add_argument(
        "--sample-timeout", type=int, default=7200, help="Per-sample extract timeout (s)."
    )
    p.add_argument("--setup-timeout", type=int, default=3600, help="probe-verus setup timeout (s).")
    p.add_argument("--resume", action="store_true", help="Skip commits already in the output.")
    p.add_argument(
        "--retry-failed", action="store_true", help="With --resume, re-run non-ok samples."
    )
    p.add_argument("--probe-verus", default="probe-verus", help="Pinned probe-verus binary.")
    p.add_argument("--probe-aeneas", default="probe-aeneas", help="Pinned probe-aeneas binary.")
    p.add_argument(
        "--probe-leanblueprint",
        default="probe-leanblueprint",
        help="Pinned probe-leanblueprint binary.",
    )
    p.add_argument(
        "--probe-lean-dir",
        type=Path,
        default=None,
        help="Directory of per-version probe-lean binaries (probe-lean-v<ver>); "
        "default: the directory of `probe-lean` on PATH. The leanblueprint "
        "pipeline selects the one matching each commit's lean-toolchain, since "
        "probe-lean reads version-specific .oleans.",
    )
    p.add_argument(
        "--dep-cache-dir",
        type=Path,
        default=None,
        help="Directory for a persistent dependency-build cache (leanblueprint). "
        "When set, compiled dep builds (e.g. VCVio) are snapshotted per (Lean "
        "toolchain, lake manifest) and restored on later samples/runs instead of "
        "recompiling. Trades disk for time; safe to delete anytime.",
    )
    p.add_argument(
        "--verso-render-cmd",
        help="Override the Verso render command probe-leanblueprint runs "
        "(via sh -c in the blueprint root), e.g. scripts/render-docs-site.sh.",
    )
    p.add_argument(
        "--smt-seed",
        type=int,
        default=0,
        help="Verus SMT random seed (determinism); -1 to disable.",
    )
    p.add_argument(
        "--verus-args", nargs=argparse.REMAINDER, help="Extra args forwarded to Verus (override)."
    )
    p.add_argument(
        "--skip-verify",
        action="store_true",
        help="Structure-only (no verified counts); for dry runs.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="List the samples that would be processed, then exit.",
    )
    p.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero if any sample processed this run is not `ok` "
        "(for cron/monitoring). Samples skipped by --resume don't count.",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.verus_args is None:
        args.verus_args = []
        if args.smt_seed >= 0:
            args.verus_args = ["--smt-option", f"smt.random_seed={args.smt_seed}"]

    name = repo_name(args.repo)
    jsonl = (args.output or DATA_DIR / name / "progress.jsonl").resolve()
    csv_path = (args.csv or jsonl.with_suffix(".csv")).resolve()
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    work_clone = (
        args.work_clone or Path(tempfile.gettempdir()) / "verification-progress-history" / name
    )

    work_clone = ensure_work_clone(args.repo, work_clone)
    project_dir = (work_clone / args.project_subdir).resolve()

    # Scrub these absolute paths from recorded `reason` strings (committed data
    # must be machine-independent). More may be added per pipeline below.
    _REDACT_PATHS.clear()
    _REDACT_PATHS.update({str(work_clone), str(project_dir)})

    pipeline = args.pipeline
    if pipeline == "auto":
        pipeline = detect_pipeline(project_dir)
    if pipeline not in ("verus", "aeneas", "leanblueprint"):
        # `lean` can be requested or auto-detected, but extract is only wired for
        # verus/aeneas/leanblueprint. Fail fast with a clear message instead of a
        # late, per-sample `extract_failed`. Charon/Aeneas Lean projects are
        # sampled via `aeneas`; blueprint projects via `leanblueprint`.
        print(
            f"[error] --pipeline {pipeline} is not supported (verus/aeneas/leanblueprint; "
            f"Charon-based Lean projects use --pipeline aeneas).",
            file=sys.stderr,
        )
        return 2
    print(f"[pipeline] {pipeline}  project={project_dir}")
    if pipeline == "aeneas" and args.skip_verify:
        print("[warn] --skip-verify is ignored for aeneas (probe-aeneas does not forward it)")
    if pipeline == "leanblueprint":
        # probe-lean is Lean-version-specific; select the matching binary per
        # sample via a managed PATH prefix (see leanblueprint_setup). Resolve the
        # binary directory BEFORE prepending, so we find the user's real install.
        if args.probe_lean_dir is None:
            which = shutil.which("probe-lean")
            args.probe_lean_dir = Path(which).resolve().parent if which else None
        managed = work_clone.parent / f".vph-probe-lean-bin-{name}"
        managed.mkdir(parents=True, exist_ok=True)
        _LEANBP_STATE.clear()
        _LEANBP_STATE["managed_bin"] = managed
        os.environ["PATH"] = f"{managed}{os.pathsep}{os.environ.get('PATH', '')}"
        if args.probe_lean_dir:
            _REDACT_PATHS.add(str(args.probe_lean_dir))  # setup_failed reasons cite this
        print(f"[leanblueprint] probe-lean selected per sample from {args.probe_lean_dir}")

    anchor_idx = WEEKDAYS.index(args.anchor_day)
    explicit = bool(args.commit)
    if explicit:
        try:
            samples = resolve_commits(work_clone, args.commit, anchor_idx)
        except RuntimeError as e:
            print(f"[error] {e}", file=sys.stderr)
            return 2
        print(f"[samples] {len(samples)} explicit commit(s)")
    else:
        ref = args.branch or default_ref(work_clone)
        commits = list_commits(work_clone, ref, args.since, args.until)
        print(f"[history] ref={ref}")
        cadence_weeks = (
            args.cadence_weeks or {"weekly": 1, "biweekly": 2, "monthly": 4}[args.cadence]
        )
        cadence_label = f"{cadence_weeks}-week" if args.cadence_weeks else args.cadence
        samples = bucket_samples(commits, anchor_idx, cadence_weeks)
        print(
            f"[samples] {len(samples)} periods from {len(commits)} commits "
            f"({cadence_label}, anchor={args.anchor_day})"
        )

    if args.dry_run:
        for sd, sha, dt in samples:
            print(f"  {sd}  {sha[:12]}  (commit {dt.date().isoformat()})")
        print(f"[dry-run] output would be {jsonl}")
        return 0

    all_shas, ok_shas = load_recorded(jsonl) if args.resume else (set(), set())

    tool_versions = {}
    for pl, binp in (
        ("verus", args.probe_verus),
        ("aeneas", args.probe_aeneas),
        ("leanblueprint", args.probe_leanblueprint),
    ):
        if pl == pipeline:
            code, out = run([binp, "--version"])
            tool_versions[pl] = out.strip().splitlines()[0] if out else ""

    processed = 0
    failed = 0  # non-ok samples actually run this invocation (for --fail-on-error)
    for idx, (sample_date, sha, commit_dt) in enumerate(samples, 1):
        tag = f"[{idx}/{len(samples)}] {sample_date} {sha[:12]}"
        # Explicit --commit always (re)runs; resume-skip only applies to the
        # periodic history walk.
        if not explicit and args.resume and sha in ok_shas:
            print(f"{tag} -> skip (already ok)")
            continue
        if not explicit and args.resume and sha in all_shas and not args.retry_failed:
            print(f"{tag} -> skip (already present)")
            continue

        print(f"{tag} -> checkout + extract")
        started = time.time()
        record = {
            "repo": name,
            "pipeline": pipeline,
            "sample_date": sample_date,
            "commit": sha,
            "commit_date": commit_dt.isoformat(),
            # Default the tool from the pipeline so failure records stay
            # consistent (not blank `tool` with a populated `tool_version`);
            # a successful extract overwrites this from the envelope.
            "tool": {
                "verus": "probe-verus",
                "aeneas": "probe-aeneas",
                "leanblueprint": "probe-leanblueprint",
            }.get(pipeline, ""),
            "tool_version": tool_versions.get(pipeline, ""),
            "status": "",
            "reason": "",
            "commit_validated": False,
            "duration_sec": 0,
            **blank_metrics(),
        }
        try:
            git(["checkout", "-f", sha], cwd=work_clone)
            if pipeline == "aeneas":
                # Force per-commit regeneration of the untracked probe caches
                # (charon.llbc + SCIP index): otherwise probe reuses a stale one
                # from an earlier commit ("Using cached Charon LLBC" / "Found
                # existing SCIP JSON"). Targeted removal only touches these pure
                # caches -- a broad ``git clean`` would also delete gitignored
                # build outputs (e.g. *_Template.lean).
                lean_clear_extract_cache(project_dir)
            elif pipeline == "leanblueprint":
                # Drop the previous sample's Verso render so this commit's
                # blueprint is rendered fresh (see the function docstring).
                leanblueprint_clear_render_cache(project_dir)
        except RuntimeError as e:
            record["status"] = "checkout_failed"
            record["reason"] = str(e).splitlines()[-1][:300]
            record["duration_sec"] = round(time.time() - started, 1)
            append_record(jsonl, csv_path, record)
            failed += 1
            print(f"     {record['status']}: {record['reason']}")
            continue

        if pipeline == "verus":
            setup_reason = verus_setup(project_dir, args, _VERUS_STATE)
            if setup_reason:
                record["status"] = "setup_failed"
                record["reason"] = setup_reason[:300]
                record["duration_sec"] = round(time.time() - started, 1)
                append_record(jsonl, csv_path, record)
                failed += 1
                print(f"     {record['status']}: {record['reason']}")
                continue
        elif pipeline == "aeneas":
            lean_prepare(project_dir)
        elif pipeline == "leanblueprint":
            lean_prepare(project_dir, args.dep_cache_dir, _LEANBP_STATE)
            setup_reason = leanblueprint_setup(project_dir, args, _LEANBP_STATE)
            if setup_reason:
                record["status"] = "setup_failed"
                record["reason"] = setup_reason[:300]
                record["duration_sec"] = round(time.time() - started, 1)
                append_record(jsonl, csv_path, record)
                failed += 1
                print(f"     {record['status']}: {record['reason']}")
                continue

        # Freshness anchor: only JSON written by THIS extract counts (excludes
        # any committed .verilib JSON that `git checkout` just restored).
        ext_start = time.time()
        code, out = run_extract_cmd(pipeline, project_dir, args)
        record["duration_sec"] = round(time.time() - started, 1)

        path, env = find_fresh_extract(project_dir, pipeline, ext_start)
        if env is None:
            record["status"] = "timeout" if code is None else "extract_failed"
            # Single-line reason: newlines here become multi-line CSV fields,
            # which are valid but noisy in diffs and awkward for consumers.
            tail = " | ".join(ln.strip() for ln in (out or "").splitlines()[-6:] if ln.strip())
            record["reason"] = (f"no fresh unified JSON; exit={code}; {tail}")[:300]
            dbg = Path(tempfile.gettempdir()) / f"vph-extract-{sha[:12]}.log"
            dbg.write_text(out or "", encoding="utf-8", errors="ignore")
            append_record(jsonl, csv_path, record)
            failed += 1
            print(f"     {record['status']}: exit={code} (full output: {dbg})")
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
            failed += 1
            print(f"     {record['status']}: {record['reason']}")
            continue

        if pipeline == "leanblueprint":
            metrics = count_blueprint(env)
            for k in BLUEPRINT_METRIC_KEYS:
                record[f"bp_{k}"] = metrics[k]
            # >=1 node means the blueprint graph was read; 0 nodes means no graph
            # (a preview-only manifest or a failed render) -- a visible gap, not a
            # real "0 formalized" data point.
            if metrics["nodes_total"] > 0:
                record["status"] = "ok"
                # Persist warnings and any cross-check diagnostics (labelled, so
                # they stay distinct) into `reason`, so a claim-vs-status
                # divergence is visible in the committed history, not only via
                # `blueprint_progress.py --table`.
                notes = list(metrics["warnings"])
                notes += [f"diag: {d}" for d in metrics.get("diagnostics", [])]
                record["reason"] = "; ".join(notes)
                if code not in (0, None):
                    record["reason"] = (record["reason"] + f"; extract exit={code}").strip("; ")
                processed += 1
            else:
                record["status"] = "verify_error"
                record["reason"] = (
                    f"blueprint produced 0 nodes (exit={code}); "
                    "likely no graph render / preview-only manifest"
                )
                failed += 1
            append_record(jsonl, csv_path, record)
            # Snapshot the freshly-built deps so the next sample/run with this
            # (toolchain, manifest) restores instead of recompiling (idempotent).
            if (
                args.dep_cache_dir
                and record["status"] == "ok"
                and _LEANBP_STATE.get("dep_cache_key")
            ):
                save_dep_cache(project_dir, args.dep_cache_dir, _LEANBP_STATE["dep_cache_key"])
            print(
                f"     {record['status']}: nodes={metrics['nodes_total']} "
                f"def_formalized={metrics['def_formalized']} "
                f"thm_formalized={metrics['thm_formalized']} "
                f"thm_proved={metrics['thm_proved_confirmed']} ({record['duration_sec']}s)"
            )
            continue

        metrics = count_colors(env)
        for k in METRIC_FIELDS:
            record[k] = metrics[k]
        # Classify: exit 0 => verify ran cleanly. Non-zero but dynamic statuses
        # present (some failed/verified/unverified) => verify ran, record it.
        # Non-zero with only none/trusted => verify did not run (build/toolchain
        # error) -> a visible gap, not a real "0 verified" data point.
        dynamic = (
            metrics["red"] + metrics["yellow"] + metrics["light_green"] + metrics["dark_green"]
        )
        if args.skip_verify or code == 0 or dynamic > 0:
            record["status"] = "ok"
            record["reason"] = "; ".join(metrics["warnings"])
            if code not in (0, None):
                record["reason"] = (record["reason"] + f"; extract exit={code}").strip("; ")
            processed += 1
        else:
            record["status"] = "verify_error"
            record["reason"] = (
                f"verify produced no statuses (exit={code}); likely build/toolchain error"
            )
            failed += 1
        append_record(jsonl, csv_path, record)
        print(
            f"     {record['status']}: tracked={metrics['tracked']} verified={metrics['verified']} "
            f"v+t={metrics['verified_trusted']} translated={metrics['translated']} "
            f"({record['duration_sec']}s)"
        )

    print(f"[done] processed {processed} new sample(s); output: {jsonl}")
    print(f"       CSV: {csv_path}")
    if args.fail_on_error and failed:
        print(f"[fail-on-error] {failed} sample(s) not ok this run", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
