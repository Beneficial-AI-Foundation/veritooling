#!/usr/bin/env python3
"""docstring-lint: the mechanical half of a Lean 4 docstring review.

Enumerates the `/-- … -/` and `/-! … -/` blocks of a Lean project (the whole tree, a list of
files, or only the blocks touched since a git ref) and reports what needs no judgment: lines
over the column limit, backticked identifiers that resolve to no declaration, docstrings that
restate the declaration or are trivially short, `Proof:` lines, and the parentheses and
"so/hence" connectives a human or LLM pass should look at. The judgment criteria live in
RUBRIC.md next to this file; the JSON output is the input to that pass.

Standard library only, Python 3.10+.
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA = "veritooling/docstring-lint"
SCHEMA_VERSION = 1

DECL_KINDS = (
    "theorem",
    "lemma",
    "def",
    "abbrev",
    "structure",
    "class",
    "inductive",
    "instance",
    "axiom",
    "opaque",
    "example",
    "macro",
    "syntax",
    "notation",
    "elab",
    "infixl",
    "infixr",
    "infix",
    "prefix",
    "postfix",
)
# `scoped` may carry the namespace it scopes to: `scoped[omegaLimit] notation "ω" => …`.
_MODIFIERS = (
    r"(?:(?:private|protected|noncomputable|nonrec|partial|unsafe|local"
    r"|scoped(?:\[[\w.'’]+\])?)\s+)*"
)
DECL_RE = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*" + _MODIFIERS + r"(" + "|".join(DECL_KINDS) + r")\b\s*([^\s({\[:]+)?"
)
# Lines that may sit between a docstring and its declaration and declare nothing themselves.
# Checked only after the declaration patterns, so `@[simp] theorem t …` is not skipped as an
# attribute line.
_SKIP_BEFORE_DECL = re.compile(r"^\s*(@\[|set_option\b|open\b.*\bin\s*$|attribute\b)")
# Declarations named by a string literal rather than by an identifier.
_LITERAL_NAME_KINDS = (
    "syntax",
    "macro",
    "notation",
    "elab",
    "infixl",
    "infixr",
    "infix",
    "prefix",
    "postfix",
)
_LITERAL_NAME_RE = re.compile(r'"([^"\n]+)"')
_NAME_START_RE = re.compile(r"[A-Za-z_«Ͱ-Ͽ]")
_FIELD_RE = re.compile(r"^\s+([A-Za-z_][\w'!?]*)\s*:(?!=)")
_CTOR_RE = re.compile(r"^\s*\|\s*([A-Za-z_][\w'!?]*)")
_SECTION_RE = re.compile(r"^\s*section\b\s*([\w.'’]*)")
_STRUCT_RE = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:private|protected)\s+)*(?:structure|class|inductive)\s+([\w.'’]+)"
)
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([\w.'’]+)")
_MUTUAL_RE = re.compile(r"^\s*mutual\b")
_END_RE = re.compile(r"^\s*end\b")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_IDENT_RE = re.compile(r"^[A-Za-z_Ͱ-Ͽ][\w'!?.Ͱ-Ͽ₀-₟₀-₉]*$")
_BINDER_RE = re.compile(r"[(\[{⦃]\s*([^:()\[\]{}⦃⦄]+?)\s*:")
_CONNECTIVE_RE = re.compile(r"\b(so|hence|therefore|thus)\b", re.IGNORECASE)
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_PROOF_RE = re.compile(r"^\s*\**\s*Proof(?: idea| sketch)?\s*:", re.IGNORECASE | re.MULTILINE)
_WORD_RE = re.compile(r"[A-Za-z_][\w']*")
# Superscripts and subscripts mark math notation (`x¹²⁸`, `J₀`), not identifiers to resolve.
_NOTATION_RE = re.compile(r"[\u00b2\u00b3\u00b9\u1d2c-\u1d6a\u2070-\u209f]")

# Backticked tokens that are Lean vocabulary, not declarations to resolve.
LEAN_WORDS = frozenset(
    """
    by simp rfl sorry decide omega linarith positivity norm_num exact refine intro rcases obtain
    rw simpa unfold fun let have show calc match with do return pure bind if then else
    native_decide exact_mod_cast push_cast ring field_simp aesop grind norm_cast nlinarith ext
    funext congr constructor use exists rintro cases induction apply trivial assumption
    contradiction exfalso subst split and_intros gcongr bound tauto
    Prop Type Sort Nat Int Bool List Option Fin Finset Set Fintype BitVec String Unit
    true false none some id Id IO ℕ ℤ ℝ ℚ
    theorem lemma def abbrev structure class inductive instance axiom opaque example
    namespace section variable open import private protected noncomputable
    macro macro_rules syntax notation elab deriving mutual attribute set_option
    infix infixl infixr prefix postfix
    where end at in partial unsafe nonrec local scoped
    """.split()
)

Severity = str  # "error" | "warn" | "info"


@dataclass
class Finding:
    code: str
    severity: Severity
    line: int
    message: str


@dataclass
class Block:
    path: str
    start: int
    end: int
    kind: str  # "decl" (/--) or "module" (/-!)
    text: str  # docstring body without the comment markers
    body_line: int = 0  # line where `text` begins, for finding locations
    end_col: int = 0  # column after the closing `-/`, so line length excludes what follows
    decl_kind: str | None = None
    decl_name: str | None = None
    decl_line: int | None = None
    findings: list[Finding] = field(default_factory=list)

    def add(self, code: str, severity: Severity, line: int, message: str) -> None:
        self.findings.append(Finding(code, severity, line, message))


# --------------------------------------------------------------------------- scanning


@dataclass
class Span:
    """A comment, docstring or string literal: `kind` is `doc` (`/--`), `module` (`/-!`),
    `comment` (ordinary `/- -/`), `line` (`--`) or `string`; offsets are [start, end)."""

    kind: str
    start: int
    end: int


_OPEN_RE = re.compile(r'/-|--|"')
_NEST_RE = re.compile(r"/-|-/")
_STR_RE = re.compile(r'\\.|"', re.DOTALL)


def scan_spans(source: str) -> list[Span]:
    """Every comment, docstring and string span of a Lean source, in order and non-overlapping.
    Block comments nest, `--` runs to the end of the line, strings honour backslash escapes.
    A `/--` inside an ordinary comment or a string is therefore not a docstring."""
    spans: list[Span] = []
    pos = 0
    n = len(source)
    while True:
        m = _OPEN_RE.search(source, pos)
        if not m:
            break
        i, tok = m.start(), m.group(0)
        if tok == "/-":
            if source.startswith("/-!", i):
                kind = "module"
            elif source.startswith("/--", i) and not source.startswith("/--/", i):
                kind = "doc"
            else:
                kind = "comment"
            end = _block_end(source, i)
        elif tok == "--":
            e = source.find("\n", i)
            end = n if e < 0 else e
            kind = "line"
        else:
            j = i + 1
            while True:
                m2 = _STR_RE.search(source, j)
                if not m2:
                    j = n
                    break
                j = m2.end()
                if m2.group(0) == '"':
                    break
            end = j
            kind = "string"
        spans.append(Span(kind, i, end))
        pos = end
    return spans


def _block_end(source: str, start: int) -> int:
    depth = 0
    pos = start
    while True:
        m = _NEST_RE.search(source, pos)
        if not m:
            return len(source)
        if m.group(0) == "/-":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return m.end()
        pos = m.end()


def code_only(source: str, *, keep_strings: bool = False) -> str:
    """The source with every comment, docstring and string blanked out, newlines and offsets
    preserved: what is left is code, so words found in it are identifiers in scope.
    `keep_strings` keeps string literals, whose text is the name of a `syntax`, `elab`,
    `macro` or `notation` declaration."""
    pieces: list[str] = []
    pos = 0
    for sp in scan_spans(source):
        if keep_strings and sp.kind == "string":
            continue
        pieces.append(source[pos : sp.start])
        pieces.append(re.sub(r"[^\n]", " ", source[sp.start : sp.end]))
        pos = sp.end
    pieces.append(source[pos:])
    return "".join(pieces)


def _line_starts(source: str) -> list[int]:
    starts = [0]
    for m in re.finditer(r"\n", source):
        starts.append(m.end())
    return starts


def _line_of(starts: list[int], offset: int) -> int:
    """1-based line holding `offset`."""
    return bisect.bisect_right(starts, offset)


# --------------------------------------------------------------------------- parsing


def parse_blocks(path: str, source: str) -> list[Block]:
    """All docstring blocks of one file, each attached to the declaration that follows it."""
    code_lines = code_only(source, keep_strings=True).split("\n")
    starts = _line_starts(source)
    blocks: list[Block] = []
    for sp in scan_spans(source):
        if sp.kind not in ("doc", "module"):
            continue
        start_line = _line_of(starts, sp.start)
        end_line = _line_of(starts, max(sp.start, sp.end - 1))
        raw = source[sp.start + 3 : max(sp.start + 3, sp.end - 2)]
        lead = len(raw) - len(raw.lstrip())
        body_line = start_line + raw[:lead].count("\n")
        kind = "decl" if sp.kind == "doc" else "module"
        end_col = sp.end - starts[end_line - 1]
        block = Block(
            path, start_line, end_line, kind, raw.strip(), body_line=body_line, end_col=end_col
        )
        if kind == "decl":
            _attach_decl(block, code_lines, end_line, end_col)
        blocks.append(block)
    return blocks


def _attach_decl(block: Block, code_lines: list[str], end_line: int, end_col: int) -> None:
    """Attach the first declaration after the block: the rest of the closing line if it holds
    one (`/-- doc -/ theorem t …`), else the first of the following lines that declares
    something. The lines are the file with comments, docstrings and strings blanked, so anchor
    comments and ordinary `/- … -/` blocks between a docstring and its declaration read as
    blank and are skipped, however long they are; so are attribute-only lines, `set_option`
    and `open … in`. The declaration patterns are tried before those skips, so
    `@[simp] theorem t …` still attaches. The search ends at the first line that declares
    nothing and is not skippable."""
    candidates = [(end_line, code_lines[end_line - 1][end_col:])]
    candidates += [(k + 1, code_lines[k]) for k in range(end_line, len(code_lines))]
    for lineno, line in candidates:
        if not line.strip():
            continue
        m = DECL_RE.match(line)
        if m:
            block.decl_kind = m.group(1)
            block.decl_name = decl_name(m.group(1), m.group(2), line)
            block.decl_line = lineno
            return
        m = _FIELD_RE.match(line)
        if m:
            block.decl_kind, block.decl_name, block.decl_line = "field", m.group(1), lineno
            return
        m = _CTOR_RE.match(line)
        if m:
            block.decl_kind, block.decl_name, block.decl_line = "ctor", m.group(1), lineno
            return
        if _SKIP_BEFORE_DECL.match(line):
            continue
        return


def decl_name(kind: str, captured: str | None, line: str) -> str | None:
    """The name a declaration line declares: the string literal of a `syntax`, `notation`,
    `infixl`, … declaration (`syntax "vcvSupport" : tactic` declares `vcvSupport`), else the
    identifier after the keyword, without its universe parameters (`abbrev GrpMax.{u₁, u₂}`
    declares `GrpMax`; the name pattern stops at the brace and leaves the dot). Anything else
    the keyword may be followed by (`=>`, `|`, a term) is not a name."""
    if kind in _LITERAL_NAME_KINDS:
        m = _LITERAL_NAME_RE.search(line)
        if m:
            return m.group(1).strip() or None
    if captured and _NAME_START_RE.match(captured):
        return captured.rstrip(".") or None
    return None


def decl_signature(lines: list[str], decl_line: int, max_lines: int = 40) -> str:
    """The declaration text from its first line up to the `:=` / `where` / `by` that starts
    the body. Approximate; used only for binder names and restatement heuristics."""
    out: list[str] = []
    for k in range(decl_line - 1, min(decl_line - 1 + max_lines, len(lines))):
        line = lines[k]
        out.append(line)
        if ":=" in line or re.search(r"\b(where|by)\s*$", line):
            break
    return code_only("\n".join(out))


def binder_names(signature: str) -> set[str]:
    names: set[str] = set()
    for m in _BINDER_RE.finditer(signature):
        for tok in m.group(1).split():
            if tok and not tok.startswith(("@", "_")):
                names.add(tok)
    return names


# --------------------------------------------------------------------------- name index


def scan_declared_names(root: Path, include_packages: bool = True) -> set[str]:
    """Names a backticked token may legitimately refer to: every declaration under `root`, its
    Lake packages and the Lean core sources of the pinned toolchain (short and
    namespace-qualified), module names and their components, and every identifier-like word in
    the project's own code. The last set makes the check project-local: a token that appears
    nowhere in the code is what a rename leaves behind."""
    names: set[str] = set()
    for path in root.rglob("*.lean"):
        if ".lake" in path.parts:
            continue
        rel = path.relative_to(root).with_suffix("")
        names.update(rel.parts)
        names.add(".".join(rel.parts))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        _collect_names(text, names)
        names.update(code_words(text))
    others: list[Path] = []
    pkgs = root / ".lake" / "packages"
    if include_packages and pkgs.is_dir():
        others.extend(p for p in pkgs.iterdir() if p.is_dir())
    core = lean_core_src(root)
    if core is not None:
        others.append(core)
    for base in others:
        names.add(base.name)
        for path in base.rglob("*.lean"):
            rel = path.relative_to(base).with_suffix("")
            names.update(rel.parts)
            names.add(".".join(rel.parts))
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            _collect_names(text, names)
    return names


def lean_core_src(root: Path) -> Path | None:
    """`~/.elan/toolchains/<toolchain>/src/lean` for the toolchain pinned in `lean-toolchain`,
    if elan has it installed; core declarations (`Init`, `Lean`, `Std`) are not Lake packages."""
    pin = root / "lean-toolchain"
    if not pin.is_file():
        return None
    name = pin.read_text(encoding="utf-8").strip()
    mangled = name.replace("/", "--").replace(":", "---")
    cand = Path.home() / ".elan" / "toolchains" / mangled / "src" / "lean"
    return cand if cand.is_dir() else None


def _collect_names(text: str, names: set[str]) -> None:
    """Declaration names of one file, short and namespace-qualified, plus the fields of its
    structures and classes and the constructors of its inductives (`field`, `Struct.field`).
    Comments and docstrings are blanked first, so a code example inside a docstring adds no
    name; string literals are kept because they name `syntax`, `macro`, `notation` and `elab`
    declarations. `section` and `mutual` are tracked alongside namespaces, so a bare `end`
    closing either of them does not pop a namespace."""
    scopes: list[tuple[str, str]] = []  # ("namespace" | "section" | "mutual", name)
    owner: str | None = None  # structure/class/inductive whose body we are in
    for line in code_only(text, keep_strings=True).split("\n"):
        if not line.strip():
            continue
        if not line[0].isspace() and not line.lstrip().startswith("|"):
            owner = None
        m = _NAMESPACE_RE.match(line)
        if m:
            scopes.append(("namespace", m.group(1)))
            continue
        m = _SECTION_RE.match(line)
        if m:
            scopes.append(("section", m.group(1)))
            continue
        if _MUTUAL_RE.match(line):
            scopes.append(("mutual", ""))
            continue
        if _END_RE.match(line):
            if scopes:
                scopes.pop()
            continue
        ns = [name for kind, name in scopes if kind == "namespace"]
        m = DECL_RE.match(line)
        if m:
            name = decl_name(m.group(1), m.group(2), line)
            if name is None:
                continue
            names.add(name)
            if ns:
                names.add(".".join(ns) + "." + name)
            sm = _STRUCT_RE.match(line)
            owner = sm.group(1).rstrip(".") if sm else None  # `structure S.{u} where`
            continue
        if owner is not None:
            m = _FIELD_RE.match(line) or _CTOR_RE.match(line)
            if m:
                names.add(m.group(1))
                names.add(owner + "." + m.group(1))
                if ns:
                    names.add(".".join(ns) + "." + owner + "." + m.group(1))


def load_probe_names(path: Path) -> set[str]:
    """Declaration names from a probe-lean `extract` JSON (`data` keys `probe:<Name>`)."""
    data = json.loads(path.read_text(encoding="utf-8")).get("data", {})
    return {k.split(":", 1)[1] for k in data if k.startswith("probe:")}


def resolves(token: str, index: set[str]) -> bool:
    if token in index:
        return True
    for name in index:
        if name.endswith("." + token) or token.endswith("." + name):
            return True
    return False


# --------------------------------------------------------------------------- checks


def _prose(text: str) -> str:
    """Docstring text with backtick spans and fenced code blanked out, offsets preserved."""

    def blank(m: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    text = re.sub(r"```.*?```", blank, text, flags=re.DOTALL)
    return _BACKTICK_RE.sub(blank, text)


def _ident_tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text) if len(w) >= 3}


def check_block(
    block: Block,
    lines: list[str],
    *,
    max_line: int,
    name_index: set[str] | None,
    file_words: set[str],
) -> None:
    # The closing line is measured up to `-/` only: a declaration that follows it
    # (`/-- doc -/ theorem t …`) is not the docstring's line length.
    raw_lines = lines[block.start - 1 : block.end]
    for off, line in enumerate(raw_lines):
        width = block.end_col if block.start + off == block.end else len(line)
        if width > max_line:
            block.add(
                "long-line",
                "error",
                block.start + off,
                f"{width} characters, limit {max_line}",
            )

    prose = _prose(block.text)
    words = _WORD_RE.findall(prose)

    n_words = len(words) + len(_BACKTICK_RE.findall(block.text))
    if block.decl_kind in ("theorem", "lemma", "def", "abbrev") and n_words <= 3:
        block.add("trivial", "warn", block.start, "three words or fewer")

    # On the whole text, not the prose: `` /-- `fooBarBaz` -/ `` restates the name too.
    if block.decl_name and _restates_name(block.text, block.decl_name):
        block.add("name-restated", "warn", block.start, "the docstring is the name, spelled out")

    if _PROOF_RE.search(block.text):
        block.add(
            "proof-restated",
            "warn",
            block.start,
            "has a `Proof:` line; check it says more than the proof term does",
        )

    if re.match(r"\s*Why\b", prose):
        block.add("question-form", "info", block.start, "answers a question the reader has not met")

    for m in _PAREN_RE.finditer(prose):
        inner = m.group(1).strip()
        if not inner:
            continue
        line = block.body_line + block.text[: m.start()].count("\n")
        block.add("paren", "info", line, f"({_short(inner)})")

    conn = _CONNECTIVE_RE.findall(prose)
    if conn:
        block.add(
            "connective",
            "info",
            block.start,
            f"{len(conn)} of so/hence/therefore/thus; each must be a real implication",
        )

    if block.decl_line and block.decl_kind in ("theorem", "lemma", "def", "abbrev"):
        sig = decl_signature(lines, block.decl_line)
        _check_restates_decl(block, sig)

    if name_index is not None:
        sig = decl_signature(lines, block.decl_line) if block.decl_line else ""
        _check_refs(block, sig, name_index, file_words)


def _short(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _name_words(s: str) -> list[str]:
    """`fooBarBaz` and `foo_bar_baz` alike as `["foo", "bar", "baz"]`."""
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s).replace("_", " ").lower().split()


def _restates_name(text: str, name: str) -> bool:
    """The docstring says the declaration's name and nothing else, whether spelled out
    (`Foo bar baz.`) or quoted (`` `fooBarBaz` ``)."""
    parts = _name_words(name.rsplit(".", 1)[-1])
    got = [w for word in _WORD_RE.findall(text) for w in _name_words(word)]
    return len(parts) >= 2 and got == parts


def _check_restates_decl(block: Block, signature: str) -> None:
    """Backticked identifiers (or, when fewer than three, every identifier-like word) of the
    docstring measured against the statement's identifiers."""
    doc_ids = {
        t for t in (m.group(1).strip() for m in _BACKTICK_RE.finditer(block.text)) if len(t) >= 3
    }
    if len(doc_ids) < 3:
        doc_ids = _ident_tokens(block.text)
    if len(doc_ids) < 3:
        return
    sig_ids = _ident_tokens(signature)
    overlap = len(doc_ids & sig_ids) / len(doc_ids)
    if overlap >= 0.8 and len(block.text.split("\n")) <= 2:
        block.add(
            "restates-decl",
            "warn",
            block.start,
            f"{int(overlap * 100)}% of its identifiers are the statement's; says nothing the type"
            " does not",
        )


