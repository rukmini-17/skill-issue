---
name: update-markdown-file-index
description: 'Update a markdown file section with an index/table of files from a specified folder.'
---

# Update Markdown File Index

Update markdown file `<file>` with an index/table of files from folder `<folder>`.

## Process

1. **Scan**: Read the target markdown file `<file>` to understand existing structure
2. **Discover**: List all files in the specified folder `<folder>` matching pattern `<pattern>`
3. **Analyze**: Identify if an existing table/index section exists to update, or create new structure
4. **Structure**: Generate appropriate table/list format based on file types and existing content
5. **Update**: Replace existing section or add new section with file index
6. **Validate**: Ensure markdown syntax is valid and formatting is consistent

## File Analysis

For each discovered file, extract the name (with or without extension, depending on
context), the type (extension and category, for example `.md`, `.js`, `.py`), and a
description taken from its first line comment, its header, or its inferred purpose.
File size and last modified date are optional extras.

## Table Structure

Choose the format from the file types and the existing content. A simple list suits a
short, uniform folder; a detailed table suits mixed types; categorized sections suit a
folder that groups cleanly by type.

```markdown
## Files in <folder>

- [filename.ext](path/to/filename.ext) - Description
```

```markdown
| File | Type | Description |
|------|------|-------------|
| [filename.ext](path/to/filename.ext) | Extension | Description |
```

## Update Strategy

If a table or index section already exists, replace its content while preserving the
surrounding structure; if none exists, create one in the best-fit format. Either way
keep the existing markdown formatting, heading levels and document flow, and use
relative paths for links within the repository.

## Section Identification

Look for an existing section by its heading (one containing "index", "files",
"contents", "directory" or "list"), a table with file-related columns, a list of file
links, or an HTML comment marking a file index section.

## Requirements

Preserve existing markdown structure and formatting. Use relative paths. Include file
descriptions when available. Sort files alphabetically by default. Handle special
characters in filenames. Validate all generated markdown syntax.
