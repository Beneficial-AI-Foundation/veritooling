"""docstring_lint: parsing, each mechanical check, diff scoping and output formats."""

import json
import subprocess

import docstring_lint as dl

SAMPLE = """\
/-!
# Module header

Explains the file. Nested /- comment -/ inside stays part of the block.
-/

namespace Foo

/-- Doc for `bar`, which uses `baz` and `Nat`. -/
-- ANCHOR: bar
theorem bar (n : ℕ) (hn : 0 < n) : n ≠ 0 := by omega
-- ANCHOR_END: bar

/-- Baz thing. -/
@[simp]
def baz : ℕ := 3

/-- A block cipher. -/
structure Cipher (K : Type) where
  /-- Forward. -/
  perm : K → K
  /-- Inverse. -/
  invPerm : K → K

/-- Proof: unfold and `simp`. So it holds (trivially). Hence done. -/
theorem qux : baz = 3 := rfl

/-- Refers to `gone` which no longer exists, to `x⁷` notation and to `hn` a binder. -/
theorem quux (hn : 0 < 1) : True := trivial

end Foo
"""


def _blocks(text=SAMPLE):
    return dl.parse_blocks("Foo.lean", text)


# --------------------------------------------------------------------------- parsing


def test_parse_finds_all_blocks_and_kinds():
    bs = _blocks()
    kinds = [(b.kind, b.decl_kind, b.decl_name) for b in bs]
    assert kinds == [
        ("module", None, None),
        ("decl", "theorem", "bar"),
        ("decl", "def", "baz"),
        ("decl", "structure", "Cipher"),
        ("decl", "field", "perm"),
        ("decl", "field", "invPerm"),
        ("decl", "theorem", "qux"),
        ("decl", "theorem", "quux"),
    ]


def test_nested_comment_does_not_end_block():
    header = _blocks()[0]
    assert header.start == 1 and header.end == 5
    assert "Nested /- comment -/ inside" in header.text


def test_attach_skips_anchor_comments_and_attributes():
    bs = _blocks()
    assert bs[1].decl_line == 11  # past the `-- ANCHOR:` line
    assert bs[2].decl_line == 16  # past `@[simp]`


def test_body_strips_markers():
    assert _blocks()[2].text == "Baz thing."


def test_binder_names():
    sig = "theorem t {α : Type} [inst : Foo α] (x y : α) (hxy : x ≠ y) : True :="
    assert dl.binder_names(sig) == {"α", "inst", "x", "y", "hxy"}


def test_doc_opener_inside_ordinary_comment_is_not_a_docstring():
    text = (
        "/- An example:\n/-- looks like a docstring -/\ntheorem fake : True := trivial\n-/\n"
        "/-- Real. -/\ntheorem real : True := trivial\n"
    )
    bs = _blocks(text)
    assert [b.decl_name for b in bs] == ["real"]


def test_doc_opener_inside_string_or_line_comment_is_ignored():
    text = 'def s : String := "/-- not a doc -/"\n-- /-- nor this -/\n/-- Yes. -/\ndef t := 1\n'
    assert [b.decl_name for b in _blocks(text)] == ["t"]


def test_one_line_docstring_with_declaration_on_the_same_line():
    text = "/-- docs -/ theorem t : True := trivial\n"
    (b,) = _blocks(text)
    assert (b.text, b.decl_name, b.decl_line) == ("docs", "t", 1)


def test_body_line_tracks_stripped_leading_newline():
    text = "/--\nFirst (with paren).\n-/\ntheorem t : True := trivial\n"
    (b,) = _blocks(text)
    assert b.body_line == 2
    lines = text.split("\n")
    dl.check_block(b, lines, max_line=100, name_index=None, file_words=set())
    assert [f.line for f in b.findings if f.code == "paren"] == [2]


def test_code_only_blanks_comments_docstrings_and_strings():
    text = 'theorem t := "-- not a comment" -- `gone`\n/- gone -/ /-- gone -/ def u := 1\n'
    code = dl.code_only(text)
    assert "gone" not in code and "theorem t" in code and "def u" in code
    assert code.count("\n") == text.count("\n")


# --------------------------------------------------------------------------- checks