def _check_refs(block: Block, signature: str, index: set[str], file_words: set[str]) -> None:
    binders = binder_names(signature)
    seen: set[str] = set()
    for m in _BACKTICK_RE.finditer(block.text):
        tok = m.group(1).strip()
        if tok in seen or not _IDENT_RE.match(tok) or _NOTATION_RE.search(tok):
            continue
        seen.add(tok)
        if tok in LEAN_WORDS or tok in binders:
            continue
        last = tok.rsplit(".", 1)[-1]
        if last in binders or tok in file_words or last in file_words:
            continue
        if resolves(tok, index):
            continue
        line = block.body_line + block.text[: m.start()].count("\n")
        block.add("unresolved-ref", "warn", line, f"`{tok}` names no declaration found")


def code_words(source: str) -> set[str]:
    """Identifier-like words in the file's code, with comments, docstrings and strings blanked
    (fields, local notation, pattern variables, binders of other declarations). A backticked
    token found here is not a dangling reference. Dotted tokens also contribute their parts."""
    words: set[str] = set()
    for tok in re.findall(r"[\w'!?.Ͱ-Ͽ₀-₟]+", code_only(source)):
        words.add(tok)
        words.update(tok.split("."))
    return words


# --------------------------------------------------------------------------- scope


def git_changed_files(root: Path, base: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "--diff-filter=AMR", base, "--", "*.lean"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.split("\n") if line.strip()]


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def touched_ranges(diff_text: str) -> list[tuple[int, int]]:
    """Inclusive 1-based line ranges of the current file touched by a unified diff with zero
    context. An added hunk `+b,c` gives `(b, b + c - 1)`; a deletion-only hunk `+b,0` has no
    lines of its own and gives `(b, b + 1)`, the pair the removed lines sat between, so
    shortening a docstring still selects it."""
    ranges = []
    for line in diff_text.split("\n"):
        m = _HUNK_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        ranges.append((start, start + count - 1) if count else (start, start + 1))
    return ranges


