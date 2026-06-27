---
title: Threat Level
status: active
created: {{TODAY}}
last_reviewed_on: {{TODAY}}
review_in: 6 months
applies_to: {{REPO_NAME}}
threat_level: Low
---

# Threat Level — {{REPO_NAME}}

A lightweight, living threat model. The `threat_level` frontmatter field above is the
machine-readable rating (Low · Medium · High · Critical, CVSS-aligned) — keep it current.

## Current assessment

| Field | Value |
|-------|-------|
| Threat level | Low (see frontmatter) |
| Owner | TBD |
| Last reviewed | {{TODAY}} |

## Trust boundaries

```
[ Untrusted input ] → [ {{REPO_NAME}} ] → [ Downstream / data store ]
                          ▲
                   trust boundary
```

Describe where untrusted data crosses into the system, and what is trusted vs. not.

## STRIDE

| Threat | Applies? | Control / mitigation | Status |
|--------|----------|----------------------|--------|
| **S**poofing | TBD | TBD | TBD |
| **T**ampering | TBD | TBD | TBD |
| **R**epudiation | TBD | TBD | TBD |
| **I**nformation disclosure | TBD | TBD | TBD |
| **D**enial of service | TBD | TBD | TBD |
| **E**levation of privilege | TBD | TBD | TBD |

## OWASP Top 10 checklist

- [ ] A01 Broken access control
- [ ] A02 Cryptographic failures
- [ ] A03 Injection
- [ ] A04 Insecure design
- [ ] A05 Security misconfiguration
- [ ] A06 Vulnerable / outdated components
- [ ] A07 Identification & authentication failures
- [ ] A08 Software & data integrity failures
- [ ] A09 Security logging & monitoring failures
- [ ] A10 Server-side request forgery (SSRF)

## Residual risks

Risks accepted for now, with rationale:
- TBD

## Escalation

If the threat level would rise to **Critical**: TBD — who is notified, freeze criteria,
remediation timeline, and where the post-incident note is recorded (e.g.
[LESSONS_LEARNED.md](LESSONS_LEARNED.md)).