def _lint(text=SAMPLE, index=None, max_line=100):
    bs = _blocks(text)
    lines = text.split("\n")
    words = dl.code_words(text)
    for b in bs:
        dl.check_block(b, lines, max_line=max_line, name_index=index, file_words=words)
    return {(b.decl_name or "header"): b for b in bs}


def _codes(block):
    return sorted(f.code for f in block.findings)


def test_long_line_counts_characters_not_bytes():
    text = "/-- " + "x¹²⁸ " * 18 + "-/\ntheorem t : True := trivial\n"
    line = text.split("\n")[0]
    assert len(line) <= 100 < len(line.encode("utf-8"))
    out = _lint(text, index=set())
    assert "long-line" not in _codes(out["t"])
    out = _lint(text, index=set(), max_line=80)
    assert [f.severity for f in out["t"].findings if f.code == "long-line"] == ["error"]


def test_paren_and_connective_and_proof_flags():
    out = _lint(index=set())
    qux = out["qux"]
    assert "proof-restated" in _codes(qux)
    assert "paren" in _codes(qux)
    conn = [f for f in qux.findings if f.code == "connective"][0]
    assert conn.message.startswith("2 of")  # "So" and "Hence"


def test_paren_ignores_backtick_contents():
    text = "/-- Uses `f (x)` and nothing else. -/\ndef g : ℕ := 0\n"
    assert "paren" not in _codes(_lint(text, index=set())["g"])


def test_trivial_only_for_real_declarations():
    out = _lint(index=set())
    assert "trivial" in _codes(out["baz"])  # "Baz thing." on a def
    assert "trivial" not in _codes(out["perm"])  # short field docs are fine
    assert "trivial" not in _codes(out["Cipher"])  # structures are exempt
    assert "trivial" not in _codes(out["header"])
    text = "/-- Uses `foo`. -/\ntheorem t : True := trivial\n"
    assert "trivial" in _codes(_lint(text, index=set())["t"])  # backticked names count as words


def test_name_restated():
    text = "/-- Foo bar baz. -/\ntheorem fooBarBaz : True := trivial\n"
    assert "name-restated" in _codes(_lint(text, index=set())["fooBarBaz"])
    text = "/-- Foo bar baz. -/\ntheorem foo_bar_baz : True := trivial\n"
    assert "name-restated" in _codes(_lint(text, index=set())["foo_bar_baz"])


def test_restates_decl():
    text = (
        "/-- `ghash` of `encode` at `H` equals `poly`. -/\n"
        "theorem ghash_encode (H : K) : ghash H (encode m) = poly H := rfl\n"
    )
    assert "restates-decl" in _codes(_lint(text, index=set())["ghash_encode"])


def test_proof_requires_colon():
    text = "/-- Proof obligations are discharged by `simp`. -/\ntheorem t : True := trivial\n"
    assert "proof-restated" not in _codes(_lint(text, index=set())["t"])
    text = "/-- The bound.\n\nProof sketch: unfold. -/\ntheorem t : True := trivial\n"
    assert "proof-restated" in _codes(_lint(text, index=set())["t"])


def test_same_line_docstring_is_not_part_of_the_signature():
    text = "/-- `alpha` `beta` `gamma` -/ theorem t : True := trivial\n"
    out = _lint(text, index=set())
    assert "restates-decl" not in _codes(out["t"])


def test_restates_decl_applies_to_defs():
    text = "/-- `foo` of `bar` and `baz`. -/\ndef fooBarBaz (bar baz : Nat) : Nat := foo bar baz\n"
    assert "restates-decl" in _codes(_lint(text, index=set())["fooBarBaz"])


def test_question_form():
    text = "/-- Why the bound has no extra term: reasons. -/\ntheorem t : True := trivial\n"
    assert "question-form" in _codes(_lint(text, index=set())["t"])


def test_unresolved_ref_rules():
    out = _lint(index={"baz", "Foo.bar"})
    # `bar` and `baz` resolve via the index; `Nat` is Lean vocabulary.
    assert "unresolved-ref" not in _codes(out["bar"])
    quux = out["quux"]
    msgs = [f.message for f in quux.findings if f.code == "unresolved-ref"]
    assert msgs == ["`gone` names no declaration found"]  # not `x⁷` (notation), not `hn` (binder)


