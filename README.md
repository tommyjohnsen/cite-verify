# cite-verify

`cite-verify` extracts legal citations from Markdown or plain text and performs
a deterministic first-pass check against official and open sources. Matching is
rule based: normalized exact matching runs first, followed where appropriate by
bounded fuzzy title matching at a documented 0.88 threshold. No model calls are
made, and no model makes a pass/fail decision.

The tool supports cases, federal statutes and regulations, Washington statutes
and regulations, journal articles, and bar ethics opinions. Reports are CSV or
Markdown and contain the cite, location, label, source tag, matched field, source
URL, reason, and normalized form. All output needs human verification before
use.

## Install

Python 3.11 or newer is required.

```sh
pip install .
```

## Usage

```sh
cite-verify draft.md --format markdown --output report.md
cite-verify draft.md --sidecar sources.csv --format csv --output report.csv
cite-verify draft.md --ethics-sources ethics-sources.json
cite-verify lint draft.md
```

Without `--output`, the report is written to standard output. A JSON or CSV
sidecar can map normalized citations to `LIBRARY`, `ALT`, or `PUBLIC`; matches
against free official or open sources default to `PUBLIC`. The `lint` command
flags possible style issues without rewriting the input.

Exit code 0 means the command completed. Exit code 2 means command-line usage
was invalid. File, configuration, or other unexpected runtime failures exit
nonzero (normally 1).

For a short synthetic example, save this as `draft.md`:

```text
Alpha v. Beta, 123 F.3d 456 (9th Cir. 2001).
```

Then run `cite-verify draft.md --format markdown`. With no CourtListener token,
the row is labeled `Unverified` and its reason is `no token`; no network request
is attempted.

`Id.` and `supra` references are resolved locally against earlier citations and
footnotes in the same draft. They do not cause network calls. Bar ethics opinions
are checked only through a user-supplied sources file; the project bundles no
issuer list. That JSON file supplies an issuer, a citation pattern with a named
`number` group, and an official URL template or index URL.

## Configuration and sources

- CourtListener case lookup uses `COURTLISTENER_API_TOKEN`. The token is read at
  runtime, sent only in the authorization header, and never included in output
  or cache entries.
- govinfo statute and regulation lookup uses `GOVINFO_API_KEY`. Registration and
  API documentation are at <https://api.govinfo.gov/docs/>. If the variable is
  absent, govinfo is skipped and the report explains why.
- Crossref and OpenAlex use `CONTACT_EMAIL` for their contact parameter when it
  is set. It is read at runtime and is not written to reports or the cache.
- OpenAlex optionally uses `OPENALEX_API_KEY`, read only at runtime.
- The eCFR API and official Washington legislature pages require no configured
  credential.

## Limits

- CourtListener permits 125 requests per day and 5 requests per minute, with at
  most 250 citations or 64,000 characters in one request. The client batches a
  draft into as few requests as possible, waits at least 12 seconds between
  requests, honors `Retry-After`, and stops when its daily budget is exhausted.
- The persistent cache defaults to `.cache/cite-verify/`, is keyed by source and
  normalized citation, and is consulted before a network call. Cached source
  responses can become stale; remove the relevant local cache entry when a fresh
  check is required.
- Exact and bounded fuzzy matching can confirm source metadata but cannot judge
  whether an authority supports a proposition, remains current, or is suitable
  for a particular use. Ambiguous, unavailable, and unresolvable citations stay
  `Unverified`.

External services can impose their own availability and use terms. CourtListener
requests must stay within the limits above. govinfo requires its issued API key;
eCFR and the Washington legislature expose public official material without a
configured key. Crossref accepts an optional contact email, and OpenAlex accepts
an optional key and contact email. Users are responsible for the current service
terms and for any rights or restrictions attached to fetched records. The cache
stores fetched response data locally, so its retention and redistribution should
follow those same terms.

## Dependencies and licenses

- `eyecite` is a BSD-2-Clause runtime dependency used to extract citations. Its
  permissive license is compatible with distribution under Apache-2.0.
- `reporters-db` and `courts-db` are BSD-2-Clause transitive runtime dependencies
  providing reporter and court data. Their permissive terms are compatible with
  Apache-2.0.
- `lxml` and `pyahocorasick` are BSD-3-Clause transitive runtime dependencies used
  by eyecite. Their notice-preserving permissive terms are compatible with
  Apache-2.0.
- `regex` is an Apache-2.0 transitive runtime dependency used by eyecite, so its
  license is directly compatible.
- `pytest` is an MIT-licensed development and test dependency. Its permissive
  terms are compatible with Apache-2.0.
- `setuptools` is the MIT-licensed build dependency. Its permissive terms are
  compatible with Apache-2.0.

HTTP and HTML handling otherwise use the Python standard library, which is not a
separately bundled project dependency. This project itself is licensed under
Apache-2.0; see `LICENSE` and `NOTICE`.
