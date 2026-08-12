# Audiobookshelf matching

`media-janitor match-audiobookshelf` is a read-only comparison step between the local filesystem inspection and the items already known to Audiobookshelf.

It does not rename files, update metadata, trigger a scan, call provider match endpoints, or create an executable cleanup plan.

## Usage

```bash
export AUDIOBOOKSHELF_URL='http://your-audiobookshelf-host:13378'
export AUDIOBOOKSHELF_API_KEY='your-api-key'

media-janitor match-audiobookshelf /path/to/audiobooks \
  --json matches.json \
  --pretty
```

If more than one book library exists, pass `--library-id`.

The command:

1. scans the local audiobook tree read-only;
2. groups files into likely audiobook items;
3. reads embedded metadata where available;
4. fetches the selected Audiobookshelf library with GET requests;
5. scores every local item against the existing Audiobookshelf items;
6. retains the best candidates with a per-field evidence breakdown;
7. labels each local item `strong_candidate`, `ambiguous`, or `no_candidate`.

## Evidence model

Matching is deliberately evidence-based rather than a single fuzzy title comparison.

Current positive signals include:

- exact ASIN;
- exact normalized ISBN;
- title similarity;
- author similarity;
- narrator similarity;
- series and sequence agreement;
- duration agreement;
- matching trailing path components.

Current negative signals include:

- conflicting ASIN or ISBN values;
- clearly different titles/authors;
- conflicting series sequence;
- large duration differences.

Every contribution is emitted in the JSON report so a future review UI can explain why a candidate ranked where it did.

## Safety and ambiguity rules

A score alone never authorizes a write.

A candidate is only labeled `strong_candidate` when its score is high enough and it is sufficiently separated from the next-best candidate. The runner-up is considered even when `--candidate-limit 1` is used, so hiding candidates from output cannot make the decision less conservative.

If the same Audiobookshelf item becomes the strong candidate for more than one local filesystem item, all of those assignments are downgraded to `ambiguous` and receive a warning. This prevents duplicate/split folders from silently converging on the same server item.

`ambiguous` is also used for useful but incomplete evidence, such as a tagless folder whose title/path resembles an existing Audiobookshelf item.

## Intended next step

The match report becomes input to persistent proposal/review state. Provider searches should be used to identify items that do not already have a trustworthy Audiobookshelf identity, not to bypass the human-review boundary.
