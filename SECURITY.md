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
- Diagnostics downloads redact credentials, guest e-mail addresses and PIN
  codes, including inside the raw cloud payloads. Review any file before
  sharing it anyway.
- Never share live account credentials in issues or diagnostics.
