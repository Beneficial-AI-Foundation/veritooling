#!/usr/bin/env python3
"""Build a blueprint dependency-graph model from one extract envelope.

Sibling to ``blueprint_progress.py`` (the counter). Where that folds atoms into
scalar progress metrics, this folds the *same* atoms into a graph: one node per
``blueprint-label``, edges from the curated ``blueprint-*-uses`` lists, and one
colour state per node. Node grouping mirrors ``blueprint_progress._collect_nodes``
(a test cross-checks node counts against ``count_blueprint``), so the graph and
the burn-up never disagree on what a node is.

Design notes (see ``blueprint-depgraph-plan.md``):

* **Node identity is by ``blueprint-label``**, one node per label, atoms with a
  null label skipped. Never one-node-per-key or per-status.
* **``bound``** = any atom is a real (``language != "blueprint"``) or shadow atom
  -- not "code-path present".
* **``verif`` rollup** counts ``verification-status`` from included real atoms
  only (``language != "blueprint"`` and ``_atom_included``); hidden / ignored /
  stub atoms never sway a node's status.
* **Edges** are resolved ``key -> target atom -> its blueprint-label``, collected
  from *all* atoms in a source label group, with intra-label (self) edges
  dropped and the rest deduped. Unresolved targets are counted *by reason*.
* **Colour** is a single ordered precedence (``node_state``), so overlapping
  states (mismatch / trusted / machine-verified / claimed) resolve deterministically.

"Machine-verified" (the graph's solid green) is the per-node ``verif`` rollup
landing on ``verified``. This is NOT ``blueprint_progress``'s binding-complete
``thm_proved_confirmed`` nor the 3.0 sidecar's ``fraction-probe-lean-confirmed``
(both "not-refuted" bars). See the plan's "Terminology" note.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

# Reuse the oracle's grouping helpers verbatim so the graph can't drift from the
# tested counter.
from blueprint_progress import _PROOF_RANK, _atom_included, _proof_bucket

# Node colour states, in the precedence order ``node_state`` evaluates (first
# match wins). See the plan's colour-mapping table.
STATES = (
    "mismatch",
    "failed",
    "trusted",
    "machine-verified",
    "proved-claimed",
    "statement-formalized",
    "ready",
    "not-ready",
)

# Unresolved-edge drop reasons (kept as an ordered tuple for stable reporting).
DROP_REASONS = ("missing-key", "upstream-unlabeled", "self-edge", "duplicate")


@dataclass
class Node:
    """One blueprint node, assembled from every atom sharing its label."""

    label: str
    kind: str = "theorem"
    title: str | None = None
    chapter: str | None = None
    group: str | None = None
    stmt_status: str = "none"
    proof_status: str = "none"
    bound: bool = False
    decl_missing: bool = False
    missing_decls: bool = False
    mismatch_field: bool = False  # blueprint-status-mismatch, straight from 3.0
    statuses: list[str] = field(default_factory=list)  # machine statuses, real atoms
    kinds: set[str] = field(default_factory=set)
    stmt_use_keys: set[str] = field(default_factory=set)
    proof_use_keys: set[str] = field(default_factory=set)

    @property
    def proof_bucket(self) -> str | None:
        """failed | in_progress | trusted | verified | None (unrealized)."""
        return _proof_bucket(self.statuses)


@dataclass(frozen=True)
class Edge:
    src: str  # source label
    dst: str  # target label
    kind: str  # "statement" | "proof"


@dataclass
class Graph:
    nodes: dict[str, Node]  # label -> Node
    edges: list[Edge]
    dropped: dict[str, int]  # reason -> count
    schema: str
    schema_version: str
    source: dict


def node_state(n: Node) -> str:
    """Fold a node to one colour state by fixed precedence (first match wins).

    A node can satisfy several conditions at once (e.g. ``fully-proved`` claim,
    ``trusted`` binding, ``mismatch`` flag); this picks exactly one.
    """
    bucket = n.proof_bucket
    claimed = n.proof_status in ("proved", "fully-proved")
    # mismatch: the 3.0 flag, OR a proved claim the machine refutes (sorry/failed).
    if n.mismatch_field or (claimed and bucket in ("failed", "in_progress")):
        return "mismatch"
    if bucket == "failed":
        return "failed"
    if bucket == "trusted":
        return "trusted"
    if n.proof_status == "fully-proved" and bucket == "verified":
        return "machine-verified"
    if claimed:
        # A proved claim with no machine backing (unrealized) or only "proved".
        return "proved-claimed"
    if n.stmt_status == "formalized":
        return "statement-formalized"
    if n.stmt_status == "ready":
        return "ready"
    return "not-ready"


def _iter_items(data):
    """Yield ``(key, atom)``; ``data`` is a probe-id -> atom map (list tolerated)."""
    if isinstance(data, dict):
        yield from data.items()
    elif isinstance(data, list):
        for i, atom in enumerate(data):
            yield str(i), atom


def build_graph(envelope: dict) -> Graph:
    """Turn one ``probe-leanblueprint/extract`` envelope into a graph model."""
    data = envelope.get("data") or {}

    # Pass 1: every atom's key -> its blueprint-label (or None), and group atoms
    # into nodes by label. Both need the dict key, which _collect_nodes discards,
    # so we re-walk here rather than call it -- a test guards that the node set
    # stays identical to the oracle's.
    key_to_label: dict[str, str | None] = {}
    data_keys: set[str] = set()
    nodes: dict[str, Node] = {}
    for key, atom in _iter_items(data):
        if not isinstance(atom, dict):
            continue
        data_keys.add(key)
        label = atom.get("blueprint-label")
        key_to_label[key] = label
        if label is None:
            continue
        n = nodes.get(label)
        if n is None:
            n = Node(label=label)
            nodes[label] = n
        n.kind = atom.get("blueprint-kind", n.kind)
        if atom.get("blueprint-kind"):
            n.kinds.add(atom["blueprint-kind"])
        # Node metadata is last-write-wins across the group (like the oracle);
        # keep the first non-empty title/chapter/group so a synthetic atom with
        # blanks can't clobber a real one.
        n.title = n.title or atom.get("blueprint-title")
        n.chapter = n.chapter or atom.get("blueprint-chapter")
        n.group = n.group or atom.get("blueprint-group")
        n.stmt_status = atom.get("blueprint-statement-status", n.stmt_status)
        n.proof_status = atom.get("blueprint-proof-status", n.proof_status)
        if atom.get("language") != "blueprint" or atom.get("blueprint-shadow"):
            n.bound = True
        if atom.get("language") != "blueprint" and _atom_included(atom):
            vs = atom.get("verification-status")
            if vs is not None:
                n.statuses.append(vs)
        if atom.get("blueprint-decl-missing"):
            n.decl_missing = True
        if atom.get("blueprint-missing-decls"):
            n.missing_decls = True
        if atom.get("blueprint-status-mismatch"):
            n.mismatch_field = True
        for k in atom.get("blueprint-statement-uses") or []:
            n.stmt_use_keys.add(k)
        for k in atom.get("blueprint-proof-uses") or []:
            n.proof_use_keys.add(k)

    # Pass 2: resolve edges key -> label, drop self-edges, dedupe, count reasons.
    edges: list[Edge] = []
    dropped = dict.fromkeys(DROP_REASONS, 0)
    seen: set[Edge] = set()
    for n in nodes.values():
        for cls, keys in (("statement", n.stmt_use_keys), ("proof", n.proof_use_keys)):
            for tgt_key in keys:
                if tgt_key not in data_keys:
                    dropped["missing-key"] += 1
                    continue
                tgt_label = key_to_label.get(tgt_key)
                if tgt_label is None:
                    dropped["upstream-unlabeled"] += 1
                    continue
                if tgt_label == n.label:
                    dropped["self-edge"] += 1
                    continue
                edge = Edge(src=n.label, dst=tgt_label, kind=cls)
                if edge in seen:
                    dropped["duplicate"] += 1
                    continue
                seen.add(edge)
                edges.append(edge)

    edges.sort(key=lambda e: (e.src, e.dst, e.kind))
    return Graph(
        nodes=nodes,
        edges=edges,
        dropped=dropped,
        schema=envelope.get("schema", "") or "",
        schema_version=str(envelope.get("schema-version", "")),
        source=envelope.get("source", {}) or {},
    )


def _open(path: Path):
    """Open a possibly-gzipped JSON extract (Stage 0 archives are ``.json.gz``)."""
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def build_graph_file(path: Path) -> Graph:
    with _open(Path(path)) as f:
        return build_graph(json.load(f))


def summary(graph: Graph) -> dict:
    """Per-state and per-kind counts + fractions, recomputed from the graph.

    All figures come from the graph nodes, never a summary sidecar. The
    ``machine_verified_fraction`` is the per-node ``verif`` green over theorems;
    ``claimed_fraction`` is the blueprint's own fully-proved claim.
    """
    nodes = list(graph.nodes.values())
    thms = [n for n in nodes if n.kind != "definition"]
    defs = [n for n in nodes if n.kind == "definition"]

    by_state = dict.fromkeys(STATES, 0)
    for n in nodes:
        by_state[node_state(n)] += 1

    thm_total = len(thms)
    thm_claimed = sum(1 for n in thms if n.proof_status == "fully-proved")
    thm_machine = sum(1 for n in thms if node_state(n) == "machine-verified")

    def frac(num: int, den: int) -> float:
        return num / den if den else 0.0

    return {
        "nodes_total": len(nodes),
        "def_total": len(defs),
        "thm_total": thm_total,
        "thm_claimed_proved": thm_claimed,
        "thm_machine_verified": thm_machine,
        "claimed_fraction": frac(thm_claimed, thm_total),
        "machine_verified_fraction": frac(thm_machine, thm_total),
        "by_state": by_state,
        "edges": len(graph.edges),
        "dropped": dict(graph.dropped),
    }


# --- Dependency-closure metrics --------------------------------------------
#
# The colour states above are node-LOCAL: a node's own bindings can be
# machine-verified while something it uses is still a sorry, and node_state
# doesn't see that. The functions below answer the graph-wide question the
# verso-blueprint "Blueprint Summary" pages ask (e.g.
# https://leanprover.github.io/verso-blueprint/.../Blueprint-Summary/):
# "completed" vs "with incomplete dependencies", "ready now", and which
# entries the most downstream work depends on. There is no published spec for
# the site's exact bucket semantics (its source isn't ours to read), so these
# are our own well-defined notions -- close in spirit, not guaranteed to match
# the live site's counts exactly.


def _adjacency(graph: Graph, kinds: set[str] | None = None) -> dict[str, set[str]]:
    """label -> set of labels it uses, restricted to edges whose kind is in
    ``kinds`` (default: both statement and proof, combined).

    Closure and downstream-reachability don't care which axis a dependency
    came from -- a theorem is only as sound as everything it transitively
    touches, whether via its statement or its proof. ``actionable`` is
    narrower: whether a node's *statement* can be written today depends only
    on its statement-use dependencies, not on what its eventual proof will
    cite, so it passes ``kinds={"statement"}``.
    """
    adj: dict[str, set[str]] = {label: set() for label in graph.nodes}
    for e in graph.edges:
        if kinds is None or e.kind in kinds:
            adj[e.src].add(e.dst)
    return adj


def claimed_ok(n: Node) -> bool:
    """The blueprint's own claim, ignoring machine backing (matches what a
    native leanblueprint/verso graph colours green from ``\\leanok``)."""
    if n.kind == "definition":
        return n.stmt_status == "formalized"
    return n.proof_status == "fully-proved"


def machine_ok(n: Node) -> bool:
    """Our stricter cross-check: the ``verif`` rollup actually backs the claim."""
    if n.kind == "definition":
        return n.stmt_status == "formalized" and node_state(n) not in ("mismatch", "failed")
    return node_state(n) == "machine-verified"


def closure(graph: Graph, own_ok) -> tuple[dict[str, bool], list[str]]:
    """Per-node transitive closure: ``own_ok(node)`` AND everything it (directly
    or transitively) uses is also closed.

    ``own_ok`` is a ``Node -> bool`` predicate for the node's own status,
    ignoring its dependencies (see ``claimed_ok`` / ``machine_ok``). A node can
    be locally fine yet not "closed" if something it rests on isn't -- that
    gap is exactly what ``node_state`` alone can't show.

    Returns ``(closed, cycle_labels)``. A dependency cycle has no well-defined
    closure; every node on it is marked not closed, and the node where the
    back-edge was found (at least one label per cycle, not necessarily every
    member) is reported in ``cycle_labels`` -- blueprint graphs should be a
    DAG, so a nonempty result here is itself a data-quality signal worth
    surfacing.
    """
    adj = _adjacency(graph)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph.nodes, WHITE)
    closed: dict[str, bool] = {}
    cycle_labels: list[str] = []

    def visit(label: str) -> bool:
        if color[label] == BLACK:
            return closed[label]
        if color[label] == GRAY:
            cycle_labels.append(label)
            return False
        color[label] = GRAY
        ok = own_ok(graph.nodes[label])
        for dep in adj[label]:
            if not visit(dep):
                ok = False
        color[label] = BLACK
        closed[label] = ok
        return ok

    for label in graph.nodes:
        visit(label)
    return closed, cycle_labels


def downstream_counts(graph: Graph) -> dict[str, int]:
    """Per-node count of distinct OTHER nodes that transitively depend on it
    (reverse reachability) -- the site's "downstream unlocks": how much work
    becomes less blocked once this entry closes.

    A node on a dependency cycle can be reached back from itself during the
    walk; explicitly excluded so a node is never counted as its own
    downstream dependent (blueprint graphs should be a DAG, but a real one --
    e.g. KeyedVerificationAnonymousCredential-model's -- can have a cycle; see
    ``closure``'s cycle detection).
    """
    radj: dict[str, set[str]] = {label: set() for label in graph.nodes}
    for e in graph.edges:
        radj[e.dst].add(e.src)
    counts: dict[str, int] = {}
    for label in graph.nodes:
        seen: set[str] = set()
        stack = list(radj[label])
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(radj.get(x, ()) - seen)
        seen.discard(label)
        counts[label] = len(seen)
    return counts


def in_degree(graph: Graph) -> dict[str, dict[str, int]]:
    """Per-node direct reverse-dependency counts, split by edge class."""
    counts = {label: {"statement": 0, "proof": 0} for label in graph.nodes}
    for e in graph.edges:
        counts[e.dst][e.kind] += 1
    return counts


def actionable(graph: Graph) -> list[str]:
    """Labels whose statement is ``ready`` (informal writeup done, no Lean
    binding yet), whose STATEMENT-use dependencies are already formalized
    (a proof-use dependency has no bearing on writing the statement, so it
    doesn't gate this), and that already unlock at least one downstream entry
    (``downstream_counts`` > 0).

    Mirrors the live verso-blueprint site's own description of its
    "Actionable priorities" metric: entries "ready now and already unlocking
    downstream work". Deliberately NOT named ``ready_now``: the live site's
    "Ready now" headline is a stricter, different metric (see the plan). This
    is our own reading of "actionable", not guaranteed to match the live
    site's bucket exactly on every project.
    """
    stmt_adj = _adjacency(graph, kinds={"statement"})
    downstream = downstream_counts(graph)
    out = []
    for label, n in graph.nodes.items():
        if n.stmt_status != "ready":
            continue
        if downstream[label] <= 0:
            continue
        if all(
            graph.nodes[d].stmt_status == "formalized" for d in stmt_adj[label] if d in graph.nodes
        ):
            out.append(label)
    return out


def _claimed_bucket(n: Node) -> str:
    """The blueprint's own four-way split, read directly off ``proof_status``.

    No graph walk needed: per ``docs/SCHEMA.md``, probe-leanblueprint already
    computes this closure upstream -- ``proved`` means "sorry-free on its own",
    ``fully-proved`` means "this node *and everything it depends on* are done".
    Validated against carleson's own published Blueprint-Summary page: reading
    proof_status this way reproduces its 154 closed / 6 incomplete-deps exactly
    (mod one node of expected commit drift between snapshots).
    """
    if n.proof_status == "fully-proved":
        return "closed"
    if n.proof_status == "proved":
        return "incomplete-deps"
    if n.proof_bucket in ("in_progress", "failed"):
        return "sorry"
    return "no-proof"


def _machine_bucket(n: Node, is_closed: bool) -> str:
    """Our independent cross-check: probe-lean's own per-node status plus a
    graph walk over the SAME blueprint uses-edges (not the blueprint's own,
    more optimistic closure above).

    ``machine_ok`` requires proof_status ``fully-proved`` too (see its
    docstring), so a node whose own Lean binding is sorry-free but whose
    blueprint claim is only ``proved`` (or whose binding is merely ``trusted``,
    axiom-reliant) fails ``machine_ok`` without being "no proof" -- it lands in
    ``incomplete-deps``, same as a node blocked by an unclosed dependency.
    """
    if machine_ok(n):
        return "closed" if is_closed else "incomplete-deps"
    if n.proof_bucket in ("in_progress", "failed"):
        return "sorry"
    if n.proof_bucket in ("verified", "trusted"):
        return "incomplete-deps"
    return "no-proof"


def closure_summary(graph: Graph) -> dict:
    """The site's four-way split -- closed / incomplete-deps / sorry / no-proof
    -- computed twice: once from the blueprint's own claim (direct field read,
    see ``_claimed_bucket``), once from our stricter machine-verified
    cross-check (a graph walk over probe-lean's own per-node status, see
    ``_machine_bucket``). Scoped to theorem-kind nodes (a "closed" definition is
    just "formalized"; nothing to split further).
    """
    machine_closed, machine_cycles = closure(graph, machine_ok)
    thms = [n for n in graph.nodes.values() if n.kind != "definition"]

    claimed = dict.fromkeys(("closed", "incomplete-deps", "sorry", "no-proof"), 0)
    machine = dict.fromkeys(("closed", "incomplete-deps", "sorry", "no-proof"), 0)
    for n in thms:
        claimed[_claimed_bucket(n)] += 1
        machine[_machine_bucket(n, machine_closed[n.label])] += 1

    return {
        "thm_total": len(thms),
        "claimed": claimed,
        "machine": machine,
        "machine_cycles": sorted(set(machine_cycles)),
    }


# Re-exported for consumers that want the raw rank table (e.g. custom colouring).
__all__ = [
    "Node",
    "Edge",
    "Graph",
    "STATES",
    "DROP_REASONS",
    "node_state",
    "build_graph",
    "build_graph_file",
    "summary",
    "claimed_ok",
    "machine_ok",
    "closure",
    "closure_summary",
    "downstream_counts",
    "in_degree",
    "actionable",
    "_PROOF_RANK",
]
