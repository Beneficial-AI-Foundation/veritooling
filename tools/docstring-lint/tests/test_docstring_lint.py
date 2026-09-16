"""docstring_lint: parsing, each mechanical check, diff scoping and output formats."""

import itertools
import json
import subprocess

import docstring_lint as dl
import pytest

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


def test_attach_skips_an_ordinary_comment_before_the_declaration():
    text = "/-- Doc. -/\n/- a note\nspanning two lines -/\ntheorem t : True := trivial\n"
    (b,) = _blocks(text)
    assert (b.decl_kind, b.decl_name, b.decl_line) == ("theorem", "t", 4)


def test_attach_crosses_a_comment_longer_than_a_few_lines():
    text = "/-- Doc. -/\n/- note\n" + "more\n" * 20 + "-/\ntheorem t : True := trivial\n"
    (b,) = _blocks(text)
    assert (b.decl_kind, b.decl_name) == ("theorem", "t")


def test_attach_reads_a_declaration_on_its_attribute_line():
    text = "/-- Doc. -/\n@[simp] theorem t : True := trivial\n"
    (b,) = _blocks(text)
    assert (b.decl_kind, b.decl_name, b.decl_line) == ("theorem", "t", 2)


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


def test_character_literal_holding_a_quote_does_not_swallow_the_next_docstring():
    text = "def quote : Char := '\"'\n/-- Real. -/\ndef t := 1\n"
    assert [b.decl_name for b in _blocks(text)] == ["t"]


def test_prime_in_an_identifier_is_not_a_character_literal():
    text = "theorem h' (x'' : Nat) : True := trivial\n/-- Real. -/\ndef t := 1\n"
    assert [b.decl_name for b in _blocks(text)] == ["t"]


def test_raw_string_ends_only_at_its_hash_delimiter():
    # An unpaired `"` in the body desynchronizes a scanner that does not know `r#"`.
    text = (
        'def css : String := r#"\n  label: "x\n  /-- injected -/\n'
        '  theorem fake : True := trivial\n"#\n\n/-- Real. -/\ndef t := 1\n'
    )
    assert [b.decl_name for b in _blocks(text)] == ["t"]
    names = set()
    dl._collect_names(text, names)
    assert "fake" not in names and "css" in names


# Valid Lean whose `"` or `/-` a naive scanner reads as opening something. Each desynchronizes
# the scan for the rest of the file, so every later docstring stops being enumerated: the one
# failure that silently removes work from the review rather than adding noise to it.
DESYNC_FORMS = [
    'def «quote"» := 0',
    "def «/-» := 0",
    'def r := s!"{"/-"}"',
    'def s : String := r#"a "b /-- x -/ "#',
    "def quote : Char := '\"'",
]


@pytest.mark.parametrize("form", DESYNC_FORMS, ids=lambda f: f.split(":=")[0].strip())
def test_a_docstring_after_an_exotic_lexical_form_is_still_enumerated(form):
    text = (
        f"/-- First. -/\ndef a := 0\n{form}\n"
        "/-- Second. -/\ndef b := 1\n/-- Third. -/\ndef c := 2\n"
    )
    assert [b.decl_name for b in _blocks(text)] == ["a", "b", "c"]


def test_an_interpolated_string_does_not_invent_a_docstring():
    text = 'def r := s!"{"/-- Fake. -/"}"\ndef u := 1\n'
    assert _blocks(text) == []


def test_interpolation_braces_may_hold_several_strings():
    text = 'def r := s!"a {f (g "x") "y"} b"\n/-- Real. -/\ndef t := 1\n'
    assert [b.decl_name for b in _blocks(text)] == ["t"]


def test_a_guillemet_identifier_stays_in_the_code_view():
    # It is a span only so the scanner skips its body; blanking it would lose the name it
    # declares from both `DECL_RE` and `code_words`.
    text = "/-- Doc. -/\ndef «my name» := 1\n"
    (b,) = _blocks(text)
    assert b.decl_name == "«my name»"
    names = set()
    dl._collect_names(text, names)
    assert names == {"«my name»"}