def test_unresolved_ref_one_character_tokens_are_checked():
    text = "/-- Uses `z` and `n`. -/\ntheorem t (n : Nat) : True := trivial\n"
    msgs = [f.message for f in _lint(text, index=set())["t"].findings if f.code == "unresolved-ref"]
    assert msgs == ["`z` names no declaration found"]


def test_unresolved_ref_accepts_words_from_the_files_code():
    text = "/-- Reads `perm` of the cipher. -/\ndef useIt (c : Cipher K) : K := c.perm\n"
    assert "unresolved-ref" not in _codes(_lint(text, index=set())["useIt"])


def test_code_words_excludes_comments_and_strings():
    text = '/-- Refers to `gone`. -/\n-- gone was renamed\ndef t : String := "gone"\n'
    assert "unresolved-ref" in _codes(_lint(text, index=set())["t"])


def test_collect_names_ignores_code_examples_in_docstrings():
    names = set()
    dl._collect_names(
        "/-- Example:\n```\ntheorem stale : True := trivial\n```\n-/\ndef t := 1\n", names
    )
    assert names == {"t"}


def test_resolves_namespace_suffixes():
    idx = {"Foo.Bar.baz", "qux"}
    assert dl.resolves("baz", idx)
    assert dl.resolves("Bar.baz", idx)
    assert dl.resolves("Other.qux", idx)
    assert not dl.resolves("bazz", idx)


def test_no_resolve_when_index_is_none():
    out = _lint(index=None)
    assert "unresolved-ref" not in _codes(out["quux"])


def test_collect_names_tracks_namespaces():
    names = set()
    dl._collect_names(
        "namespace A\nnamespace B\ntheorem t : True := trivial\nend B\nend A\n", names
    )
    assert names == {"t", "A.B.t"}


def test_collect_names_sections_do_not_pop_namespaces():
    names = set()
    src = (
        "namespace Foo\nsection\ntheorem t : True := trivial\nend\n"
        "theorem u : True := trivial\nend Foo\n"
    )
    dl._collect_names(src, names)
    assert {"Foo.t", "Foo.u"} <= names


def test_collect_names_fields_and_constructors():
    names = set()
    src = (
        "namespace N\nstructure S where\n  /-- f -/\n  fld : Nat\n  other : Nat\n"
        "inductive T where\n  | mk\n  | cons (n : Nat)\nend N\n"
    )
    dl._collect_names(src, names)
    assert {"fld", "S.fld", "N.S.fld", "other", "mk", "T.mk", "cons", "T.cons"} <= names


def test_constructor_docstring_is_attached():
    text = (
        "inductive T where\n  /-- Nothing. -/\n  | none\n  /-- Something. -/\n  | some (n : Nat)\n"
    )
    bs = _blocks(text)
    assert [(b.decl_kind, b.decl_name) for b in bs] == [("ctor", "none"), ("ctor", "some")]
    out = _lint(text, index=set())
    assert "trivial" not in _codes(out["none"])


def test_probe_names(tmp_path):
    p = tmp_path / "extract.json"
    p.write_text(json.dumps({"data": {"probe:GCM.ghash": {}, "other": {}}}), encoding="utf-8")
    assert dl.load_probe_names(p) == {"GCM.ghash"}


# --------------------------------------------------------------------------- scope


def test_added_ranges_from_zero_context_diff():
    diff = "@@ -3,0 +4,2 @@\n+a\n+b\n@@ -10 +13 @@\n-x\n+y\n@@ -20,2 +23,0 @@\n-p\n-q\n"
    assert dl.added_ranges(diff) == [(4, 5), (13, 13)]


def test_in_ranges():
    b = dl.Block("f", 10, 12, "decl", "")
    assert dl.in_ranges(b, [(12, 20)])
    assert dl.in_ranges(b, [(1, 10)])
    assert not dl.in_ranges(b, [(1, 9), (13, 30)])


