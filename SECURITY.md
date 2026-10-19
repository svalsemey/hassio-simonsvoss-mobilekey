# Security policy

## Supported versions

Only the latest release of the integration receives security fixes.

| Version        | Supported |
| -------------- | --------- |
| Latest release | ✅        |
| Older releases | ❌        |

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub
private vulnerability reporting instead:
<https://github.com/svalsemey/hassio-simonsvoss-mobilekey/security/advisories/new>

Include as much detail as possible: affected version, reproduction steps and
impact. Reports are acknowledged within a few days; please allow a reasonable
delay for a fix before any public disclosure.

## Scope and hardening notes

- The integration talks exclusively to the SimonsVoss MobileKey cloud over
  HTTPS; it exposes no local network service.
- The MobileKey account credentials are stored by Home Assistant in its
  config entry storage; protect the Home Assistant instance accordingly.
- Diagnostics downloads redact credentials, guest e-mail addresses, PIN codes
  and the names of Key4Friends guest keys and ident media (key holders),
  including inside the raw cloud payloads. Hardware identifiers (SmartBridge
  serial numbers, chip IDs and PHI numbers) are replaced by placeholders that
  are only consistent within one file. Lock and SmartBridge names are kept.
  Home Assistant names device diagnostics files after the device: rename the
  file of a guest key or of an ident medium before sharing it. Review any
  file before sharing it anyway.
- Never share live account credentials in issues or diagnostics.
