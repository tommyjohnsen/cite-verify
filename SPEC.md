# cite-verify: spec

Python tool that extracts legal citations from a draft with eyecite and checks case citations against the CourtListener citation-lookup API, plus a bluebook-lint sub-feature.

## Core (module `cite_verify`, console script `cite-verify`)
- Input: a Markdown or plain-text draft (footnotes supported). eyecite (BSD-2-Clause) extracts full, short, id. and supra citations; rule-based parsers add statutes, regulations, journal articles and bar ethics opinions.
- Every result carries: label (**Verified**, **Corrected** or **Unverified**), source tag (**LIBRARY**, **ALT** or **PUBLIC**), matched field (what matched, e.g. reporter+volume+page, section number, DOI, title+year, opinion number), source URL, and the reason for the label.
- Matching is exact first, then bounded fuzzy matching (normalized strings, a documented similarity threshold). Corrected means the authoritative source matched but a field in the draft differs; report the authoritative form.

### Cases: CourtListener
- Citation-lookup endpoint `https://www.courtlistener.com/api/rest/v4/citation-lookup/`, token from env `COURTLISTENER_API_TOKEN` read at runtime only, sent as an `Authorization: Token ...` header, never printed or written. No token: skip and mark Unverified (reason "no token").
- 200 and same normalized form: Verified. 200 but different: Corrected. 404, 400, 300 ambiguous or not looked up: Unverified.
- Limits: 5 requests/min, 125 requests/day, up to 250 citations or 64,000 characters per request. Batch the whole draft into as few requests as possible (one when it fits), min 12 s between requests (injectable clock), back off on 429 using Retry-After, stop and report when the daily budget is used.

### Statutes and regulations
- US Code and CFR via govinfo (`https://api.govinfo.gov`). The govinfo API requires an api.data.gov key (documented at `https://api.govinfo.gov/docs/`): read it from env `GOVINFO_API_KEY`; without it skip govinfo and say so in the reason. README cites that doc URL.
- CFR current text also via the eCFR API (`https://www.ecfr.gov/api/versioner/v1/`, docs `https://www.ecfr.gov/developers/documentation/api/v1`, no key).
- Washington RCW and WAC via the official legislature pages (`https://app.leg.wa.gov/RCW/default.aspx?cite=...`, `https://app.leg.wa.gov/WAC/default.aspx?cite=...`): confirm the section exists and match the heading.

### Journals and articles
- Match by DOI, or by metadata (title, authors, year, journal, volume, first page) via Crossref (`https://api.crossref.org`, `mailto` from env `CONTACT_EMAIL`) and OpenAlex (`https://api.openalex.org`, optional key `OPENALEX_API_KEY`, email from `CONTACT_EMAIL`).

### Id. and supra
- Resolved locally against the draft's own earlier citations and footnotes, with no network call. Id. points to the immediately preceding authority; supra points to an earlier full cite by short name and footnote number. Unresolvable ones are Unverified with the reason.

### Bar ethics opinions
- Matched against official bar ethics opinion pages listed in a user-supplied sources file (JSON: issuer short name, citation pattern, official URL template or index page). Match opinion number, and title or date when present. The repo ships no real issuer list; tests and examples use a synthetic issuer on example.com. README uses only the generic phrase "bar ethics opinions".

### Cache, batching, tags
- Persistent local cache (default `.cache/cite-verify/`, git-ignored, never committed) keyed by source + normalized citation, reused before any call; batched requests everywhere a source allows it.
- Source tag from an optional sidecar file (CSV or JSON: citation -> LIBRARY | ALT | PUBLIC). Default: PUBLIC when matched against a free official or open source, ALT for a free alternative, LIBRARY otherwise.
- Reports: CSV and Markdown (cite, location, label, tag, matched field, source URL, reason, normalized form).

## bluebook-lint (sub-feature, `cite-verify lint`)
- Flags, never rewrites: nonstandard reporter abbreviations (use reporters-db data from eyecite's dependencies), missing pincites on short forms, id. used after an intervening different authority, supra used for cases, short form before any full cite.
- Rule descriptions are written in our own words, paraphrased from the Indigo Book. No Bluebook text and no quoted rule text. Each rule has an id and a one-line paraphrase.

## Dependencies
eyecite (BSD-2-Clause, pulls reporters-db and courts-db, BSD-2-Clause; lxml BSD-3-Clause; regex Apache-2.0; pyahocorasick BSD-3-Clause). HTTP via the stdlib only; HTML parsing via the stdlib `html.parser`.

## Rules for all parts
- Deterministic only: rule-based parsing and exact or fuzzy matching against authoritative sources. No LLM or model makes any pass/fail call, and nothing calls a model API at runtime. Output is a first pass that a human verifies.
- License Apache-2.0 (LICENSE and NOTICE are already here; keep them as they are). pyproject.toml: `license = "Apache-2.0"`, requires-python >=3.11.
- Tests use pytest and must pass with this exact command run from this directory (network is off; the uv cache is pre-warmed):
  `UV_OFFLINE=1 UV_CACHE_DIR=$UVC uv run --no-project --with pytest --with eyecite pytest -q`
  where $UVC is the pre-warmed cache path given in the job prompt. Put `[tool.pytest.ini_options]` with `pythonpath = ["src"]` and `testpaths = ["tests"]` in pyproject.toml. Use a src/ layout.
- All network access in tests is mocked (unittest.mock on the stdlib HTTP layer). No live calls in tests or CI.
- Synthetic fixtures only (synthetic citations and DOIs; no real drafts or notes). No hostnames other than the public API hosts named here, no IPs, local paths, usernames, real emails (use `you@example.com`; contact email only from env `CONTACT_EMAIL` or a config file, never hardcoded), account details, real data or secrets.
- Tokens and contact emails come only from environment variables read at runtime. Never print, log, cache or write their values.
- The README must state that all output needs human verification before use.
- Do not copy text from The Bluebook or any licensed or library source. Do not bundle CSL styles.
- Work only inside this directory. Do not read or copy anything from other directories.
