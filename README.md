# cite-verify

`cite-verify` extracts legal citations with eyecite and performs a deterministic,
first-pass case-citation check against CourtListener. It stores responses in a
local cache and can apply `LIBRARY`, `ALT`, or `PUBLIC` source tags from a JSON or
CSV sidecar.

Set `COURTLISTENER_API_TOKEN` at runtime to enable case lookup. The value is used
only in the request authorization header. Without it, citations are reported as
`Unverified` with reason `no token`.

```sh
cite-verify draft.md --format markdown --output report.md
cite-verify draft.md --sidecar sources.csv --format csv
```

The cache defaults to `.cache/cite-verify/`. Output is only a first pass and must
be verified by a human before use.

Future source adapters have explicit hooks for statutes, regulations, journals,
bar ethics opinions, and local resolution of `id.` and `supra` references.

