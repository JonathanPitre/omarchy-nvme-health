#!/usr/bin/env python3
"""Emit disk SMART health JSON for the Omarchy NVMe Health bar widget.

Reads NVMe/ATA SMART through UDisks2 over the system bus — no root, no
smartctl, no sudoers. Requires udisks2 (ships with Omarchy).
"""

from __future__ import annotations

import json
import sys
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


UDISKS = "org.freedesktop.UDisks2"
IFACE_DRIVE = "org.freedesktop.UDisks2.Drive"
IFACE_NVME = "org.freedesktop.UDisks2.NVMe.Controller"
IFACE_ATA = "org.freedesktop.UDisks2.Drive.Ata"
IFACE_BLOCK = "org.freedesktop.UDisks2.Block"


def bytes_to_path(value: Any) -> str:
  if isinstance(value, (bytes, bytearray)):
    return bytes(value).split(b"\x00", 1)[0].decode("utf-8", "replace")
  if isinstance(value, str):
    return value.split("\x00", 1)[0]
  if isinstance(value, (list, tuple)):
    try:
      return bytes(int(x) & 0xFF for x in value).split(b"\x00", 1)[0].decode("utf-8", "replace")
    except (TypeError, ValueError):
      return ""
  return ""


def as_int(value: Any) -> int | None:
  try:
    if value is None:
      return None
    return int(value)
  except (TypeError, ValueError):
    return None


def bytes_to_tib(num_bytes: int | None) -> float | None:
  if num_bytes is None or num_bytes < 0:
    return None
  return round(num_bytes / (1024**4), 2)


def get_managed_objects() -> dict[str, dict[str, dict[str, Any]]]:
  bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
  om = Gio.DBusProxy.new_sync(
    bus,
    Gio.DBusProxyFlags.NONE,
    None,
    UDISKS,
    "/org/freedesktop/UDisks2",
    "org.freedesktop.DBus.ObjectManager",
    None,
  )
  result = om.call_sync("GetManagedObjects", None, Gio.DBusCallFlags.NONE, -1, None)
  objs = result.unpack()
  if isinstance(objs, tuple):
    objs = objs[0]
  return objs if isinstance(objs, dict) else {}


def call_method(path: str, iface: str, method: str) -> Any:
  bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
  proxy = Gio.DBusProxy.new_sync(
    bus,
    Gio.DBusProxyFlags.NONE,
    None,
    UDISKS,
    path,
    iface,
    None,
  )
  result = proxy.call_sync(
    method,
    GLib.Variant("(a{sv})", ([],)),
    Gio.DBusCallFlags.NONE,
    -1,
    None,
  )
  return result.unpack()


def block_paths_for_drive(objects: dict[str, Any], drive_path: str) -> list[str]:
  names: list[str] = []
  for path, ifaces in objects.items():
    block = ifaces.get(IFACE_BLOCK)
    if not block:
      continue
    if str(block.get("Drive") or "") != drive_path:
      continue
    # Skip partitions: they also point at the same Drive in some setups via
    # the parent disk; prefer whole-disk nodes (no Partition iface).
    if "org.freedesktop.UDisks2.Partition" in ifaces:
      continue
    device = bytes_to_path(block.get("Device") or block.get("PreferredDevice"))
    if device:
      names.append(device)
  return names


def device_matches(requested: str, candidates: list[str], drive_id: str) -> bool:
  if not requested:
    return False
  req = requested.strip()
  if req == drive_id or req in candidates:
    return True
  for name in candidates:
    # /dev/nvme0 matches /dev/nvme0n1; /dev/sda matches /dev/sda
    if name == req or name.startswith(req):
      return True
    if req.startswith(name):
      return True
  return False


def ata_attr_raw(attrs: Any, *names: str) -> int | None:
  # ATA SmartGetAttributes returns (a{sv} or aa{sv} depending on version).
  wanted = {n.lower() for n in names}
  rows: list[Any]
  if isinstance(attrs, tuple) and len(attrs) == 1:
    attrs = attrs[0]
  if isinstance(attrs, dict):
    # Some builds return id->struct; flatten values
    rows = list(attrs.values())
  elif isinstance(attrs, list):
    rows = attrs
  else:
    return None
  for row in rows:
    if not isinstance(row, dict):
      continue
    name = str(row.get("name") or row.get("Name") or "").lower()
    if name not in wanted:
      continue
    for key in ("raw", "value", "Raw", "Value"):
      if key in row:
        return as_int(row.get(key))
  return None


def summarize_nvme(drive: dict[str, Any], nvme_props: dict[str, Any], attrs: dict[str, Any], device: str) -> dict[str, Any]:
  percent_used = as_int(attrs.get("percent_used"))
  life_remaining = None if percent_used is None else max(0, 100 - percent_used)
  spare = as_int(attrs.get("avail_spare"))
  media_errors = as_int(attrs.get("media_errors"))
  written = as_int(attrs.get("total_data_written"))
  hours = as_int(nvme_props.get("SmartPowerOnHours"))
  critical = nvme_props.get("SmartCriticalWarning") or []
  warning = False
  if isinstance(critical, (list, tuple)) and len(critical) > 0:
    warning = True
  if media_errors is not None and media_errors > 0:
    warning = True
  if spare is not None and spare < 10:
    warning = True
  if life_remaining is not None and life_remaining <= 10:
    warning = True

  return {
    "device": device,
    "type": "nvme",
    "model": str(drive.get("Model") or "").strip(),
    "serial": str(drive.get("Serial") or "").strip(),
    "protocol": "nvme",
    "passed": None if warning else True,
    "warning": warning,
    "powerOnHours": hours,
    "reallocatedSectors": None,
    "mediaErrors": media_errors,
    "availableSparePercent": spare,
    "percentageUsed": percent_used,
    "lifeRemainingPercent": life_remaining,
    "tbwTiB": bytes_to_tib(written),
    "criticalWarning": len(critical) if isinstance(critical, (list, tuple)) else 0,
  }


