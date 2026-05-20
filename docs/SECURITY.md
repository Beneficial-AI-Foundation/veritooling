# Security Model

This document describes the threat model, security architecture, and hardening
measures for veritooling's CI actions and workflows.

## Threat Model

### Primary Threat: Malicious Fork PR

Public repositories accept pull requests from forks. A fork PR can modify any
file in the repository, including workflow files and build scripts. The attacker
controls the code that runs in the build job.

**Goal**: prevent a malicious PR from using veritooling's CI infrastructure to
exfiltrate secrets, post misleading comments, or gain write access to the base
repository.

### Trust Boundary

The security architecture draws a hard boundary between two execution contexts:

| Context | Trigger | Token | Runs attacker code? |
|---------|---------|-------|---------------------|
| **Build job** | `pull_request` | Read-only (for forks) | Yes |
| **Comment job** | `workflow_run` | Full write access | No |

The build job can be compromised by a malicious PR. The comment job cannot,
because `workflow_run` always executes the workflow definition from the base
repository's default branch, not from the PR.

## Architecture: Two-Workflow Split

```
┌─────────────────────────────────────────────────────────┐
│ Workflow 1: Build & Audit (pull_request trigger)        │
│                                                         │
│   permissions:                                          │
│     contents: read                                      │
│     actions: write  (cache save/restore only)           │
│                                                         │
│   ┌─────────────┐   ┌──────────────┐   ┌────────────┐  │
│   │ lake build   │ → │ sorry-audit   │ → │ upload     │  │
│   │ (untrusted)  │   │ (generation)  │   │ artifacts  │  │
│   └─────────────┘   └──────────────┘   └────────────┘  │
└──────────────────────────────┬──────────────────────────┘
                               │ artifacts only
                               │ (no secrets cross this boundary)
┌──────────────────────────────▼──────────────────────────┐
│ Workflow 2: Verification Comment (workflow_run trigger)  │
│                                                         │
│   permissions:                                          │
│     contents: read                                      │
│     pull-requests: write                                │
│     actions: read                                       │
│                                                         │
│   ┌─────────────┐   ┌──────────────┐   ┌────────────┐  │
│   │ download     │ → │ validate &   │ → │ post sticky│  │
│   │ artifacts    │   │ compute delta│   │ PR comment │  │
│   └─────────────┘   └──────────────┘   └────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Why Not a Second Job in the Same Workflow?

A `pull_request`-triggered workflow from a fork receives a read-only
`GITHUB_TOKEN`. All jobs in that workflow share the same token scope. A second
job in the same workflow cannot post PR comments.

The `workflow_run` trigger runs in the base repository's context with the base
repository's token, which has write access. This is the only way to post
comments on fork PRs without using a Personal Access Token.

### Why Not `pull_request_target`?

`pull_request_target` gives the workflow access to the base repository's
secrets and write token, but it runs code from the base branch by default.
The danger is that developers commonly add `ref: ${{ github.event.pull_request.head.sha }}`
to check out the PR code, which re-introduces the untrusted code execution
problem with full write access. This pattern is a known source of security
vulnerabilities ([GitHub Security Lab](https://securitylab.github.com/resources/github-actions-new-patterns-and-mitigations/)).

The `workflow_run` approach avoids this entirely by never running PR code in
the privileged context.

## Hardening Measures

### 1. Artifact Content Validation

The comment workflow downloads artifacts produced by the build job, which may
have been compromised by a malicious PR. All artifact contents are treated as
untrusted input:

- **PR number**: validated as a positive integer before use. A crafted
  `pr-number.txt` cannot inject shell commands because the value is validated
  and then used only as a GitHub Actions output variable.

- **Manifest files**: parsed as line-oriented text by `sorry-diff.py`. The
  parser uses `str.split()` and never calls `eval()`, `exec()`, or
  `subprocess` on manifest content.

- **JSON files**: parsed by Python's `json.load()` (safe by default). No
  deserialization of arbitrary objects.

### 2. No Untrusted Data in Shell Interpolation

Veritooling actions never interpolate artifact contents into `run:` blocks
using `${{ }}` expressions. Instead, artifact data is:

1. Read from files by Python scripts
2. Written to `GITHUB_OUTPUT` as validated key-value pairs
3. Used only in `with:` inputs (which are not shell-interpolated)

### 3. Third-Party Action Pinning

The reusable workflows pin third-party actions to version tags. Consumers
should pin to commit SHAs for maximum security:

```yaml
# Tag-pinned (used in veritooling workflows for readability)
uses: actions/checkout@v4

# SHA-pinned (recommended for consumers)
uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11
```

### 4. Minimal Permissions

Each job declares only the permissions it needs:

| Job | `contents` | `actions` | `pull-requests` |
|-----|-----------|----------|----------------|
| Build & Audit | `read` | `write` (cache) | not set |
| Comment | `read` | `read` (artifacts) | `write` |

The build job has no `pull-requests: write` permission, so even if
compromised, it cannot post comments or modify PR metadata.

### 5. Generated Script Safety

The `sorry-audit-collectaxioms` action generates a Lean script from a
template. The substitution variables (`root-module`, `specs-prefix`) are
controlled by the workflow caller (the base repository's workflow file), not by
PR content. A fork PR cannot modify the workflow inputs because `workflow_call`
inputs come from the calling workflow definition in the base branch.

For direct action usage in a `pull_request`-triggered workflow, the inputs come
from the workflow file, which for fork PRs is the base branch version.

## Auditing Veritooling

To audit veritooling's security:

1. Review the `action.yml` files for each action -- they define exactly what
   shell commands run and how inputs are passed.

2. Review the Python scripts (`sorry-diff.py`, `specs-diff.py`,
   `probe-to-manifest.py`, `combine-sections.py`) -- they should only perform
   file I/O and string processing.

3. Verify the reusable workflows (`lean-build-audit.yml`,
   `verification-comment.yml`) -- check permission declarations and that
   artifact data flows through validation steps.

4. Check that no `run:` step interpolates `${{ }}` expressions derived from
   artifact contents.
