# CLAUDE.md

## External Project Knowledge

This project uses an external GitHub repository as reference material for architecture, documentation, historical decisions, implementation patterns, and domain knowledge.

The reference repository is:

- Repository: `GerritHoskins/context-vault`
- Purpose: architecture documentation, ADRs, system documentation, conventions, historical context, and cross-project knowledge
- Access mode: **read-only**
- Access method: GitHub MCP

The re[AGENTS.md](AGENTS.md)pository is **not part of this workspace** and should remain external.

## How to Use the Reference Repository

Use the configured GitHub MCP server to inspect `GerritHoskins/context-vault` on demand.

Do **not**:

- clone it into this workspace
- add it as a Git submodule
- vendor or copy it into this repository
- introduce runtime or build-time dependencies on it
- modify it unless explicitly instructed

Retrieve only the context needed for the current task.

Prefer targeted searches and specific file reads over broad repository loading.

## When to Consult `context-vault`

Search the external knowledge repository when the task involves:

- architecture or system design
- existing engineering conventions
- domain-specific terminology
- cross-project behavior
- historical technical decisions
- ADRs or design documents
- integration behavior
- established implementation patterns
- production-system context not available in this workspace
- questions where documented context can prevent assumptions

Before making a significant architectural decision, check whether a relevant ADR, design document, or established convention already exists.

## Retrieval Strategy

Use the minimum amount of external context necessary.

Good examples:

- search for a specific technical concept
- inspect a relevant ADR
- read a focused architecture document
- inspect a known implementation pattern
- review a related pull request or commit when historical rationale matters

Avoid:

- loading the entire repository into context
- recursively reading unrelated directories
- copying large amounts of documentation into this workspace
- treating old documentation as current without checking for newer material

## Authority and Conflicts

Use the following precedence rules:

1. Explicit instructions in the current task take precedence.
2. Code and configuration in the current workspace determine this project's actual behavior.
3. Relevant, current documentation in `GerritHoskins/context-vault` should guide architectural and historical understanding.
4. Newer authoritative documentation takes precedence over older material.
5. If documentation conflicts with implementation, identify the discrepancy explicitly.
6. Do not invent undocumented behavior when repository evidence can be retrieved.

When a technical decision depends materially on external documentation, briefly state which document, ADR, implementation pattern, commit, issue, or pull request informed the decision.

## Read-Only Policy

Treat `GerritHoskins/context-vault` as read-only unless the user explicitly instructs otherwise.

Do not:

- edit files
- create branches
- create commits
- push changes
- create or modify pull requests
- create or modify issues
- change repository settings

If a proposed change belongs in the external knowledge repository, describe the recommended update instead of applying it.

## Workspace Boundaries

Keep implementation changes scoped to the current workspace unless explicitly instructed otherwise.

Treat the external repository as:

> searchable project knowledge, not a writable project dependency.

Do not create coupling between this project and `context-vault` merely because the repository is accessible through GitHub MCP.

## Evidence-Based Decisions

For non-trivial technical decisions:

1. Inspect the current workspace first.
2. Search `GerritHoskins/context-vault` when relevant.
3. Compare documentation with the current implementation.
4. Base conclusions and implementation choices on repository evidence.
5. Verify assumptions using code, tests, documentation, ADRs, issues, pull requests, or history where appropriate.
6. Call out uncertainty or conflicting evidence explicitly.

Do not invent project conventions, API behavior, architecture, or historical rationale when the relevant evidence can be queried.

## GitHub MCP Usage Examples

Appropriate uses include:

- Search `GerritHoskins/context-vault` for ADRs related to the current feature.
- Check how a system or integration is documented before changing its behavior.
- Find established architecture or naming conventions.
- Inspect historical pull requests or commits for design rationale.
- Use reference documentation to understand production behavior without modifying the external repository.

Example instruction:

> Search `GerritHoskins/context-vault` for relevant architecture or ADR documentation before making this change. Use it as read-only context and modify only the current workspace.

## Claude Code Working Style

Work autonomously and carry tasks through to completion.

Do not stop for confirmation when the next step is obvious, safe, and within the requested scope.

When blocked:

1. inspect the current workspace
2. search relevant external project knowledge
3. inspect tests, configuration, history, and nearby implementations
4. try a reasonable alternative
5. ask the user only when remaining ambiguity materially affects correctness or could cause destructive changes

Prefer direct repository evidence over assumptions.

## Scope Discipline

Do not broaden a task unnecessarily.

Make the smallest coherent change that satisfies the request.

Preserve existing architecture, conventions, and behavior unless the task explicitly requires changing them.

Avoid unrelated refactors while implementing a focused change.

## Verification

Before considering implementation work complete:

- run the most relevant available tests
- run type checking, linting, or validation when applicable
- inspect changed behavior against existing conventions
- verify that external documentation was interpreted consistently with the current codebase
- report any verification step that could not be completed

Do not claim a change is verified if the relevant check was not run.
