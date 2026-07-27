"""Regression tests for sorry-diff.py manifest parsing: same-named declarations
in different modules must stay distinct."""


def _manifest(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("# sorry-manifest v1\n" + "\n".join(lines) + "\n")
    return p


def test_same_name_different_module_kept_distinct(sorry_diff, tmp_path):
    path = _manifest(tmp_path, "m.txt", ["ModA thm direct", "ModB thm direct"])
    decls, version = sorry_diff.read_manifest(path)
    assert version == 1
    assert set(decls) == {("ModA", "thm"), ("ModB", "thm")}


def test_delta_detects_new_module_collision(sorry_diff, tmp_path):
    """Adding a same-named decl in a new module is a genuine new sorry, not a
    no-op masked by name-only keying."""
    base = _manifest(tmp_path, "base.txt", ["ModA thm direct"])
    head = _manifest(tmp_path, "head.txt", ["ModA thm direct", "ModB thm direct"])
    base_decls, _ = sorry_diff.read_manifest(base)
    head_decls, _ = sorry_diff.read_manifest(head)
    new_keys = set(head_decls) - set(base_decls)
    assert new_keys == {("ModB", "thm")}
