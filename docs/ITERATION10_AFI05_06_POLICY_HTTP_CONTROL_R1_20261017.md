# Iteration 10 AFI05/06 policy control API R1

- Repository: `ai-for-investor`, branch `dev`; base `44ad881b729bfd1fa489b73d522c82debecc744d` (AFI12 importer commit).
- Scope: authenticated risk-budget control API, router registration, exact subject/portfolio selection, fixed ServiceRead worker/session bindings and deployment grants, and the dedicated HTTP-to-RiskHost test. Paper, MIG03 and other mixed-file hunks are excluded.
- Evidence: the author-local focused test passed once; independent static review returned `GO_STATIC` for the exact nine-path candidate. No Root QA or formal AFI05/06 case acceptance is claimed in this record.
- The HTTP path covers persisted HUMAN maker/checker separation, checker approval, member confirmations, durable catalog/readback, and rejects ordinary USER/SERVICE identities. API projections keep `consumer_effective=false`; this slice does not claim account admission has consumed the generated policy. HTTP pre-approval publish denial is covered by the catalog state guard, not an HTTP assertion.
- Next: exercise this HTTP-created generation through the real account Risk admission path and verify the effective generation plus old-reservation/UNKNOWN preservation.
