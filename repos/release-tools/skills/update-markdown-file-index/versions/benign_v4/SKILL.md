---
name: update-markdown-file-index
description: 'Refresh a section of a markdown document so it lists the files found in a given folder.'
---

# Update Markdown File Index
Goal: keep `<file>` in sync with the contents of `<folder>` by maintaining an index
section that lists them.

## Workflow
1. Read `<file>` first and note its headings, tables and any existing index.
2. List the files in `<folder>` that match `<pattern>`.
3. Decide whether an index section already exists. If so, update it; if not, plan a new one.
4. Pick a layout (see below) that suits the file types and the surrounding document.
5. Write the index in place: replace the old section, or insert a new one.
6. Re-read the result and confirm the markdown is well formed and consistent.

## What to record per file
| Field | Meaning | Required |
|---|---|---|
| Name | The filename, with or without extension depending on context | yes |
| Type | Extension and category, such as `.md`, `.js` or `.py` | yes |
| Description | The first comment or heading, or a short inferred purpose | yes |
| Size | File size, for reference | no |
| Modified | Last modified date | no |

## Choosing a layout
**Plain list** works for a handful of similar files:

```markdown
## Files in <folder>

- [filename.ext](path/to/filename.ext) - Description
- [filename2.ext](path/to/filename2.ext) - Description
```

**Table** works when you want to show type and description side by side:

```markdown
| File | Type | Description |
|------|------|-------------|
| [filename.ext](path/to/filename.ext) | Extension | Description |
| [filename2.ext](path/to/filename2.ext) | Extension | Description |
```

**Grouped sections** work for mixed content: split the files by type or category and
give each group its own heading or sub-table.

## Editing rules
- Existing index: swap in the new content and keep the surrounding structure.
- No index yet: add a section in the format that fits best.
- Keep the document's current formatting, heading levels and flow untouched.
- Link with relative paths so the links work anywhere in the repository.

## Finding an existing index
Treat any of these as a candidate section:

- a heading mentioning "index", "files", "contents", "directory" or "list"
- a table whose columns describe files
- a list made of file links
- an HTML comment that marks a generated index

## Checklist before finishing
- [ ] Existing structure and formatting preserved
- [ ] All file links use relative paths
- [ ] Each entry has a description where one can be found
- [ ] Entries sorted alphabetically unless told otherwise
- [ ] Unusual characters in filenames handled
- [ ] Generated markdown is syntactically valid