def git_touched_ranges(root: Path, base: str, rel: str) -> list[tuple[int, int]]:
    """`--no-renames`, so a file renamed since the ref reads as an addition of all its lines
    rather than as rename metadata with no hunks: a renamed file contributes all of its
    blocks, and one renamed and then edited contributes the untouched docstrings too."""
    out = subprocess.run(
        ["git", "-C", str(root), "diff", "-U0", "--no-renames", base, "--", rel],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return touched_ranges(out)


def in_ranges(block: Block, ranges: list[tuple[int, int]]) -> bool:
    return any(not (block.end < a or block.start > b) for a, b in ranges)


def read_error(path: Path) -> str | None:
    """Why `path` cannot be linted, or None. Discovered files are skipped on error; a file
    named on the command line is a caller's mistake, so `main` reports it instead."""
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "not UTF-8"
    except OSError as e:
        return e.strerror or str(e)
    return None


def project_files(root: Path, excludes: list[str]) -> list[str]:
    files = []
    for p in sorted(root.rglob("*.lean")):
        rel = p.relative_to(root).as_posix()
        if ".lake/" in rel or rel.startswith(".") or any(x in rel for x in excludes):
            continue
        files.append(rel)
    return files


# --------------------------------------------------------------------------- driver


def lint(
    root: Path,
    files: list[str],
    *,
    base: str | None,
    max_line: int,
    name_index: set[str] | None,
) -> list[Block]:
    blocks: list[Block] = []
    for rel in files:
        path = root / rel
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        file_blocks = parse_blocks(rel, source)
        words = code_words(source) if name_index is not None else set()
        if base is not None:
            ranges = git_touched_ranges(root, base, rel)
            file_blocks = [b for b in file_blocks if in_ranges(b, ranges)]
        lines = source.split("\n")
        for b in file_blocks:
            check_block(b, lines, max_line=max_line, name_index=name_index, file_words=words)
        blocks.extend(file_blocks)
    return blocks


def render_text(blocks: list[Block]) -> str:
    out = []
    n = 0
    for b in blocks:
        for f in b.findings:
            n += 1
            who = b.decl_name or ("module header" if b.kind == "module" else "?")
            out.append(f"{b.path}:{f.line}: [{f.severity}] {f.code}: {f.message}  ({who})")
    out.append(f"{len(blocks)} blocks, {n} findings")
    return "\n".join(out)


def _wc_data(s: str) -> str:
    """A workflow command's message: GitHub decodes `%25`, `%0D` and `%0A` in it, so a
    docstring carrying those sequences (or a newline) would otherwise break the annotation."""
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _wc_prop(s: str) -> str:
    """A workflow command's property value: `:` and `,` end it, so they are escaped too."""
    return _wc_data(s).replace(":", "%3A").replace(",", "%2C")


def render_github(blocks: list[Block]) -> str:
    out = []
    for b in blocks:
        for f in b.findings:
            level = "error" if f.severity == "error" else "warning"
            out.append(
                f"::{level} file={_wc_prop(b.path)},line={f.line}"
                f"::{_wc_data(f.code)}: {_wc_data(f.message)}"
            )
    return "\n".join(out)


def render_json(blocks: list[Block], root: Path, scope: dict) -> str:
    payload = {
        "schema": SCHEMA,
        "schema-version": SCHEMA_VERSION,
        "root": str(root),
        "scope": scope,
        "blocks": [asdict(b) for b in blocks],
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=".", help="Lean project root (default: cwd)")
    scope = ap.add_mutually_exclusive_group(required=True)
    scope.add_argument("--base", help="git ref: only blocks touched since this ref")
    scope.add_argument("--files", nargs="+", help="files to lint, relative to root")
    scope.add_argument("--all", action="store_true", help="every .lean file under root")
    ap.add_argument("--exclude", action="append", default=[], help="path substring to skip")
    ap.add_argument("--max-line", type=int, default=100, help="column limit (characters)")
    ap.add_argument("--probe", type=Path, help="probe-lean extract JSON for name resolution")
    ap.add_argument("--no-resolve", action="store_true", help="skip the unresolved-ref check")
    ap.add_argument("--no-packages", action="store_true", help="do not scan .lake/packages")
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    ap.add_argument(
        "--only-flagged", action="store_true", help="JSON: drop blocks without findings"
    )
    ap.add_argument("--strict", action="store_true", help="exit 1 on any error-severity finding")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if args.files:
        files = args.files
        scope_desc = {"files": files}
        # A file asked for by name and then skipped would let a typo in a CI list pass silently.
        unreadable = [f"{f}: {err}" for f in files if (err := read_error(root / f))]
        if unreadable:
            print("error: cannot read " + "; ".join(unreadable), file=sys.stderr)
            return 2
    elif args.base:
        files = git_changed_files(root, args.base)
        scope_desc = {"base": args.base}
    else:
        files = project_files(root, args.exclude)
        scope_desc = {"all": True}
    if args.exclude:
        files = [f for f in files if not any(x in f for x in args.exclude)]

    index: set[str] | None = None
    if not args.no_resolve:
        index = scan_declared_names(root, include_packages=not args.no_packages)
        if args.probe:
            index |= load_probe_names(args.probe)

    blocks = lint(root, files, base=args.base, max_line=args.max_line, name_index=index)

    if args.format == "json":
        if args.only_flagged:
            blocks = [b for b in blocks if b.findings]
        print(render_json(blocks, root, scope_desc))
    elif args.format == "github":
        print(render_github(blocks))
    else:
        print(render_text(blocks))

    if args.strict and any(f.severity == "error" for b in blocks for f in b.findings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
