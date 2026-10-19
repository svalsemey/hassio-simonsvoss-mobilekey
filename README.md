![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)
[![HACS Passing](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/actions/workflows/validate.yml/badge.svg)](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/actions/workflows/validate.yml)
[![Total Downloads](https://img.shields.io/github/downloads/svalsemey/hassio-simonsvoss-mobilekey/total.svg)](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/releases)
[![Latest Release Downloads](https://img.shields.io/github/downloads/svalsemey/hassio-simonsvoss-mobilekey/latest/total.svg)](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/releases/latest)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-orange?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/sebastien_valsemey)

# SimonsVoss MobileKey for Home Assistant

Bring your SimonsVoss MobileKey locking system into Home Assistant: keep an eye
on your doors, open your locks remotely and manage guest keys, straight from
your dashboards and automations.

> Community project — not affiliated with or endorsed by SimonsVoss
> Technologies GmbH.

## What you can do

- **See your whole system at a glance** — your locks, SmartBridges, keys and
  guest keys appear automatically in Home Assistant, with the names you gave
  them in MobileKey.
- **Watch your doors** — know whether a door is open or closed and whether it
  is locked (with compatible locks).
- **Open locks remotely** — from a dashboard button or an automation.
- **Manage guest keys (Key4Friends)** — invite a guest by email, adjust their
  access later, see when an invitation has expired and revoke it when it is no
  longer needed.
- **Stay ahead of problems** — battery warnings, connectivity and radio signal
  quality for every device.
- **Automate everything** — get notified when a door stays open, when a
  battery runs low or when a guest key expires.

Several MobileKey accounts can be added side by side, each with its own
credentials.

## What you need

- A SimonsVoss MobileKey account (email address and password)
- At least one SmartBridge, online and linked to your locks
- An internet connection for Home Assistant — MobileKey is a cloud service

## Installation

### With HACS

1. Add this repository to HACS as a custom repository.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=svalsemey&repository=hassio-simonsvoss-mobilekey&category=integration)

2. Install **SimonsVoss MobileKey**.
3. Restart Home Assistant.

### Manual

1. Copy the `simonsvoss_mobilekey` folder into the `custom_components` folder
   of your Home Assistant configuration.
2. Restart Home Assistant.

## Getting started

1. Go to **Settings → Devices & services**.
2. Select **Add integration** and search for **SimonsVoss MobileKey**.
3. Sign in with your MobileKey email address and password.

That's it. Your devices are created automatically, and anything you add,
rename or remove in MobileKey later is reflected in Home Assistant on its own.

## Everyday use

### Doors and locks

Depending on its capabilities, each lock offers door and lock states, an
**Open** button for remote opening, a **Read access list** button to fetch its
latest access history (viewable in the MobileKey app), plus battery,
connectivity and signal quality indicators.

### Guest keys (Key4Friends)

Guest keys let someone open selected locks with the free SimonsVoss
**Key4Friends** app on their phone.

- **Create a key** — open the integration options (**Settings → Devices &
  services → SimonsVoss MobileKey → Configure**) and choose **Create a
  Key4Friends key**: pick a name, the guest's email address and language, the
  validity period and the authorized locks. The guest receives the invitation
  by email.
- **Edit a key** — choose **Edit a Key4Friends key** in the same menu.
  Everything can be changed except the email address.
- **Revoke a key** — delete the key's device in Home Assistant. The key is
  removed from your MobileKey system and the guest is notified.
- **Expired** — each guest key exposes an *Expired* indicator. Expired keys
  are kept until you delete them, so this is a handy trigger for a cleanup
  reminder.

### Actions

Everything you can do with guest keys is also available as actions, for use
in automations, scripts and dashboards ([**Settings → Tools → Actions**](https://my.home-assistant.io/redirect/developer_services)):

| Action | What it does |
| --- | --- |
| `simonsvoss_mobilekey.key4friends_list` | Returns every guest key of an account (use `response_variable`). |
| `simonsvoss_mobilekey.key4friends_get` | Returns the details of one guest key. |
| `simonsvoss_mobilekey.key4friends_create` | Creates a guest key and emails the invitation. |
| `simonsvoss_mobilekey.key4friends_update` | Updates a guest key; omitted fields are left unchanged. |
| `simonsvoss_mobilekey.key4friends_delete` | Revokes a guest key; the guest is notified. |

Example — create a three-day key when a booking calendar event starts:

```yaml
actions:
  - action: simonsvoss_mobilekey.key4friends_create
    data:
      config_entry_id: YOUR_ENTRY_ID  # use the account picker in the UI
      name: "{{ trigger.calendar_event.summary }}"
      email: "{{ trigger.calendar_event.description }}"
      language: en
      valid_from: "{{ trigger.calendar_event.start }}"
      valid_to: "{{ trigger.calendar_event.end }}"
      locks:
        - YOUR_LOCK_DEVICE_ID
      # Optional: names shown to the guest instead of the system lock names.
      lock_names:
        YOUR_LOCK_DEVICE_ID: "Main entrance"
```

`lock_names` (available on `key4friends_create` and `key4friends_update`)
takes one entry per lock to rename: the device ID of the lock as the key, the
name shown to the guest as the value. Renamed locks must also be listed in
`locks`; locks without an entry keep their system name — or, when updating a
key, the name already shown to the guest. To find the device IDs, pick the
locks with the UI selectors, then switch the action editor to YAML mode.

### Refreshing

Home Assistant polls the MobileKey cloud at once a minute and refreshes every
state in a single request. The **Refresh** button on the system device forces
an immediate update, for example right after changing something in the
MobileKey app, or while waiting for a physical change to be reported (locking,
unlocking, a door opening or closing). **Use it sparingly** — every press is a
request to the MobileKey cloud.
Need a different cadence? Disable polling in the integration's System options
(⋮ menu on the account entry) and create an automation that calls the
homeassistant.update_entity action on any MobileKey entity at the pace you want.

## Integration options

Open **Settings → Devices & services → SimonsVoss MobileKey → Configure** and
choose **Configure the integration** to adjust:

- **User agent** — the HTTP `User-Agent` header sent to the cloud, mirroring
  the official mobile application. Only change it if the cloud stops
  accepting the default one.

The same menu also contains the Key4Friends guest key management described
above.

## Known limitations

- **PIN code keypads (SmartKeypad) are not supported.** When the cloud
  reports one, it is skipped with a single log warning and the rest of the
  installation keeps working. If you own one, please open an **Unsupported
  device** issue and attach the account diagnostics file so support can be
  added.
- MobileKey is a cloud service: there is no local connection to the
  SmartBridge, and state changes are only visible once the SmartBridge has
  reported them to the cloud.
- Commands (remote opening, access list readout) are acknowledged only after
  the SmartBridge has relayed them to the lock by radio, so they can take a
  few seconds.
- The access lists fetched with **Read access list** are viewable in the
  MobileKey app only; the cloud does not expose their content to third-party
  clients.
- Expired guest keys remain listed until you delete them, mirroring the
  MobileKey apps.

## Removing the integration

1. Go to **Settings → Devices & services → SimonsVoss MobileKey**.
2. Open the ⋮ menu of the account entry and select **Delete**.

All devices and entities of the account are removed from Home Assistant.
Nothing is changed in your MobileKey system: locks, keys and guest keys stay
exactly as they are, and the session opened by Home Assistant simply expires.

> **Note** — deleting a single **guest key device** (as opposed to the whole
> integration) revokes that Key4Friends key in MobileKey and notifies the
> guest. Deleting any other device only removes it from Home Assistant; it is
> recreated at the next refresh as long as MobileKey still reports it.

## Security and privacy

- Home Assistant communicates exclusively with the SimonsVoss MobileKey cloud
  over HTTPS; the integration opens no local network service.
- Your MobileKey credentials are stored by Home Assistant in its config entry
  storage; protect your instance accordingly.
- Diagnostics downloads automatically redact passwords, email addresses, PIN
  codes and the names of guest keys and key holders (ident media) — including
  inside the raw cloud payloads. Hardware identifiers (SmartBridge serial
  numbers, radio chip IDs and PHI numbers) are replaced by numbered
  placeholders (`**REDACTED-1**`, `**REDACTED-2**`…) that are consistent
  within one file, so a lock can still be matched to its SmartBridge. Lock
  and SmartBridge names are kept, as they are needed for troubleshooting.
- To report a vulnerability, please follow the [security policy](SECURITY.md)
  instead of opening a public issue.

## Troubleshooting

- **Invalid authentication** — the email address or password is wrong. If you
  changed your password, Home Assistant prompts you to re-authenticate.
- **Failed to connect** — Home Assistant could not reach the MobileKey cloud.
  Check your internet connection and try again.
- **"Skipping unsupported …" warning in the logs** — your system contains a
  device type the integration does not model, such as a PIN code keypad.
  Everything else keeps working; please open an **Unsupported device** issue
  and attach the account diagnostics file so the device can be supported.
- **Every request suddenly fails** — the MobileKey cloud occasionally stops
  accepting outdated client versions. Update the integration or, as a
  stopgap, set a newer **User agent** in the integration options.
- **A command feels slow** — commands travel through the cloud and then by
  radio to the lock; a few seconds of delay is normal.
- **Reporting an issue** — download the diagnostics and attach the file to
  your GitHub issue: either for the whole account (**Settings → Devices &
  services → SimonsVoss MobileKey → ⋮ → Download diagnostics**) or for a
  single device, from its device page. Both include the raw JSON returned by
  the cloud; passwords, email addresses, PIN codes, the names of guest keys
  and key holders and hardware identifiers are automatically redacted,
  including inside the raw payloads. Home Assistant names a device
  diagnostics file after the device, so the file of a guest key or of a key
  holder carries their name: rename it before attaching it to a public
  issue. Review the file before attaching it anyway.

To capture debug logs, add the following to your configuration and reproduce
the problem:

```yaml
logger:
  default: info
  logs:
    custom_components.simonsvoss_mobilekey: debug
```

Alternatively, select **⋮ → Enable debug logging** on the integration page
(**Settings → Devices & services → SimonsVoss MobileKey**), reproduce the
problem, then select **Disable debug logging**: the captured log is
downloaded automatically.

## Contributing

Bug reports, feature requests and reports of unsupported devices are welcome
on the [issue tracker](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/issues);
please use the matching issue form and attach a diagnostics file whenever
possible. Security vulnerabilities must be reported privately, as described
in the [security policy](SECURITY.md). Development guidelines are described
in [CONTRIBUTING.md](CONTRIBUTING.md).
