---
title: Lessons Learned
status: active
created: {{TODAY}}
last_reviewed_on: {{TODAY}}
review_in: 12 months
applies_to: {{REPO_NAME}}
---

# Lessons Learned

Append-only, dated entries. Newest first. Each entry: what happened, what we learned, how to apply going forward.

## {{TODAY}} — Repository initialized

- **What:** `/cms init` scaffolded the standard doc set.
- **Learned:** Creation-time enforcement is the strongest lever for doc hygiene (Nx, Kubernetes OWNERS, Backstage).
- **Apply:** Any new repo starts here. Retroactive audits drift; creation-time templates don't.
