# docstring-lint

The mechanical half of a docstring review for Lean 4 projects. It enumerates the `/-- … -/`
and `/-! … -/` blocks in scope and reports what needs no judgment; the judgment half is
[`RUBRIC.md`](RUBRIC.md), applied by a reviewer to the JSON this tool emits.

Standard library only, Python 3.10+. Cost is dominated by building the name index: on
`secure-messaging` (2 493 blocks; 627 k names indexed from the project, `.lake/packages`
including Mathlib, and the Lean core sources) `--all` takes about 9 s, of which 8 s is the
index and under 2 s the blocks themselves. `--no-packages` or `--no-resolve` skip most of it.

## Usage

```sh
# only the blocks a branch added or touched
python3 docstring_lint.py --root path/to/project --base origin/main

# given files, or the whole project
python3 docstring_lint.py --files Foo/Bar.lean Foo/Baz.lean
python3 docstring_lint.py --all --exclude docs/

# machine-readable, for the rubric pass; CI annotations; fail on errors
python3 docstring_lint.py --base origin/main --format json --only-flagged > blocks.json
python3 docstring_lint.py --base origin/main --format github
python3 docstring_lint.py --base origin/main --strict
```

Exactly one of `--base`, `--files`, `--all` is required. `--base` takes any git ref and keeps a
block when one of its lines is in the diff's touched ranges: the lines a hunk adds, or, for a
hunk that only deletes, the pair of lines the removed ones sat between, so shortening a
docstring selects it too. The per-file diff runs with
`--no-renames`, so a new or renamed file reads as an addition of all its lines and contributes
all of its blocks, while an edited file contributes only the docstrings the change touched.
The file list is read with `--relative -z`, so `--root` may be a subdirectory of the
repository (files outside it are not linted) and a path with non-ASCII bytes arrives intact.

Blocks are found by a scanner that tracks ordinary `/- -/` comments, `--` line comments,
strings — plain, raw (`r#"…"#`, ending only at the matching `"#`) and character literals
(`'"'`) — so a `/--` inside any of those is not a docstring, and a docstring closed on
the same line as its declaration (`/-- doc -/ theorem t …`) is attached to it. Declarations are
read from the same source with comments, docstrings and literals blanked, so an anchor or a note
comment between a docstring and its declaration is skipped, and a declaration sharing a line
with its attributes (`@[simp] theorem t …`) still attaches.

## Checks

| code | severity | what it flags |
|---|---|---|
| `long-line` | error | a docstring line over the limit, counted in characters, the closing line only up to `-/` (`--max-line`, default 100) |
| `unresolved-ref` | warn | a backticked identifier that names nothing: not a declaration in the project, its Lake packages or the Lean core sources, not a module of any of those, not a binder of the declaration, and not a word in the project's code (comments, docstrings and strings excluded) |
| `trivial` | warn | three words or fewer, backticked names counted, on a `theorem`, `lemma`, `def` or `abbrev`; fields, constructors, structures and instances are exempt |
| `name-restated` | warn | the docstring is the declaration name spelled out |
| `restates-decl` | warn | a one- or two-line docstring on a theorem, lemma, def or abbrev whose backticked identifiers are almost all the statement's own |
| `proof-restated` | warn | a `Proof:` / `Proof sketch:` line, a candidate for saying only what the proof term says |
| `question-form` | info | opens with "Why …", answering a question the reader has not met |
| `paren` | info | a parenthesised phrase in the prose (backtick spans excluded) |
| `connective` | info | occurrences of so / hence / therefore / thus, each of which must be a real implication |

Severity `error` is for facts, `warn` for strong heuristics, `info` for things the rubric pass
should look at but that are often fine. `--strict` exits 1 only on errors. Exit 2 is a bad
input rather than a finding: a file named in `--files`, a file git reported as changed for
`--base`, or a `--probe` extract that cannot be read. Files merely discovered by `--all` are
skipped on a read error, since the tree may hold anything.

`unresolved-ref` is what a rename leaves behind. Names are resolved against a regex scan of
every declaration (`theorem`, `def`, `structure`, …, short and namespace-qualified, with
structure fields and inductive constructors as `field` and `Struct.field`, and the string
literal that names a `syntax`, `macro`, `notation`, `infixl`, … declaration) in the project, `.lake/packages`, and `~/.elan/toolchains/<pinned>/src/lean` when `lean-toolchain`
pins an installed toolchain. A probe-lean extract (`--probe extract.json`) adds its exact
declaration list. Tokens containing superscripts or subscripts are treated as notation and
skipped, as are Lean keywords and common tactics. `--no-resolve` skips the check;
`--no-packages` skips the package scan.

## Output

- `text` (default): one line per finding, `path:line: [severity] code: message (declaration)`,
  then a count.
- `json`: `{"schema": "veritooling/docstring-lint", "blocks": [...]}`, every block in scope with
  its text, the declaration it documents, and its findings. `--only-flagged` drops clean blocks.
- `github`: `::warning file=…,line=…::code: message` annotations (`::error` for errors).

## With the rubric

The intended workflow is: run with `--format json`, hand the blocks to a reviewer working from
`RUBRIC.md`, collect KEEP / REPHRASE / DELETE / WRONG verdicts in the report format the rubric
specifies, then apply the accepted edits. The tool catches the stale names and long lines; the
rubric catches docstrings that describe a proof route the term does not take, credit the
wrong lemma, or carry the argument in a parenthesis.

## Tests

```sh
pytest -q tools/docstring-lint/tests
```
