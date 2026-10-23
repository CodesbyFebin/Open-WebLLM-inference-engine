# Security policy

## Reporting a vulnerability

Please report suspected security vulnerabilities privately to the repository owner through GitHub's **Report a vulnerability** feature, if it is enabled for this repository. Include affected files or endpoints, impact, and reproducible steps. Do not disclose credentials or personal data. If private reporting is unavailable, contact the repository owner directly before publishing details.

## Scope and verification

The CI security and PostgreSQL checks are automated fixtures, not an independent security assessment. See [`docs/PRODUCTION-GATES.md`](docs/PRODUCTION-GATES.md) for tested controls and outstanding deployment and device gates. Do not send sensitive production data to this project for testing.
