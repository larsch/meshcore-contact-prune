# MeshCore Contact Pruner

Prune stale contacts from a [MeshCore](https://meshcore.io) **Bluetooth
companion** device (the kind you pair with the MeshCore mobile app via BLE).
Also works over USB Serial if your companion firmware was built for that.

Filters contacts by configurable criteria — age, distance, type — and optionally
exports each deleted contact as a `meshcore://` URI so they can be re-imported
or shared as QR codes later.

## Prerequisites

### Bluetooth pairing (Linux)

Your MeshCore BLE companion device must be **paired and trusted** with the
host before this tool can connect.  Use `bluetoothctl`:

```bash
# 1. Start bluetoothctl and turn on the adapter
bluetoothctl power on

# 2. Scan for MeshCore devices (look for names starting with "MeshCore")
bluetoothctl scan on
# ... let it run until your device appears, note its MAC address ...

# 3. Stop scanning once you've found it
bluetoothctl scan off

# 4. Pair with the device
bluetoothctl pair F8:5B:1B:A6:0B:AD

# 5. Trust it so it reconnects without prompting next time
bluetoothctl trust F8:5B:1B:A6:0B:AD
```

After pairing, the device should show as **Paired: yes** and **Trusted: yes**:

```bash
$ bluetoothctl info F8:5B:1B:A6:0B:AD
Device F8:5B:1B:A6:0B:AD (public)
    Name: MeshCore-larsch🕹️
    Paired: yes
    Trusted: yes
```

> **Note:** If the device is already paired but won't connect, try unpairing
> and re-pairing: `bluetoothctl remove F8:5B:1B:A6:0B:AD`, then pair again.

### Companion firmware

The MeshCore device must be running **companion radio firmware** — the same
firmware you'd use with the MeshCore mobile app.  BLE mode is the default;
serial mode is available if you built the `companion_radio_usb` variant.

### Python / uv

[uv](https://docs.astral.sh/uv/) handles Python and dependencies automatically.
Install it once:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Quick Start

```bash
git clone <this-repo>
cd meshcore-contact-prune

# Dry-run (safe — shows what would be deleted)
uv run meshcore-contact-prune --max-age-days 30
```

## Usage

```
meshcore-contact-prune [OPTIONS]
```

### Connection

| Flag | Description |
|---|---|
| `-d`, `--device ADDR` | BLE device address or name substring (auto-discovers first MeshCore device if omitted) |
| `-s`, `--serial PORT` | Use USB serial instead of BLE (e.g. `/dev/ttyACM0`) |
| `-b`, `--baudrate N` | Serial baud rate (default: 115200) |
| `--debug` | Enable debug logging |

### Filters

At least one filter must be specified, otherwise nothing will be pruned.

| Flag | Description |
|---|---|
| `--max-age-days N` | Remove contacts with `last_advert` older than N days |
| `--max-distance-km N` | Remove contacts farther than N km from your position |
| `--keep-types TYPES` | Contact types to **keep** (comma-sep: `CLI,REP,ROOM,SENS`).  Unlisted types become candidates. |
| `--whitelist NAMES` | Contact names to always keep (comma-sep) |
| `--keep-favourites` | Never remove favourited contacts (default: on) |
| `--no-keep-favourites` | Allow removing favourited contacts |

### Safety

| Flag | Description |
|---|---|
| `--dry-run` | Show what would be deleted without touching anything (**default: on**) |
| `--no-dry-run` | Actually delete matched contacts |
| `-y`, `--yes` | Skip the confirmation prompt |
| `--no-backup` | Skip exporting before delete (faster, but no recovery possible) |
| `--backup PATH` | Custom backup file path (default: `meshcore_pruned_<timestamp>.json`) |

## Examples

```bash
# See what would be removed (dry-run, safe)
uv run meshcore-contact-prune --max-age-days 60 --max-distance-km 500

# Only prune repeaters, keep CLI contacts and favourites
uv run meshcore-contact-prune --max-age-days 30 --keep-types CLI --whitelist "MyBuddy,OtherFriend"

# Actually delete — fast mode (no backup export)
uv run meshcore-contact-prune --max-age-days 90 --no-dry-run -y --no-backup

# Delete with full backup for recovery
uv run meshcore-contact-prune --max-age-days 30 --no-dry-run -y --backup my-prune.json

# Connect to a specific BLE device by name
uv run meshcore-contact-prune --device MeshCore-larsch --max-age-days 30

# Use serial instead of BLE
uv run meshcore-contact-prune --serial /dev/ttyACM0 --max-age-days 30
```

## Troubleshooting

### "Failed to connect"

- Make sure the device is **paired and trusted** (see Prerequisites above).
- The device must be **powered on and in range**.
- If the device is already connected to another client (e.g. the mobile app
  or your OS Bluetooth settings), **disconnect it first** — MeshCore only
  accepts one BLE connection at a time.

### Contacts fetch fails / times out

- This can happen with very large contact lists (300+) — the BLE link may
  drop mid-transfer.  Run with `--debug` to see what's happening.
- Try again; the robust fetcher will collect whatever contacts arrived before
  the drop.

## Backup Format

Backup files are JSON with one entry per deleted contact.  The `uri` field
contains a `meshcore://` link that can be re-imported into any MeshCore
client to restore the contact.

## Development

```bash
uv sync
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pytest              # tests
```