# --------------------------------------------------------------------------- span invariants

_FRAGMENTS = [
    "/-- doc -/",
    "/-! header -/",
    "/- comment -/",
    "-- line",
    '"plain"',
    'r#"raw "q" -/"#',
    's!"interp {f "x"} y"',
    "'\"'",
    'def «w"» := 0',
    "def «/-» := 0",
    "theorem h' : True := trivial",
    "\n",
]


def _fragment_pairs():
    """Every ordered pair of the lexical fragments above, as one source file each."""
    return ["\n".join(c) + "\n" for c in itertools.permutations(_FRAGMENTS, 2)]


def test_spans_partition_the_source():
    # Ordered, non-overlapping, and spans plus the gaps between them reconstruct the source.
    for src in _fragment_pairs():
        spans = dl.scan_spans(src)
        assert all(a.end <= b.start for a, b in zip(spans, spans[1:], strict=False)), src
        rebuilt, pos = [], 0
        for sp in spans:
            assert 0 <= sp.start <= sp.end <= len(src), src
            rebuilt.append(src[pos : sp.start])
            rebuilt.append(src[sp.start : sp.end])
            pos = sp.end
        rebuilt.append(src[pos:])
        assert "".join(rebuilt) == src


def test_blanking_preserves_length_and_lines():
    # Every consumer indexes the blanked views by the raw file's offsets and line numbers, so a
    # view that loses a character or a newline silently misplaces every finding after it.
    for src in _fragment_pairs():
        for keep_strings in (False, True):
            out = dl.code_only(src, keep_strings=keep_strings)
            assert len(out) == len(src), src
            assert out.count("\n") == src.count("\n"), src


def test_code_views_agree_with_code_only():
    src = "\n".join(_FRAGMENTS) + "\n"
    blanked, literals = dl.code_views(src)
    assert blanked == dl.code_only(src).split("\n")
    assert literals == dl.code_only(src, keep_strings=True).split("\n")


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


def test_long_line_measures_the_docstring_not_the_declaration_after_it():
    text = "/-- Short. -/ theorem t (n : Nat) : " + " ∧ ".join(["n = n"] * 20) + " := by simp\n"
    assert len(text.split("\n")[0]) > 100
    out = _lint(text, index=set())
    assert "long-line" not in _codes(out["t"])


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
    text = "/-- `fooBarBaz` -/\ntheorem fooBarBaz : True := trivial\n"  # the name, quoted
    assert "name-restated" in _codes(_lint(text, index=set())["fooBarBaz"])
    text = "/-- Bounds `fooBarBaz` from below. -/\ntheorem fooBarBaz : True := trivial\n"
    assert "name-restated" not in _codes(_lint(text, index=set())["fooBarBaz"])


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


def test_multiline_docstring_closing_beside_the_declaration_is_not_the_signature():
    # Slicing raw source from the declaration line starts inside the comment, so there is no
    # `/--` left to recognize and the docstring reads as its own statement: 100% overlap, always.
    text = (
        "/-- A useful calculation\n"
        "using `alpha`, `beta`, and `gamma`. -/ theorem exampleValue : True := trivial\n"
    )
    out = _lint(text, index=set())
    assert "restates-decl" not in _codes(out["exampleValue"])


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


def test_unresolved_ref_skips_every_notation_range():
    # The documented exemption is "superscripts or subscripts"; `ⱼ` (U+2C7C) and `ᶜ` (U+1D9C)
    # sit outside the ranges the pattern first covered.
    text = "/-- Uses `xⱼ`, `mⱼ`, `xᶜ`, `x₀`, `xᵥ` and `x¹²⁸`. -/\ndef t := 1\n"
    assert "unresolved-ref" not in _codes(_lint(text, index=set())["t"])


