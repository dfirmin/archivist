# Example: minimal

The smallest working target: a contract index, one concept type, one structure, and the
`author-verify` pipeline. No intake contract, so every document is in scope and is its own
concept; no reference data, gaps or scoring.

## Inbox and expected outcomes

| Document | Kind | Expected outcome |
|---|---|---|
| `travel-policy-2026.md` | clean | **new** Policy Summary under `knowledge/policies/` |

## Last tested

2026-10-05, engine `feat/transcript-extractor` (`--engine current`): matched. The title kept
the year ("Business Travel Policy (2026)"), since this example has no naming rule.
