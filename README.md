# MeshCore Contact Pruner

Prune stale contacts from a [MeshCore](https://meshcore.io) companion device.

Filters contacts by configurable criteria — age, distance, type — and optionally
exports each deleted contact as a `meshcore://` URI so they can be re-imported
or shared as QR codes later.

## Quick Start

```bash
# install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# clone and run
git clone <this-repo>
cd meshcore-contact-prune
uv run meshcore-contact-prune --max-age-days 30
```

## Usage

```
meshcore-contact-prune [OPTIONS]
```

### Connection

| Flag | Description |
|---|---|
| `-d`, `--device ADDR` | BLE device address or name (auto-discovers if omitted) |
| `-s`, `--serial PORT` | Use serial port instead of BLE |
| `-b`, `--baudrate N` | Serial baud rate (default: 115200) |
| `--debug` | Enable debug logging |

### Filters

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
| `--dry-run` | Show what would be deleted without touching anything (default: on) |
| `--no-dry-run` | Actually delete matched contacts |
| `-y`, `--yes` | Skip the confirmation prompt |
| `--no-backup` | Skip exporting before delete (faster, no recovery) |
| `--backup PATH` | Custom backup file path (default: `meshcore_pruned_<ts>.json`) |

## Examples

```bash
# See what would be removed (dry-run, safe)
uv run meshcore-contact-prune --max-age-days 60 --max-distance-km 500

# Only prune repeaters, keep CLI contacts and favourites
uv run meshcore-contact-prune --max-age-days 30 --keep-types CLI --whitelist "MyBuddy,OtherFriend"

# Actually delete — fast mode
uv run meshcore-contact-prune --max-age-days 90 --no-dry-run -y --no-backup

# Delete with full backup for recovery
uv run meshcore-contact-prune --max-age-days 30 --no-dry-run -y --backup my-prune.json
```

## Backup Format

Backup files are JSON with one entry per deleted contact. The `uri` field
contains a `meshcore://` link that can be re-imported into any MeshCore
client to restore the contact.

## Prerequisites

- **Linux**: pair your MeshCore device with `bluetoothctl` first:
  ```bash
  bluetoothctl scan on
  bluetoothctl pair XX:XX:XX:XX:XX:XX
  bluetoothctl trust XX:XX:XX:XX:XX:XX
  ```
- The MeshCore device must be running **companion firmware** (BLE or serial).
- Python 3.13+ (uv handles this for you).

## Development

```bash
uv sync
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pytest              # tests
```
