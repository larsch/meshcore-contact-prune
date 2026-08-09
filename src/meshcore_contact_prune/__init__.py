"""
MeshCore Contact Pruner
========================

Prune stale contacts from a MeshCore companion device using configurable
filters: max age, max distance, contact type, and whitelists.  Exports
deleted contacts as ``meshcore://`` URIs for later recovery or QR sharing.
"""

import argparse
import asyncio
import json
import logging
import math
import os
import time
from contextlib import suppress
from datetime import UTC, datetime

from meshcore import EventType, MeshCore
from rich import print
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

# ── logging ────────────────────────────────────────────────────────────────
log = logging.getLogger("meshcore_contact_prune")


# ── haversine distance (km) ────────────────────────────────────────────────
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon pairs (degrees)."""
    if lat1 == 0.0 and lon1 == 0.0:
        return float("inf")
    if lat2 == 0.0 and lon2 == 0.0:
        return float("inf")
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── contact type helpers ───────────────────────────────────────────────────
CONTACT_TYPE_NAMES = {0: "NONE", 1: "CLI", 2: "REP", 3: "ROOM", 4: "SENS"}
CONTACT_TYPE_LOOKUP = {v: k for k, v in CONTACT_TYPE_NAMES.items()}


def contact_type_name(type_id: int) -> str:
    return CONTACT_TYPE_NAMES.get(type_id, f"UNK({type_id})")


# ── serialisation ──────────────────────────────────────────────────────────
def contact_to_dict(c: dict) -> dict:
    """JSON-serialisable copy of a contact dict."""
    out: dict[str, str | int | float | bool | None] = {}
    for k, v in c.items():
        if isinstance(v, bytes):
            out[k] = v.hex()
        elif isinstance(v, (int, float, str, bool, type(None))):
            out[k] = v
        else:
            out[k] = str(v)
    return out


# ── robust contact fetcher ─────────────────────────────────────────────────
async def _fetch_contacts_robust(mc: MeshCore, timeout: float = 30) -> dict | None:
    """Fetch contacts, handling BLE disconnects mid-transfer.

    The library's ``get_contacts()`` waits for ``CONTACTS_END`` which may
    never arrive if the BLE link drops during a large transfer.  Instead
    we collect ``NEXT_CONTACT`` events directly and return whatever was
    received.
    """
    contacts: dict = {}
    done_event = asyncio.Event()

    def _on_next_contact(event):
        c = event.payload
        contacts[c["public_key"]] = c

    def _on_contacts(event):
        contacts.update(event.payload)
        done_event.set()

    def _on_disconnected(event):
        done_event.set()

    sub_next = mc.subscribe(EventType.NEXT_CONTACT, _on_next_contact)
    sub_contacts = mc.subscribe(EventType.CONTACTS, _on_contacts)
    sub_disc = mc.subscribe(EventType.DISCONNECTED, _on_disconnected)

    try:
        await mc.commands.get_contacts_async()
        with suppress(TimeoutError):
            await asyncio.wait_for(done_event.wait(), timeout=timeout)

        if mc.contacts and not contacts:
            contacts = dict(mc.contacts)

        return contacts or (dict(mc.contacts) if mc.contacts else None)
    finally:
        sub_next.unsubscribe()
        sub_contacts.unsubscribe()
        sub_disc.unsubscribe()


# ── CLI entry point ────────────────────────────────────────────────────────
def main():
    """Top-level entry point (argv → asyncio)."""
    asyncio.run(_async_main())


async def _async_main():
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        handlers=[RichHandler(show_time=False, markup=True)],
    )

    console = Console()

    # ── filters ────────────────────────────────────────────────────────
    keep_type_ids = _parse_keep_types(args.keep_types)
    whitelist_names = _parse_whitelist(args.whitelist)

    if args.backup is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        args.backup = f"meshcore_pruned_{ts}.json"

    # ── connect ────────────────────────────────────────────────────────
    console.print("[bold]Connecting to MeshCore device...[/]")
    mc = await _connect(args)
    if mc is None:
        console.print("[red]ERROR:[/] Failed to connect.", style="red")
        raise SystemExit(1)

    try:
        # ── own position ───────────────────────────────────────────────
        my_lat = mc.self_info.get("adv_lat", 0.0)
        my_lon = mc.self_info.get("adv_lon", 0.0)
        my_name = mc.self_info.get("name", "unknown")
        console.print(f"  Device: [cyan]{my_name}[/]")
        if my_lat != 0.0 or my_lon != 0.0:
            console.print(f"  Position: {my_lat:.6f}, {my_lon:.6f}")

        await asyncio.sleep(0.5)

        # ── fetch contacts ─────────────────────────────────────────────
        console.print("[bold]Fetching contacts...[/]")
        contacts = await _fetch_contacts_robust(mc, timeout=30)
        if contacts is None:
            console.print("[red]ERROR:[/] Failed to fetch contacts.")
            raise SystemExit(1)
        if not contacts:
            console.print("[yellow]No contacts found — nothing to prune.[/]")
            return

        console.print(f"  Found [bold]{len(contacts)}[/] contacts.\n")

        # ── evaluate ───────────────────────────────────────────────────
        now = int(time.time())
        candidates: list[tuple[str, dict]] = []
        kept: list[tuple[str, dict]] = []

        for _pubkey, c in contacts.items():
            name = c.get("adv_name", "?")
            kind = contact_type_name(c.get("type", 0))
            flags = c.get("flags", 0)
            is_fav = (flags & 0x01) != 0
            age_days = (now - c.get("last_advert", 0)) / 86400.0 if c.get("last_advert") else float("inf")
            dist_km = haversine_km(my_lat, my_lon, c.get("adv_lat", 0.0), c.get("adv_lon", 0.0))

            # --- keep rules ---
            if whitelist_names and name.lower() in whitelist_names:
                kept.append(("whitelisted", c))
                continue
            if args.keep_favourites and is_fav:
                kept.append(("favourite", c))
                continue
            if keep_type_ids is not None and c.get("type", 0) in keep_type_ids:
                kept.append((f"type {kind} in keep list", c))
                continue

            # --- reject rules ---
            reasons: list[str] = []
            if args.max_age_days is not None and age_days > args.max_age_days:
                reasons.append(f"age {age_days:.1f}d > {args.max_age_days}d")
            if args.max_distance_km is not None and dist_km != float("inf") and dist_km > args.max_distance_km:
                reasons.append(f"dist {dist_km:.0f}km > {args.max_distance_km}km")

            if reasons:
                candidates.append(("; ".join(reasons), c))
            else:
                kept.append(("within limits", c))

        # ── print tables ───────────────────────────────────────────────
        _print_contact_table(console, "KEEP", kept, style="green")
        _print_contact_table(console, "REMOVE", candidates, style="red")

        if not candidates:
            console.print("\n[yellow]Nothing to remove.[/]")
            return

        console.print(f"\n[bold red]{len(candidates)}[/] contact(s) matched for removal.")

        # ── export (unless --no-backup) ────────────────────────────────
        backup_entries, export_failures = await _export_candidates(console, mc, candidates, args)

        backup: dict | None = None
        if not args.no_backup:
            backup = _write_backup(args.backup, my_name, my_lat, my_lon, args.dry_run, backup_entries, export_failures, console)

        # ── delete ─────────────────────────────────────────────────────
        if args.dry_run:
            console.print("\n[yellow]DRY RUN[/] — no contacts deleted. Use [bold]--no-dry-run[/] to actually delete.")
            return

        if not args.no_backup and export_failures > 0:
            console.print("\n[red]Export failures detected. Aborting deletion.[/] Use [bold]--no-backup[/] to skip export.")
            return

        if not args.yes:
            try:
                resp = input("\nDelete these contacts? [y/N] ")
            except EOFError:
                resp = "n"
            if resp.lower() not in ("y", "yes"):
                console.print("[yellow]Aborted.[/]")
                return

        removed, failed = await _delete_candidates(console, mc, candidates)
        _finalise_backup(args.backup, backup, removed, failed, console)

    finally:
        await mc.disconnect()


# ── internal helpers ───────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Prune stale MeshCore contacts", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--max-age-days", type=float, default=None, help="Remove contacts older than N days")
    p.add_argument("--max-distance-km", type=float, default=None, help="Remove contacts farther than N km")
    p.add_argument("--keep-types", type=str, default=None, help="Contact types to KEEP (comma-sep: CLI,REP,ROOM,SENS)")
    p.add_argument("--keep-favourites", action="store_true", default=True, help="Never remove favourited contacts")
    p.add_argument("--no-keep-favourites", action="store_false", dest="keep_favourites", default=argparse.SUPPRESS, help="Allow removing favourites")
    p.add_argument("--whitelist", type=str, default=None, help="Contact names to always keep (comma-sep)")
    p.add_argument("--dry-run", action="store_true", default=True, help="Show plan, don't delete")
    p.add_argument("--no-dry-run", action="store_false", dest="dry_run", default=argparse.SUPPRESS, help="Actually delete contacts")
    p.add_argument("-y", "--yes", action="store_true", default=False, help="Skip confirmation prompt")
    p.add_argument("--no-backup", action="store_true", default=False, help="Skip exporting before delete (faster)")
    p.add_argument("--backup", type=str, default=None, help="Backup file path (default: meshcore_pruned_<ts>.json)")
    p.add_argument("-d", "--device", type=str, default=None, help="BLE device address or name (auto-discovers if omitted)")
    p.add_argument("-s", "--serial", type=str, default=None, help="Serial port path")
    p.add_argument("-b", "--baudrate", type=int, default=115200, help="Serial baud rate")
    p.add_argument("--debug", action="store_true", default=False, help="Enable debug logging")
    return p


def _parse_keep_types(raw: str | None) -> set[int] | None:
    if not raw:
        return None
    ids: set[int] = set()
    for t in raw.upper().split(","):
        t = t.strip()
        if t in CONTACT_TYPE_LOOKUP:
            ids.add(CONTACT_TYPE_LOOKUP[t])
        else:
            print(f"[red]Unknown contact type:[/] {t}  (known: {', '.join(CONTACT_TYPE_LOOKUP)})")
            raise SystemExit(1)
    return ids


def _parse_whitelist(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {n.strip().lower() for n in raw.split(",")}


async def _connect(args) -> MeshCore | None:
    if args.serial:
        return await MeshCore.create_serial(port=args.serial, baudrate=args.baudrate, only_error=not args.debug)
    return await MeshCore.create_ble(address=args.device, only_error=not args.debug)


def _print_contact_table(console: Console, heading: str, rows: list[tuple[str, dict]], style: str = ""):
    table = Table(title=f"[bold {style}]{heading} ({len(rows)} contacts)[/]", title_justify="left")
    table.add_column("Type", width=5)
    table.add_column("Name", width=34)
    table.add_column("Reason", width=40)

    for reason, c in rows:
        kind = contact_type_name(c.get("type", 0))
        name = c.get("adv_name", "?")
        fav = " ★" if (c.get("flags", 0) & 0x01) else ""
        table.add_row(kind, f"{name}{fav}", reason)

    console.print(table)


async def _export_candidates(console: Console, mc: MeshCore, candidates: list, args) -> tuple[list, int]:
    entries: list = []
    failures = 0

    if args.no_backup:
        console.print("\n[dim]Skipping backup (--no-backup).[/]")
        return entries, failures

    console.print("\n[bold]Exporting contacts for backup...[/]")
    for i, (reason, c) in enumerate(candidates, 1):
        name = c.get("adv_name", "?")
        pubkey = c["public_key"]
        kind = contact_type_name(c.get("type", 0))

        if i % 20 == 0:
            console.print(f"  ... {i}/{len(candidates)} ({failures} failed)")

        result = await mc.commands.export_contact(pubkey)
        if result.type == EventType.ERROR:
            console.print(f"  [red]✗[/] export failed: {kind} {name} — {result.payload}")
            failures += 1
            uri = None
        else:
            uri = result.payload.get("uri", None)

        entries.append({"exported_at": datetime.now(UTC).isoformat(), "reason": reason, "uri": uri, "contact": contact_to_dict(c)})

    return entries, failures


def _write_backup(path: str, device_name: str, lat: float, lon: float, dry_run: bool, entries: list, failures: int, console: Console) -> dict:
    backup = {
        "exported_at": datetime.now(UTC).isoformat(),
        "device_name": device_name,
        "device_lat": lat,
        "device_lon": lon,
        "dry_run": dry_run,
        "removed_count": len(entries) if not dry_run else 0,
        "entries": entries,
    }
    with open(path, "w") as f:
        json.dump(backup, f, indent=2, ensure_ascii=False)
    console.print(f"\nBackup saved to: [bold]{os.path.abspath(path)}[/]")
    if failures:
        console.print(f"[yellow]Warning:[/] {failures} export(s) failed — not in backup!")
    return backup


async def _delete_candidates(console: Console, mc: MeshCore, candidates: list) -> tuple[int, int]:
    removed = 0
    failed = 0
    for _reason, c in candidates:
        name = c.get("adv_name", "?")
        pubkey = c["public_key"]
        kind = contact_type_name(c.get("type", 0))
        result = await mc.commands.remove_contact(pubkey)
        if result.type == EventType.ERROR:
            console.print(f"  [red]FAILED[/] {kind} {name} — {result.payload}")
            failed += 1
        else:
            removed += 1
    return removed, failed


def _finalise_backup(path: str, backup: dict | None, removed: int, failed: int, console: Console):
    if backup is not None:
        backup["removed_count"] = removed
        backup["failed_count"] = failed
        with open(path, "w") as f:
            json.dump(backup, f, indent=2, ensure_ascii=False)
        console.print(f"\n[bold]Done:[/] {removed} removed, {failed} failed.  Backup: [bold]{os.path.abspath(path)}[/]")
    else:
        console.print(f"\n[bold]Done:[/] {removed} removed, {failed} failed.")
