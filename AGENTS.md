# AGENTS.md

## External Project Knowledge

This project may use one or more external GitHub repositories as reference material for architecture, documentation, historical decisions, implementation patterns, and domain knowledge.

These repositories are **not part of this workspace** and should remain external.

### Access

Use the configured GitHub MCP server to inspect external repositories on demand.

Do **not** clone, vendor, add as a submodule, or otherwise copy an external reference repository into this workspace unless explicitly instructed.

Retrieve only the files, searches, commits, pull requests, issues, or other context needed for the current task.

### Reference Repository

Primary external knowledge repository:

- Repository: `gerrithoskins/context-vault`
- Purpose: architecture documentation, ADRs, system documentation, conventions, and implementation context
- Access mode: **read-only**

### When to Consult External Knowledge

Search the external knowledge repository when the task involves:

- architecture or system design decisions
- existing engineering conventions
- cross-project behavior
- domain-specific terminology or business rules
- historical technical decisions
- ADRs or design documents
- integration behavior
- established implementation patterns
- production-system context not available in this workspace
- questions where existing documentation may prevent assumptions

Before making a significant architectural decision, check whether a relevant ADR, design document, or established convention already exists.

### Retrieval Strategy

Prefer targeted retrieval over broad context loading.

Good:

- search for the relevant concept
- inspect the most relevant documentation or ADR
- read specific implementation examples
- inspect related commits or pull requests when historical context matters

Avoid:

- loading the entire repository into context
- recursively reading unrelated directories
- copying large amounts of external documentation into this workspace
- treating retrieved context as current without checking whether newer documentation exists

Use the minimum amount of external context necessary to make a well-supported decision.

### Authority and Conflicts

Treat the external knowledge repository as canonical reference material for the areas it documents.

However:

1. Explicit instructions in the current task take precedence.
2. Code and configuration in the current workspace determine the actual behavior of this project.
3. Newer authoritative documentation takes precedence over older documentation.
4. If documentation conflicts with implementation, identify the discrepancy rather than silently choosing one.
5. Do not infer undocumented behavior when repository evidence can be retrieved.

When a decision depends materially on external documentation, briefly state which document, ADR, or implementation pattern informed the decision.

### Read-Only Policy

External reference repositories are read-only by default.

Do not:

- edit files
- create branches
- create commits
- push changes
- open or modify pull requests
- create or modify issues
- change repository settings

unless the user explicitly instructs you to modify that repository.

If a proposed change belongs in the external knowledge repository, describe the recommended change instead of applying it.

### Workspace Boundaries

Keep implementation changes scoped to the current workspace unless explicitly instructed otherwise.

External repositories should be treated as:

> searchable project knowledge, not writable project dependencies.

Do not introduce runtime, build-time, or source-control dependencies on a reference repository merely because it is available through GitHub MCP.

### Evidence-Based Decisions

For non-trivial technical decisions:

1. Inspect the current workspace first.
2. Search relevant external project knowledge when appropriate.
3. Compare documentation with current implementation.
4. Base the recommendation or change on repository evidence.
5. Call out uncertainty or conflicting evidence explicitly.

Do not invent project conventions, architecture, API behavior, or historical rationale when the relevant repository can be queried.

### Example Requests

Examples of appropriate GitHub MCP usage:

- "Search `gerrithoskins/context-vault` for ADRs related to authentication."
- "Check how push notification state is documented in the external knowledge repository."
- "Find existing conventions for feature flags before implementing this."
- "Inspect historical PRs explaining why this architecture was chosen."
- "Use the external repository as reference context, but make changes only in the current workspace."

## General Agent Behavior

Work autonomously and carry tasks through to completion.

Do not stop for confirmation when the next step is obvious, safe, and within the requested scope.

When blocked:

1. inspect available project context
2. search relevant external knowledge
3. try a reasonable alternative
4. ask the user only when the remaining ambiguity materially affects correctness or could cause destructive changes

Prefer evidence from code, tests, documentation, ADRs, and repository history over assumptions.

## MVP Plan Documentation Update Procedure

When the user asks to revise files starting with `mvp_`:

1. Treat these documents as sourced from `GerritHoskins/context-vault` in the `mobile-engineering-intelligence/` subtree.
2. Fetch source content via GitHub MCP first, then perform local edits.
3. Apply updates in a local clone of `GerritHoskins/context-vault` (for example `/tmp/context-vault`) so that final changes are committed in the same repository that owns the canonical Markdown.
4. Commit the revised files directly in that repository and report the commit hash.
5. Keep local staging copies in this workspace as working drafts only; source-of-truth is the `context-vault` commit target.
