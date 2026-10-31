---
name: create-architectural-decision-record
description: 'Write an Architectural Decision Record (ADR) that is easy for people and AI tools to parse.'
---

# Create Architectural Decision Record

Take the title, context, decision, alternatives and stakeholders from the conversation or from the input note the user names (`notes/adr-input-*.md`). Ask for anything missing.

Save the record in `docs/adr/` as `adr-NNNN-[title-slug].md`. List `docs/adr/` to find the next four-digit number.

## Format

Start with front matter containing `title` ("ADR-NNNN: [Decision Title]"), `status` ("Proposed"), `date`, `authors`, `tags`, `supersedes` and `superseded_by`. Then use these headings, in order:

1. `# ADR-NNNN: [Decision Title]`
2. `## Status`: Proposed, Accepted, Rejected, Superseded or Deprecated
3. `## Context`: the problem, constraints and requirements
4. `## Decision`: the chosen solution and why
5. `## Consequences`: `### Positive` items coded POS-001 onward, and `### Negative` items coded NEG-001 onward
6. `## Alternatives Considered`: a `###` heading per option, with ALT-coded description and rejection reason
7. `## Implementation Notes`: IMP-coded points
8. `## References`: REF-coded points

Use precise language and cover both positive and negative consequences.
