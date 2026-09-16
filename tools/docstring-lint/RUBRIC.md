# Docstring review rubric

The judgment half of a docstring review. `docstring_lint.py` finds what is mechanical; this
rubric is what a reviewer, human or LLM, applies to every block in scope, starting with the
flagged ones. It is written for Lean 4 proof developments but nothing in it is project-specific.

## The bar

A docstring must be clear, concise, and complement the code. Its job is to give the reviewer
an insight the code does not. If it does not help the reviewer, rephrase it or delete it.

What the code cannot say, and a docstring should:

- the role of the declaration in the larger proof, and the consumer that needs it
  ("`probEvent_wcInst_forge_le` takes this inequality as its `hfloor` hypothesis");
- why a hypothesis is not free, and what goes wrong without it;
- a modelling choice and the alternative it rejects;
- for a module header, the shape of the argument and where each piece lives.

What a docstring must not do:

- restate the type or the proof (a `Proof:` line mirroring a two-line `exact` is redundant, as
  is repeating the docstring of a lemma the proof invokes by name);
- answer a question the reader has not been posed ("Why the bound is …" at a lemma whose
  statement is a bare inequality: state the role first, then the reason);
- use "so", "hence", "therefore" for anything but a real implication, and never restate the
  same fact as its own consequence; put the argument in causal order (what is bounded, the
  cases, why they merge);
- carry load-bearing content in parentheses: if it is needed, make it a sentence; if not,
  drop it;
- give an example without saying what it witnesses (`ghash h [0, X] = ghash h [X]` needs
  "distinct inputs with identical hashes");
- name a file, lemma or hypothesis that no longer exists, or describe a proof route the proof
  term does not take.

## Verdicts

Exactly one per block:

| verdict | meaning | must include |
|---|---|---|
| KEEP | meets the bar | one clause on why it is fine |
| REPHRASE | right content, wrong form | the full replacement, ready to paste, lines ≤ 100 chars |
| DELETE | the code already says it | what in the code says it |
| WRONG | the text contradicts the code | the code fact, and the corrected text |

Be critical but not nitpicky: a short docstring on a self-explanatory helper that just names
what it is can be KEEP. Check factual claims against the code before accepting a docstring:
do the named hypotheses and lemmas exist, does the proof term take the route described, does
the statement match the description.

## Report format

One markdown file, findings grouped by file in source order, a summary table of the four
counts at the top, and code-level side notes (unused hypotheses, duplicated lemmas, dead
declarations found on the way) in their own section since they are not docstring edits:

````markdown
## `path/to/File.lean`
### `declName` (line N) — VERDICT
<one or two sentences: what a reviewer would not understand or not gain, or why it is fine>
```lean
/-- replacement text, for REPHRASE and WRONG -/
```
````

Mask markdown headings inside code fences when parsing the report: a docstring whose own
text contains `## References` otherwise splits an item.

## Applying the verdicts

Apply each accepted edit as an exact-text replacement of the old block, anchored by the
reported line to the nearest `/--` or `/-!` start, and assert the old text is unique in the
file. Count replacement line lengths in characters, not bytes. When the branch is reviewed
commit by commit, fold each edit into the commit that authored the docstring by applying the
same replacement to every original tree and rebuilding the chain, then check that the final
tree equals the edited working tree and that the project builds.
