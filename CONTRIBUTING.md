# Contributing

Thank you for considering a contribution to the SimonsVoss MobileKey
integration!

## Reporting bugs and requesting features

- Use the GitHub issue templates; they ask for everything needed to help
  quickly.
- For bugs, always attach the diagnostics file (Settings → Devices &
  services → SimonsVoss MobileKey → ⋮ → Download diagnostics, or from a
  device page). Secrets are redacted automatically, including inside the
  raw JSON payloads.
- Enable debug logging when relevant:

  ```yaml
  logger:
    default: info
    logs:
      custom_components.simonsvoss_mobilekey: debug
  ```

## Development environment

1. Fork and clone the repository.
2. Copy or symlink `custom_components/simonsvoss_mobilekey` into the
   `config/custom_components` folder of a Home Assistant development
   instance (the official devcontainer works well).
3. Restart Home Assistant and configure the integration through the UI.

## Coding standards

- Python 3.13+, fully typed, async end to end.
- Code must pass `ruff check .` and `ruff format --check .`; both run in CI.
- Follow the Home Assistant [integration quality scale]; the status of every
  rule is tracked in `custom_components/simonsvoss_mobilekey/quality_scale.yml`
  and must be kept up to date by pull requests.
- All code, comments and user-facing strings are written in English; new UI
  strings go through `strings.json` and the translation files.
- Never commit credentials, tokens or unredacted diagnostics.

## Pull requests

- Keep pull requests small and focused on a single change.
- Describe the motivation and the observed and expected behavior.
- Update `quality_scale.yml`, translations and documentation along with the
  code.
- CI (hassfest, HACS validation and Ruff) must pass before review.

[integration quality scale]: https://developers.home-assistant.io/docs/core/integration-quality-scale/