def test_unresolved_ref_ignores_backticks_inside_a_fenced_example():
    # Every other check reads `_prose`, which blanks fences; this one used to read the raw text,
    # so a placeholder in a code example was resolved like a reference.
    text = (
        "/-- Example:\n```lean\n-- `placeholderXyz` is the gap\n"
        "theorem e : True := trivial\n```\n-/\ndef d := 1\n"
    )
    assert "unresolved-ref" not in _codes(_lint(text, index=set())["d"])
    # ... but a reference in the prose around the fence is still checked.
    text = text.replace("/-- Example:", "/-- Uses `goneXyz`. Example:")
    msgs = [f.message for f in _lint(text, index=set())["d"].findings if f.code == "unresolved-ref"]
    assert msgs == ["`goneXyz` names no declaration found"]


def test_unresolved_ref_skips_lean_commands_and_keywords():
    text = "/-- A `macro`, its `syntax`, the `where` block and `set_option`. -/\ndef t := 1\n"
    assert "unresolved-ref" not in _codes(_lint(text, index=set())["t"])


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


def test_collect_names_ignores_string_literal_bodies():
    names = set()
    dl._collect_names(
        'def sample : String :=\n  "theorem stale : True := trivial\n'
        '   structure Ghost where\n     phantom : Nat\n  "\n',
        names,
    )
    assert names == {"sample"}


def test_collect_names_scope_survives_an_end_inside_a_string():
    names = set()
    dl._collect_names('namespace N\ndef t := "\n  end\n"\ndef u := 2\nend N\n', names)
    assert {"N.t", "N.u"} <= names


def test_suffix_index_resolves_exactly_like_the_scan():
    idx = {"A.B.c", "map", "Foo.bar"}
    suf = dl.suffix_index(idx)
    assert suf == {"B.c", "c", "bar"}
    for tok in ("A.B.c", "B.c", "c", "bar", "Invented.map", "nope", "Foo.bar.baz"):
        assert dl.resolves(tok, idx, suf) == dl.resolves(tok, idx), tok


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


def test_universe_parameters_are_not_part_of_the_name():
    text = "/-- Doc. -/\nabbrev GrpMax.{u1, u2} := GrpCat.{max u1 u2}\n"
    (b,) = _blocks(text)
    assert b.decl_name == "GrpMax"
    names = set()
    dl._collect_names("namespace N\nstructure S.{u} where\n  fld : Nat\nend N\n", names)
    assert {"S", "N.S", "S.fld", "N.S.fld"} <= names


def test_scoped_notation_with_a_namespace_attaches_and_is_indexed():
    text = '/-- Doc. -/\nscoped[omegaLimit] notation "ω" => omegaLimit\n'
    (b,) = _blocks(text)
    assert (b.decl_kind, b.decl_name) == ("notation", "ω")
    names = set()
    dl._collect_names('scoped[PFunctor] infixl:70 " ⊗ " => tensor\n', names)
    assert "⊗" in names


def test_collect_names_mutual_end_does_not_pop_a_namespace():
    names = set()
    src = "namespace Foo\nmutual\ndef t : Nat := 1\nend\ndef u : Nat := 2\nend Foo\n"
    dl._collect_names(src, names)
    assert {"Foo.t", "Foo.u"} <= names


def test_collect_names_indexes_string_literal_declaration_names():
    names = set()
    src = 'syntax "vcvSupport" : tactic\nelab "regPrelude" : command => pure ()\n'
    dl._collect_names(src, names)
    assert {"vcvSupport", "regPrelude"} <= names


def test_notation_name_is_the_literal_not_the_arrow():
    text = '/-- Doc. -/\nnotation "⟦" x "⟧" => f x\n'
    (b,) = _blocks(text)
    assert (b.decl_kind, b.decl_name) == ("notation", "⟦")


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


def test_main_reports_a_bad_probe_file(tmp_path, capsys):
    (tmp_path / "A.lean").write_text("/-- Doc. -/\ntheorem t : True := trivial\n", encoding="utf-8")
    bad = tmp_path / "extract.json"
    for content in ("{", json.dumps({"data": None})):  # malformed, then the wrong shape
        bad.write_text(content, encoding="utf-8")
        rc = dl.main(["--root", str(tmp_path), "--all", "--probe", str(bad)])
        assert rc == 2
        assert "--probe" in capsys.readouterr().err
    rc = dl.main(["--root", str(tmp_path), "--all", "--probe", str(tmp_path / "gone.json")])
    assert rc == 2


