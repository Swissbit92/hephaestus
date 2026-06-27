# Security Policy

How to report a vulnerability in {{REPO_NAME}}, and what to expect in return.

## Supported versions

| Version | Supported |
|---------|-----------|
| latest  | ✅ |
| older   | ⚠️ best-effort / TBD |

## Reporting a vulnerability

**Do not open a public issue for security problems.** Report privately:

- Preferred: GitHub **Private Vulnerability Reporting** (repo → Security → Report a
  vulnerability), or
- Email: TBD (add a security contact; PGP key optional).

Include: affected version/commit, reproduction steps, impact, and any suggested fix.

## Response targets

| Stage | Target |
|-------|--------|
| Acknowledge report | within 48 hours |
| Initial triage / severity | within 5 business days |
| Fix or mitigation plan | by severity (Critical: days · High: ~2 weeks · Medium/Low: next release) |

## Disclosure

Coordinated disclosure. We aim to ship a fix and credit the reporter before public
disclosure; default embargo is 90 days from report unless agreed otherwise.

## Scope

- **In scope:** code in this repository.
- **Out of scope:** third-party dependencies (report upstream), social engineering,
  issues requiring privileged local access already.

## Data classification

Highest data classification this repository handles: **TBD**
(one of: Public · Internal · Confidential · Restricted).

This drives the encryption, access-control, and audit obligations for the system, and the
threat assessment in [docs/THREAT_LEVEL.md](docs/THREAT_LEVEL.md).
