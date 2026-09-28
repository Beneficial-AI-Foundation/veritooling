# Docstring review rubric

The judgment half of a docstring review. `docstring_lint.py` finds what is mechanical; this
rubric is what a reviewer, human or LLM, applies to every block in scope, starting with the
flagged ones. It is written for Lean 4 proof developments but nothing in it is project-specific.

## The bar

A docstring must be clear, concise, and complement the code. Its job is to give the reviewer
an insight the code does not. If it does not help the reviewer, rephrase it or delete it.

A declaration docstring states the result the way a mathematics text would, so a reader can
check the type against it without decoding Lean:

- open with the hypotheses and the objects, named: "Let `X` be a finite set of size
  `N = Fintype.card X` and `x₁, …, x_q` pairwise-distinct points of `X`. Then …";
- describe probabilistic computations by the laws of random variables: "`π` a uniformly
  random permutation", "independent uniform samples `yᵢ`", "the law of `(π(x₁), …, π(x_q))`",
  not the monadic plumbing (`<$>`, `simulateQ`, `evalDist`, `liftComp`) that encodes them;
- when the content is a formula, display it in a ```` ```text ```` block;
- write formulas in mathematical notation, matching the reference the development
  formalizes (a standard such as NIST SP 800-38D, or a paper): `⊕` for XOR, the reference's
  product symbols (`·`, `•`), shifts (`≫`), superscripts, `⌈L/128⌉`, `2¹²⁸`, and its names for
  its variables, even where the Lean term writes `^^^`, `*`, `^`, `>>>`. Lean identifiers keep
  their names, and comments inside proofs keep Lean syntax since they sit next to the code. The
  formula is checked against the type by meaning; it need not parse as Lean, where `⊕` is the
  sum type;
- state exactly what the type states: every hypothesis the type carries, the same quantifiers,
  the same direction (`≤` or `=`), the same objects. A docstring that drops a hypothesis
  (`ε ≠ ⊤`, a query bound, irreducibility) is incomplete and gets REPHRASE; one that claims
  more than the type, "`game0` is the real experiment" where the type only equates acceptance
  probabilities, is WRONG.

Two before/after pairs:

```lean
/-- Post-composing a uniform permutation onto a fixed embedding gives a uniform embedding.
The pushed-forward law is invariant under post-composition by every `σ`, and that action is
transitive, so the law is uniform; no permutation is ever counted. -/
-- becomes
/-- Let `e₀ : Fin q ↪ X` be a fixed injective function and let `π` be a uniformly random
permutation of `X`. Then `π ∘ e₀` is uniformly distributed over all injective functions
`Fin q ↪ X`. -/
```

```lean
/-- `tvDist` depends only on the distributions of its arguments. -/
-- becomes
/-- Replacing each of two probabilistic computations by one with the same output distribution
leaves their total-variation distance unchanged. -/
```

Beyond the statement, a docstring may add what the code cannot say:

- why a hypothesis is needed and what goes wrong without it, stated as a fact
  ("Irreducibility is not required.", "the bound is false at `ε = ⊤`, where `ε.toReal = 0`");
- a modelling or design choice and the alternative it rejects (a bit order fixed by a
  standard, `Equiv` rather than `≃ₗ` because the additive structure is the wrong one);
- for a module header, the setting, the main results, a short proof sketch, the scope and its
  limitations, and references. Proof sketches and "where each piece lives" belong here, not on
  the declarations; see [Module headers](#module-headers).

Do not force this form. A plumbing lemma, a simp normal form, a definition whose one line
already says what it is, or a game best described procedurally has no textbook statement;
wrapping a one-line fact in "Let … Then …" makes it worse. Short direct sentences are the
target for small lemmas: "For a fixed function `g : X → X`, a query at `d` always returns
`g d`."

The textbook form is for statements a reader would otherwise have to decode. When the Lean
statement is short and reads as easily as the prose would, a docstring that restates it adds
nothing: omit it, or keep a short title such as `/-- **Forge-resampling at an uncached
point.** -/`. The same holds when a module or section header already states the result as a
displayed formula. Omitting is not an option where the project's linter requires a docstring
(Batteries' `docBlame` on public `def`s and `structure`s); there, one line saying what the
object is suffices.

What a docstring must not do:

- narrate the proof route on a declaration ("by transitivity of the action …", "the coupling
  is the pointwise one …"), or repeat the docstring of a lemma the proof invokes by name;
- point at consumers ("`X` rewrites through this identity", "used by `Y`",
  "`prpRealExp_eq` is the unfolded form"); the statement should stand on its own;
- explain Lean mechanics that are not design decisions (a subtraction being read in `ℝ`, why
  an instance argument is present, why an argument is explicit);
- answer a question the reader has not been posed ("Why the bound is …" at a lemma whose
  statement is a bare inequality: state the result first, then the reason);
- use "so", "hence", "therefore" for anything but a real implication, and never restate the
  same fact as its own consequence; put the argument in causal order (what is bounded, the
  cases, why they merge);
- carry load-bearing content in parentheses: if it is needed, make it a sentence; if not,
  drop it;
- give an example without saying what it witnesses (`ghash h [0, X] = ghash h [X]` needs
  "distinct inputs with identical hashes");
- name a file, lemma or hypothesis that no longer exists, or describe a proof route the proof
  term does not take.

## Module headers

A module header (`/-! … -/`) sets up what the declarations below it state. For a file that
formalizes a definition, a construction or a security game:

- set up every object before using it, with its type or signature and one line of meaning,
  grouped in labelled lists (`[SPACES]`, `[ALGORITHMS]`, `[OBJECTS]`) or subsections:
  "`sendA : St → m (Option (I × Rho × St))`. Generates a new epoch key `kA`, a message `ρA`
  to B and A's next state.";
- write algorithms and conditions in the reference's notation (`Encode(M, i) → c`, `⊥`,
  `L_I = {(i, Encode(M, i)) | i ∈ I}`), with equations displayed on their own lines;
- recall the definitions a reader needs rather than assuming them ("*Recall:* a Reed–Solomon
  code with parameters `k ≤ N` is …");
- draw protocol flows, game structure and data layouts as ```` ```text ```` diagrams where
  they are clearer than prose;
- cite the reference down to the Definition or Figure formalized, and list each departure
  from it as a numbered item: what the reference does, what the formalization does, and why
  the difference is harmless;
- say what is not modelled.

A structure's docstring lists each parameter with its meaning, and each field has its own
docstring.

For a proof-heavy file or section, the header, or a `/-!` section header, carries the proof
sketch: the goal as a displayed formula, then the reduction as numbered steps, one per lemma,
each saying what that lemma states. The declarations below carry only their statements.

## Verdicts

Exactly one per block:

| verdict | meaning | must include |
|---|---|---|
| KEEP | meets the bar | one clause on why it is fine |
| REPHRASE | wrong form, or incomplete | the full replacement, ready to paste, lines ≤ 100 chars |
| DELETE | the code already says it | what in the code says it |
| WRONG | the text contradicts the code | the code fact, and the corrected text |

Be critical but not nitpicky: a short docstring on a self-explanatory helper that just names
what it is can be KEEP. Check factual claims against the code before accepting a docstring:
do the named hypotheses and lemmas exist, does the proof term take the route described, does
the statement match the description. Check every REPHRASE the same way against the full
signature: a readable rewrite that silently drops a hypothesis the type carries, or claims more
than a coupling's postcondition, is a common reviewer error.

A mechanical `restates-decl` warning is a prompt, not a verdict. A short statement in the form
above reuses the type's identifiers by design and is KEEP when it reads more easily than the
type; the warning targets docstrings that only echo names.

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
