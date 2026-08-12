# Read-only provider identification

`media-janitor identify-audiobooks` is the read-only provider-search stage after local inspection and comparison with the current Audiobookshelf library.

It is intentionally separate from proposal generation and writes.

## Why provider search comes after current-server matching

A book that Audiobookshelf already identifies strongly should not need another external metadata search. The command therefore:

1. scans and inspects the local audiobook tree;
2. reads the current Audiobookshelf library;
3. runs local-to-server matching;
4. removes `strong_candidate` items from the provider-search queue;
5. searches the selected metadata provider only for unresolved items, up to the configured cap.

This reduces unnecessary provider traffic and keeps existing trusted server metadata as evidence rather than discarding it.

## Usage

```bash
export AUDIOBOOKSHELF_URL='http://your-audiobookshelf-host:13378'
export AUDIOBOOKSHELF_API_KEY='your-api-key'

media-janitor identify-audiobooks /path/to/audiobooks \
  --provider audible \
  --max-provider-searches 10 \
  --json identify.json \
  --pretty
```

Use `--library-id` when the server has multiple book libraries.

The provider slug must be one returned by the server's read-only metadata-provider discovery endpoint. Custom Audiobookshelf metadata-provider slugs are therefore eligible without being hard-coded into Media Janitor.

## Why `audible` is the default

The default is `audible` because audiobook-specific results can include ASIN, narrator, duration, series, language, and abridged state in addition to title/author information. Those fields are useful for distinguishing an audiobook edition from the underlying book identity.

You can explicitly select another provider, for example:

```bash
media-janitor identify-audiobooks /path/to/audiobooks \
  --provider google \
  --json google-identify.json \
  --pretty
```

A Google Books result may strongly support the identity of the book while providing little or no evidence that it is the same audiobook edition. The report keeps those two questions separate.

## Identity confidence vs edition confidence

Provider candidates expose two scores:

- `identity_score`: evidence that the result represents the same underlying book/work;
- `edition_score`: evidence that the result represents the same audiobook edition.

Identity evidence can include:

- ASIN or ISBN agreement/conflict;
- title similarity;
- author similarity;
- series and sequence agreement.

Edition evidence is narrower:

- ASIN agreement;
- duration agreement;
- narrator agreement;
- ISBN agreement when available.

`edition_score` is `null` when the provider does not expose enough edition-specific data. A strong identity result with absent or weak edition evidence receives a warning rather than being promoted to an edition-level conclusion.

## Query cap

The default `--max-provider-searches 10` is deliberate. A single Audiobookshelf provider search may itself make one or more upstream requests, depending on the provider. A bounded first pass makes real-library testing predictable and avoids turning a bad grouping heuristic into a large burst of external lookups.

Increase the cap deliberately after inspecting initial reports.

## Safety boundary

This command performs local read-only inspection plus Audiobookshelf GET requests. It does not:

- rename or move media;
- write embedded tags;
- change Audiobookshelf metadata;
- trigger an Audiobookshelf library scan;
- approve candidates;
- generate an executable filesystem plan;
- call the journaled writer.

Provider results remain evidence for a later proposal/review layer.