# --------------------------------------------------------------------------- scope


def test_touched_ranges_from_zero_context_diff():
    diff = "@@ -3,0 +4,2 @@\n+a\n+b\n@@ -10 +13 @@\n-x\n+y\n@@ -20,2 +23,0 @@\n-p\n-q\n"
    # the last hunk deletes two lines and adds none: the gap they sat in is (23, 24)
    assert dl.touched_ranges(diff) == [(4, 5), (13, 13), (23, 24)]


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
    assert [b.decl_name for b in blocks] == ["old"]  # `--no-renames`: the new path is all-added


def test_renamed_and_edited_file_contributes_untouched_blocks(tmp_path):
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
    git("commit", "-q", "-m", "rename and extend")
    files = dl.git_changed_files(tmp_path, "HEAD~1")
    blocks = dl.lint(tmp_path, files, base="HEAD~1", max_line=100, name_index=None)
    assert [b.decl_name for b in blocks] == ["old", "new"]


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


def test_base_scope_includes_a_block_only_shortened(tmp_path):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    f = tmp_path / "A.lean"
    f.write_text(
        "/--\nKept line (with a paren).\nDropped line.\n-/\ntheorem t : True := trivial\n",
        encoding="utf-8",
    )
    git("add", "A.lean")
    git("commit", "-q", "-m", "base")
    f.write_text(
        "/--\nKept line (with a paren).\n-/\ntheorem t : True := trivial\n", encoding="utf-8"
    )
    blocks = dl.lint(tmp_path, ["A.lean"], base="HEAD", max_line=100, name_index=None)
    assert [b.decl_name for b in blocks] == ["t"]  # deletion-only hunk still selects the block