def summarize_ata(drive: dict[str, Any], ata_props: dict[str, Any], attrs: Any, device: str) -> dict[str, Any]:
  hours = ata_attr_raw(attrs, "power_on_hours", "Power_On_Hours")
  if hours is None:
    seconds = as_int(ata_props.get("SmartPowerOnSeconds"))
    if seconds is not None:
      hours = seconds // 3600
  reallocated = ata_attr_raw(attrs, "reallocated_sector_ct", "Reallocated_Sector_Ct")
  life = ata_attr_raw(attrs, "percent_lifetime_remain", "Percent_Lifetime_Remain", "Percent_Lifetime_Remaining")
  failing = bool(ata_props.get("SmartFailing"))
  warning = failing or (reallocated is not None and reallocated > 0) or (life is not None and life <= 10)
  return {
    "device": device,
    "type": "ata",
    "model": str(drive.get("Model") or "").strip(),
    "serial": str(drive.get("Serial") or "").strip(),
    "protocol": "ata",
    "passed": (not failing) if ata_props.get("SmartFailing") is not None else None,
    "warning": warning,
    "powerOnHours": hours,
    "reallocatedSectors": reallocated,
    "mediaErrors": None,
    "availableSparePercent": None,
    "percentageUsed": None if life is None else max(0, 100 - life),
    "lifeRemainingPercent": life,
    "tbwTiB": None,
    "criticalWarning": 0,
  }


def collect_disks(objects: dict[str, Any]) -> list[dict[str, Any]]:
  disks: list[dict[str, Any]] = []
  for path, ifaces in objects.items():
    drive = ifaces.get(IFACE_DRIVE)
    if not drive:
      continue
    # Skip removable optical / empty media
    if drive.get("Optical") or drive.get("MediaRemovable"):
      continue
    if drive.get("MediaAvailable") is False:
      continue

    is_nvme = IFACE_NVME in ifaces
    is_ata = IFACE_ATA in ifaces
    if not is_nvme and not is_ata:
      continue

    blocks = block_paths_for_drive(objects, path)
    device = blocks[0] if blocks else path
    iface = IFACE_NVME if is_nvme else IFACE_ATA
    try:
      call_method(path, iface, "SmartUpdate")
    except Exception:
      pass
    try:
      attrs_pack = call_method(path, iface, "SmartGetAttributes")
    except Exception as exc:
      disks.append(
        {
          "ok": False,
          "path": path,
          "device": device,
          "error": str(exc),
          "protocol": "nvme" if is_nvme else "ata",
          "model": str(drive.get("Model") or "").strip(),
        }
      )
      continue

    attrs = attrs_pack[0] if isinstance(attrs_pack, tuple) else attrs_pack
    if is_nvme:
      summary = summarize_nvme(drive, ifaces.get(IFACE_NVME) or {}, attrs if isinstance(attrs, dict) else {}, device)
    else:
      summary = summarize_ata(drive, ifaces.get(IFACE_ATA) or {}, attrs, device)
    summary["path"] = path
    summary["candidates"] = blocks
    disks.append(summary)
  return disks


def pick_disk(disks: list[dict[str, Any]], requested: str) -> dict[str, Any] | None:
  healthy = [d for d in disks if d.get("protocol") in ("nvme", "ata") and "lifeRemainingPercent" in d]
  if requested:
    for d in healthy:
      if device_matches(requested, d.get("candidates") or [d.get("device") or ""], d.get("path") or ""):
        return d
    return None
  for d in healthy:
    if d.get("protocol") == "nvme":
      return d
  return healthy[0] if healthy else None


def main() -> int:
  requested = sys.argv[1].strip() if len(sys.argv) > 1 else ""
  try:
    objects = get_managed_objects()
  except Exception as exc:
    print(
      json.dumps(
        {
          "ok": False,
          "error": "udisks_unavailable",
          "message": f"Could not talk to UDisks2: {exc}",
          "needsSetup": False,
          "devices": [],
          "disk": None,
        }
      )
    )
    return 0

  disks = collect_disks(objects)
  devices = [
    {
      "name": d.get("device") or d.get("path"),
      "type": d.get("protocol") or d.get("type") or "",
      "info": d.get("model") or d.get("device") or "",
    }
    for d in disks
    if d.get("protocol") in ("nvme", "ata")
  ]

  chosen = pick_disk(disks, requested)
  if not chosen:
    print(
      json.dumps(
        {
          "ok": False,
          "error": "no_devices",
          "message": "No NVMe/ATA drives with SMART data were found.",
          "needsSetup": False,
          "devices": devices,
          "disk": None,
        }
      )
    )
    return 0

  # Strip helper fields before emitting
  disk = {k: v for k, v in chosen.items() if k not in ("path", "candidates", "ok", "error")}
  print(
    json.dumps(
      {
        "ok": True,
        "error": "",
        "message": "",
        "needsSetup": False,
        "devices": devices,
        "disk": disk,
      }
    )
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
