# cite-verify

`cite-verify` extracts legal citations with eyecite and rule-based parsers, then
performs deterministic, first-pass checks against open and official sources. It
supports cases, United States Code and federal regulations, Washington statutes
and regulations, journal articles, and bar ethics opinions. It stores responses
in a local cache and can apply `LIBRARY`, `ALT`, or `PUBLIC` source tags from a
JSON or CSV sidecar.

Set `COURTLISTENER_API_TOKEN` at runtime to enable case lookup. The value is used
only in the request authorization header. Without it, citations are reported as
`Unverified` with reason `no token`.

Set `GOVINFO_API_KEY` at runtime for United States Code and CFR checks through
govinfo. Without it, govinfo is skipped with an explicit reason; current CFR
sections can still be checked through the key-free eCFR API. Key registration and
API behavior are documented at <https://api.govinfo.gov/docs/>. Journal lookups
use Crossref and then OpenAlex. `CONTACT_EMAIL`, when set, supplies their polite
pool contact parameter; `OPENALEX_API_KEY` is optional. These values are read at
runtime and are never put in reports or the cache.

```sh
cite-verify draft.md --format markdown --output report.md
cite-verify draft.md --sidecar sources.csv --format csv
cite-verify draft.md --ethics-sources ethics-sources.json
```

Bar ethics sources are deliberately user supplied; no issuer list is bundled.
The JSON file is a list (or an object with a `sources` list) containing
`issuer`, a Python regular-expression `citation_pattern` with a named `number`
group, and either `url_template` (where `{number}` is substituted) or
`index_url`. A synthetic example is:

```json
[
  {
    "issuer": "EXB",
    "citation_pattern": "EXB Opinion (?P<number>\\d+)",
    "url_template": "https://example.com/opinions/{number}"
  }
]
```

All adapters try normalized exact matching first. When titles differ, bounded
fuzzy matching uses `difflib.SequenceMatcher` and accepts a candidate only at a
similarity of 0.88 or higher; journal fuzzy matches must also have the same year.
An authoritative match with a differing draft form is labeled `Corrected` and
reports the authoritative form. Every result includes its label, matched field,
source URL, reason, and source tag. Requests are cached by source and normalized
citation. Case lookup is batched to the provider limits; other APIs expose
single-citation endpoints and cached citations are never requested again.

The cache defaults to `.cache/cite-verify/`. Output is only a first pass and must
be verified by a human before use.
