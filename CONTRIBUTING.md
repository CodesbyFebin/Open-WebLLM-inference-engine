# Contributing

Thanks for helping improve Open WebGPU Inference Engine. Contributions should describe what is implemented and include reproducible evidence for claims about a specific runtime or deployment.

## Before opening an issue or pull request

- Search existing issues and pull requests first.
- For a feature, describe the use case, affected runtime, and the behavior expected when a backend or device is unavailable.
- For a bug, include minimal reproduction steps, environment details, and relevant sanitized logs. Never include API keys, passwords, prompts containing private information, or production data.
- Do not claim a runtime is supported based only on a mock, configuration file, or CI fixture. Update the README support matrix and `docs/PRODUCTION-GATES.md` with real evidence when adding runtime support.

## Development setup

Requirements: Node.js 22+, npm, Python 3.12+, and pip. Docker Compose v2 and PostgreSQL are needed for container/database integration checks; physical WebGPU or NVIDIA hardware is only needed to validate those actual runtimes.

```bash
cd web
npm install
npm test
npm run build

cd ../api
pip install -r requirements.txt
python -m pytest -q
```

The API tests use local fixtures for provider calls; they do not need API credentials or a live model provider. Full CI also starts disposable PostgreSQL and API/worker containers. See `.github/workflows/ci.yml` and `docs/PRODUCTION-GATES.md` for the exact checks and their scope.

## Pull request expectations

- Keep changes focused and document behavior, limits, and any required configuration.
- Add or update meaningful tests for changed behavior. Avoid tests that require paid services or secrets in normal CI.
- Run the relevant commands above and include their results in the pull request description.
- Update documentation and the evidence register if a capability, security boundary, or verification status changes.
- Never add arbitrary shell execution, credential capture, hidden network calls, or unbounded model/provider usage.
- Keep dependencies and GitHub Actions scoped to the minimum permissions required.

## Security reports

Do not publish exploitable vulnerabilities in a public issue. Follow [SECURITY.md](SECURITY.md) for private reporting instructions.

## License

This repository is licensed under the MIT License. By submitting a contribution, you agree it may be distributed under that license. Please do not submit code copied from third-party projects or work you are not authorized to contribute; include attribution and license details when adding third-party material.