def test_scan_declared_names_includes_package_and_core_module_names(tmp_path, monkeypatch):
    (tmp_path / "Proj").mkdir()
    (tmp_path / "Proj" / "A.lean").write_text("def a := 1\n", encoding="utf-8")
    pkg = tmp_path / ".lake" / "packages" / "mathlib" / "Mathlib" / "Data"
    pkg.mkdir(parents=True)
    (pkg / "Nat.lean").write_text(
        "namespace Nat\ntheorem foo : True := trivial\nend Nat\n", encoding="utf-8"
    )
    monkeypatch.setattr(dl, "lean_core_src", lambda root: None)
    names = dl.scan_declared_names(tmp_path)
    assert {"Proj.A", "Mathlib.Data.Nat", "Data", "Nat.foo", "foo", "a"} <= names


def test_base_scope_words_come_from_the_whole_file(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    f = tmp_path / "A.lean"
    f.write_text(
        "/-- Mentions `gone` in an old docstring. -/\ntheorem old : True := trivial\n",
        encoding="utf-8",
    )
    git("add", "A.lean")
    git("commit", "-q", "-m", "base")
    f.write_text(
        f.read_text(encoding="utf-8") + "\n/-- Also `gone`. -/\ntheorem new : True := trivial\n",
        encoding="utf-8",
    )
    blocks = dl.lint(tmp_path, ["A.lean"], base="HEAD", max_line=100, name_index=set())
    assert [b.decl_name for b in blocks] == ["new"]
    assert "unresolved-ref" in _codes(blocks[0])  # the untouched docstring is not code


def test_base_scope_includes_renamed_files(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "A.lean").write_text(
        "/-- Old. -/\ntheorem old : True := trivial\n", encoding="utf-8"
    )
    git("add", "A.lean")
    git("commit", "-q", "-m", "base")
    git("mv", "A.lean", "B.lean")
    (tmp_path / "B.lean").write_text(
        "/-- Old. -/\ntheorem old : True := trivial\n/-- New. -/\ntheorem new : True := trivial\n",
        encoding="utf-8",
    )
    git("add", "-A")
    assert dl.git_changed_files(tmp_path, "HEAD") == ["B.lean"]


def test_pure_rename_contributes_all_blocks(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / "A.lean").write_text(
        "/-- Old. -/\ntheorem old : True := trivial\n", encoding="utf-8"
    )
    git("add", "A.lean")
    git("commit", "-q", "-m", "base")
    git("mv", "A.lean", "B.lean")
    git("commit", "-q", "-m", "rename")
    files = dl.git_changed_files(tmp_path, "HEAD~1")
    blocks = dl.lint(tmp_path, files, base="HEAD~1", max_line=100, name_index=None)
    assert [b.decl_name for b in blocks] == ["old"]  # git shows the new path as all-added


def test_base_scope_end_to_end(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    f = tmp_path / "A.lean"
    f.write_text("/-- Old one. -/\ntheorem old : True := trivial\n", encoding="utf-8")
    git("add", "A.lean")
    git("commit", "-q", "-m", "base")
    f.write_text(
        "/-- Old one. -/\ntheorem old : True := trivial\n\n"
        "/-- New (with a paren). -/\ntheorem new : True := trivial\n",
        encoding="utf-8",
    )
    blocks = dl.lint(tmp_path, ["A.lean"], base="HEAD", max_line=100, name_index=None)
    assert [b.decl_name for b in blocks] == ["new"]
    assert "paren" in _codes(blocks[0])


# --------------------------------------------------------------------------- output


def test_render_formats():
    out = _lint(index=set())
    blocks = list(out.values())
    text = dl.render_text(blocks)
    assert text.endswith("findings")
    gh = dl.render_github(blocks)
    assert "::warning file=Foo.lean,line=" in gh
    payload = json.loads(dl.render_json(blocks, dl.Path("/r"), {"all": True}))
    assert payload["schema"] == dl.SCHEMA
    assert {b["decl_name"] for b in payload["blocks"]} >= {"bar", "qux"}


def test_main_strict_exit(tmp_path):
    (tmp_path / "A.lean").write_text(
        "/-- " + "y" * 120 + " -/\ntheorem t : True := trivial\n", encoding="utf-8"
    )
    rc = dl.main(
        ["--root", str(tmp_path), "--all", "--no-resolve", "--strict", "--format", "github"]
    )
    assert rc == 1
    rc = dl.main(["--root", str(tmp_path), "--all", "--no-resolve", "--format", "json"])
    assert rc == 0
