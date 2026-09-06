[![HACS Passing](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/actions/workflows/validate.yml/badge.svg)](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/actions/workflows/validate.yml)
[![Total Downloads](https://img.shields.io/github/downloads/svalsemey/hassio-simonsvoss-mobilekey/total.svg)](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/releases)
[![Latest Release Downloads](https://img.shields.io/github/downloads/svalsemey/hassio-simonsvoss-mobilekey/latest/total.svg)](https://github.com/svalsemey/hassio-simonsvoss-mobilekey/releases/latest)

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
4. Choose how often Home Assistant refreshes the data (once a minute by
   default, adjustable later in the integration options).

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

States refresh automatically when you decide to. The **Refresh** button on the
system device forces an immediate update, for example right afterchanging
something in the MobileKey app or for active polling after a physical change
(waiting for locking / unlocking / door opening / door closing). **Do not
abuse from it!**

## Troubleshooting

- **Invalid authentication** — the email address or password is wrong. If you
  changed your password, Home Assistant will prompt you to re-authenticate.
- **Failed to connect** — Home Assistant could not reach the MobileKey cloud.
  Check your internet connection and try again.
- **A command feels slow** — commands travel through the cloud and then by
  radio to the lock; a few seconds of delay is normal.
- **Reporting an issue** — open an issue on GitHub and attach the diagnostics
  file (**Settings → Devices & services → SimonsVoss MobileKey → ⋮ → Download
  diagnostics**). Passwords and email addresses are automatically removed from
  this file.
