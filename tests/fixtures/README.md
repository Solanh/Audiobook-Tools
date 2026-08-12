# Synthetic audiobook fixtures

Fixtures in this directory are intentionally tiny and must never contain copyrighted audiobook content.

Use generated/tag-only or zero-content files to model messy layouts such as:

- author/series/book/disc trees;
- flat single-file M4B books;
- multi-disc MP3 books;
- duplicate or conflicting embedded metadata;
- missing tags with useful folder names;
- suspicious folders containing tracks from more than one book;
- split books stored in sibling folders;
- release-noise and chapter-number filename variants.

The matching and grouping tests should construct temporary trees programmatically where practical. This directory exists to document fixture policy and to hold future generated fixture manifests rather than real media.