def test_base_scope_in_a_git_subdirectory_and_with_a_quoted_path(tmp_path, capsys):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    proj = tmp_path / "lean"
    proj.mkdir()
    (tmp_path / "other").mkdir()
    (proj / "A.lean").write_text("/-- Old. -/\ntheorem old : True := trivial\n", encoding="utf-8")
    (tmp_path / "other" / "B.lean").write_text("/-- Out. -/\ndef out := 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    (proj / "A.lean").write_text(
        "/-- Old. -/\ntheorem old : True := trivial\n/-- New. -/\ntheorem new : True := trivial\n",
        encoding="utf-8",
    )
    # git C-quotes this name unless it is read with -z
    (proj / "α.lean").write_text("/-- Greek. -/\ntheorem u : True := trivial\n", encoding="utf-8")
    (tmp_path / "other" / "B.lean").write_text("/-- Out. -/\ndef out := 2\n", encoding="utf-8")
    git("add", "-A")
    # paths are relative to --root, and the file outside the project is not linted
    assert dl.git_changed_files(proj, "HEAD") == ["A.lean", "α.lean"]
    rc = dl.main(["--root", str(proj), "--base", "HEAD", "--no-resolve"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "2 blocks" in out and "α.lean" in out and "B.lean" not in out


def _repo_with_a_long_docstring(tmp_path):
    """A repository whose worktree adds an overlong docstring since HEAD."""

    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    f = tmp_path / "A.lean"
    f.write_text("/--\nshort\n-/\ntheorem t : True := trivial\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    f.write_text(f"/--\n{'y' * 120}\n-/\ntheorem t : True := trivial\n", encoding="utf-8")
    return git


@pytest.mark.parametrize(
    "setting",
    [
        ("config", "color.ui", "always"),  # colour escapes before the `@@`
        ("config", "diff.external", "/bin/true"),  # an external differ emits no hunks
        ("attributes", "*.lean -diff"),  # the file is reported as binary
    ],
    ids=["color.ui", "diff.external", "gitattributes"],
)
def test_base_scope_survives_git_display_settings(tmp_path, setting):
    # Each of these reshapes `git diff` so the anchored hunk regex matches nothing, and every
    # docstring on the branch would silently escape review.
    git = _repo_with_a_long_docstring(tmp_path)
    if setting[0] == "attributes":
        (tmp_path / ".gitattributes").write_text(setting[1] + "\n", encoding="utf-8")
    else:
        git(*setting)
    blocks = dl.lint(tmp_path, ["A.lean"], base="HEAD", max_line=100, name_index=None)
    assert [b.decl_name for b in blocks] == ["t"]
    assert "long-line" in _codes(blocks[0])


def test_main_rejects_a_nonexistent_root(tmp_path, capsys):
    rc = dl.main(["--root", str(tmp_path / "gone"), "--all", "--no-resolve", "--strict"])
    assert rc == 2
    assert "not a directory" in capsys.readouterr().err


@pytest.mark.parametrize(
    "base", ["origin/nope", "--no-patch"], ids=["unknown-ref", "option-shaped"]
)
def test_main_reports_an_unresolvable_base(tmp_path, capsys, base):
    # An unknown ref used to raise CalledProcessError with git's message swallowed, and a value
    # git reads as an option used to empty the block list and exit 0. `--base=` because argparse
    # would otherwise take `--no-patch` for one of its own options.
    _repo_with_a_long_docstring(tmp_path)
    rc = dl.main(["--root", str(tmp_path), f"--base={base}", "--no-resolve"])
    assert rc == 2
    assert base in capsys.readouterr().err


def test_main_reports_a_base_outside_a_repository(tmp_path, capsys):
    (tmp_path / "A.lean").write_text("/-- Doc. -/\ntheorem t : True := trivial\n", encoding="utf-8")
    rc = dl.main(["--root", str(tmp_path), "--base", "HEAD", "--no-resolve"])
    assert rc == 2
    assert "not a git repository" in capsys.readouterr().err


def test_git_resolve_returns_the_commit_the_diffs_are_given(tmp_path):
    _repo_with_a_long_docstring(tmp_path)
    commit, why = dl.git_resolve(tmp_path, "HEAD")
    assert why == "" and commit is not None and len(commit) == 40
    assert dl.git_resolve(tmp_path, "origin/nope") == (None, "not a commit: origin/nope")


# --------------------------------------------------------------------------- output


def test_render_github_escapes_workflow_command_data():
    b = dl.Block("dir,A:B.lean", 1, 1, "decl", "")
    b.add("paren", "info", 1, "100% of it\nand a second line")
    gh = dl.render_github([b])
    assert gh == ("::warning file=dir%2CA%3AB.lean,line=1::paren: 100%25 of it%0Aand a second line")


def test_render_github_rebases_paths_on_the_repository_root(tmp_path):
    # GitHub resolves `file=` against the checkout root; block paths are relative to `--root`.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    proj = tmp_path / "project"
    proj.mkdir()
    assert dl.repo_prefix(proj) == "project/"
    assert dl.repo_prefix(tmp_path) == ""
    b = dl.Block("A.lean", 1, 1, "decl", "")
    b.add("long-line", "error", 1, "117 characters, limit 100")
    assert dl.render_github([b], "project/").startswith("::error file=project/A.lean,line=1::")


def test_repo_prefix_is_empty_outside_a_repository(tmp_path):
    assert dl.repo_prefix(tmp_path) == ""


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


def test_main_reports_an_unreadable_requested_file(tmp_path, capsys):
    (tmp_path / "A.lean").write_text("/-- Doc. -/\ntheorem t : True := trivial\n", encoding="utf-8")
    rc = dl.main(["--root", str(tmp_path), "--files", "A.lean", "Typo.lean", "--no-resolve"])
    assert rc == 2
    assert "Typo.lean" in capsys.readouterr().err
    rc = dl.main(["--root", str(tmp_path), "--files", "A.lean", "--no-resolve"])
    assert rc == 0


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
