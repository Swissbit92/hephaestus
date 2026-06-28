# {{REPO_NAME}}

{{ONE_LINE_PURPOSE}}

## Contents

- [Status](#status)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Status

Active — see [CHANGELOG.md](CHANGELOG.md) for the latest release.

## Quickstart

```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Run
python3 -m {{REPO_NAME}} --help
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

<!-- Tip: a Mermaid diagram here renders on GitHub and is AI-parseable — add one if a picture
     of the flow/components helps. Example:
     ```mermaid
     flowchart LR
       A[input] --> B[process] --> C[output]
     ``` -->

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md). Strategic direction lives in the [ecosystem VISION](../VISION.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) if present. Development workflow: `/develop` (auto-detects
this repo); documentation changes go through `/cms`. Keep the default branch releasable and tests
green before integrating.

## License

See [LICENSE](LICENSE) if present.
