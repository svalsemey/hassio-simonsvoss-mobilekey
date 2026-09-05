# SimonsVoss MobileKey for Home Assistant

Integrate your **SimonsVoss MobileKey** locking system into Home Assistant to monitor devices and trigger lock-related actions from your dashboard and automations.

This integration connects to the MobileKey cloud and keeps your system state updated automatically.

---

## What this integration provides

Once configured, Home Assistant will automatically discover and create entities for:

- **Locks**
- **SmartBridges**
- **Identification media** (keys/transponders)

### Main capabilities

- Monitor lock and bridge **connectivity**
- Check lock-related states such as:
  - door status (if available from your hardware)
  - lock state
  - battery critical state
- View diagnostics like **signal quality**
- Trigger lock actions from Home Assistant:
  - **Open**
  - **Read access list** (audit trail request)

---

## Installation

Install as a custom integration (for example via HACS or manual copy into `custom_components`), then restart Home Assistant.

Repository/documentation:
- <https://github.com/svalsemey/hassio-simonsvoss-mobilekey>

---

## Configuration

No YAML setup is required.

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **SimonsVoss MobileKey**
3. Enter your MobileKey account:
   - **Username** (email)
   - **Password**

If credentials expire or change, Home Assistant will prompt for **re-authentication**.

---

## Entities created

## Binary sensors

For locks (depending on available components):

- **Lock** (lock state as binary sensor)
- **Door**
- **Battery**
- **Connectivity**

For SmartBridges:

- **Connectivity**

## Sensors

- **Signal quality** (`none`, `weak`, `good`, `excellent`)
- **MobileKey ID** (SmartBridge)
- **ID** (ident medium)
- **Name** (ident medium)

## Buttons

- **Open**
- **Read access list**

---

## Usage notes

- Updates are cloud-polled (roughly every minute).
- Commands are sent to the cloud first, then relayed to the lock by the SmartBridge.
- Some actions may take a short time to be reflected in entity states.
- Entities are dynamically managed: devices removed from MobileKey are cleaned up automatically in Home Assistant.

---

## Troubleshooting

Common issues and meaning:

- **Failed to connect**
  Home Assistant cannot reach the MobileKey cloud service.
- **Invalid authentication**
  Username/password is incorrect or no longer valid.
- **Unexpected error**
  Temporary/unknown issue during setup.

If needed:

1. Verify cloud connectivity from your Home Assistant host
2. Re-check account credentials
3. Try re-authentication from the integration page
4. Check Home Assistant logs for `simonsvoss_mobilekey`

---

## Good to know

- This is a **cloud polling** integration, so internet access is required.
- Device state depends on what MobileKey reports for your installation and hardware capabilities.
