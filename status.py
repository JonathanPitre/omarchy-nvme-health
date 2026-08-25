#!/usr/bin/env python3
"""Emit SMART health JSON for Omarchy NVMe Health bar widget.

Uses `sudo -n /usr/bin/smartctl` for passwordless reads. Run setup-sudoers.sh once
if sudo -n is not configured.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


SMARTCTL = "/usr/bin/smartctl"
SKIP_HINTS = ("megaraid", "cciss", "areca", "3ware", "sat+megaraid")


def run_smartctl(args: list[str], timeout: float = 12.0) -> tuple[int, str, str]:
  command = ["sudo", "-n", SMARTCTL, *args]
  try:
    completed = subprocess.run(
      command,
      check=False,
      capture_output=True,
      text=True,
      timeout=timeout,
    )
  except FileNotFoundError:
    return 127, "", "smartctl or sudo not found"
  except subprocess.TimeoutExpired:
    return 124, "", "smartctl timed out"
  return completed.returncode, completed.stdout or "", completed.stderr or ""


def parse_json(text: str) -> dict[str, Any] | None:
  text = (text or "").strip()
  if not text:
    return None
  try:
    data = json.loads(text)
  except json.JSONDecodeError:
    return None
  return data if isinstance(data, dict) else None


def smartctl_missing() -> bool:
  return not os.path.isfile(SMARTCTL)


def needs_setup(exit_code: int, stderr: str) -> bool:
  if exit_code in (0, 4, 64, 68, 192, 196):  # smartctl bitflags: 4=FAILING often still JSON
    return False
  combined = (stderr or "").lower()
  if "a password is required" in combined:
    return True
  if "a terminal is required" in combined:
    return True
  if "sudo:" in combined and "password" in combined:
    return True
  if exit_code in (1, 126, 127) and "sudo" in combined:
    return True
  return False


def skip_device(name: str, type_name: str) -> bool:
  blob = f"{name} {type_name}".lower()
  if "/dev/dm-" in blob or blob.startswith("dm-"):
    return True
  return any(hint in blob for hint in SKIP_HINTS)


def scan_devices() -> tuple[list[dict[str, str]], str | None, bool]:
  code, stdout, stderr = run_smartctl(["--scan", "-j"])
  if needs_setup(code, stderr):
    return [], "needs_sudoers", True
  if code == 127 or smartctl_missing():
    return [], "missing_smartctl", False

  data = parse_json(stdout)
  devices: list[dict[str, str]] = []
  if data and isinstance(data.get("devices"), list):
    for entry in data["devices"]:
      if not isinstance(entry, dict):
        continue
      name = str(entry.get("name") or "")
      type_name = str(entry.get("type") or "")
      if not name or skip_device(name, type_name):
        continue
      devices.append({"name": name, "type": type_name, "info": str(entry.get("info_name") or name)})
  else:
    # Fallback: plain text scan
    code2, stdout2, stderr2 = run_smartctl(["--scan"])
    if needs_setup(code2, stderr2):
      return [], "needs_sudoers", True
    for line in (stdout2 or "").splitlines():
      parts = line.split("#", 1)[0].split()
      if len(parts) < 1:
        continue
      name = parts[0]
      type_name = parts[2] if len(parts) >= 3 and parts[1] == "-d" else ""
      if skip_device(name, type_name):
        continue
      devices.append({"name": name, "type": type_name, "info": name})

  return devices, None, False


def ata_attr(table: Any, *names: str) -> int | None:
  if not isinstance(table, list):
    return None
  wanted = {n.lower() for n in names}
  for row in table:
    if not isinstance(row, dict):
      continue
    name = str(row.get("name") or "").lower()
    if name not in wanted:
      continue
    raw = row.get("raw")
    if isinstance(raw, dict) and "value" in raw:
      try:
        return int(raw["value"])
      except (TypeError, ValueError):
        pass
    try:
      return int(row.get("raw_value"))
    except (TypeError, ValueError):
      pass
  return None


def bytes_to_tib(num_bytes: float | None) -> float | None:
  if num_bytes is None or num_bytes < 0:
    return None
  return round(num_bytes / (1024 ** 4), 2)


def summarize(device: str, type_name: str, payload: dict[str, Any]) -> dict[str, Any]:
  nvme = payload.get("nvme_smart_health_information_log")
  if not isinstance(nvme, dict):
    nvme = {}

  ata_table = None
  ata = payload.get("ata_smart_attributes")
  if isinstance(ata, dict):
    ata_table = ata.get("table")

  model = ""
  serial = ""
  info = payload.get("model_name") or payload.get("scsi_model_name")
  if isinstance(info, str):
    model = info.strip()
  model_info = payload.get("model_name")
  if not model and isinstance(payload.get("device"), dict):
    model = str(payload["device"].get("name") or "")
  serial_val = payload.get("serial_number")
  if isinstance(serial_val, str):
    serial = serial_val.strip()

  protocol = str(payload.get("device", {}).get("protocol") or type_name or "").lower() if isinstance(payload.get("device"), dict) else str(type_name or "").lower()
  is_nvme = "nvme" in protocol or bool(nvme)

  power_on_hours = None
  pot = payload.get("power_on_time")
  if isinstance(pot, dict) and "hours" in pot:
    try:
      power_on_hours = int(pot["hours"])
    except (TypeError, ValueError):
      power_on_hours = None
  if power_on_hours is None:
    power_on_hours = ata_attr(ata_table, "Power_On_Hours", "Power_On_Hour")

  reallocated = ata_attr(ata_table, "Reallocated_Sector_Ct", "Reallocated_Sector_Count")
  media_errors = None
  if "media_errors" in nvme:
    try:
      media_errors = int(nvme["media_errors"])
    except (TypeError, ValueError):
      media_errors = None

  available_spare = None
  if "available_spare" in nvme:
    try:
      available_spare = int(nvme["available_spare"])
    except (TypeError, ValueError):
      available_spare = None

  percentage_used = None
  if "percentage_used" in nvme:
    try:
      percentage_used = int(nvme["percentage_used"])
    except (TypeError, ValueError):
      percentage_used = None

  life_remaining = None
  if percentage_used is not None:
    life_remaining = max(0, 100 - percentage_used)
  else:
    plr = ata_attr(ata_table, "Percent_Lifetime_Remain", "Percent_Lifetime_Remaining")
    if plr is not None:
      life_remaining = max(0, min(100, plr))
    else:
      wear = ata_attr(ata_table, "Wear_Leveling_Count")
      if wear is not None and 0 <= wear <= 100:
        # Often normalized remaining; treat as remaining when high.
        life_remaining = wear

  tbw_tib = None
  if "data_units_written" in nvme:
    try:
      # NVMe SMART: one data unit = 1000 * 512 bytes
      tbw_tib = bytes_to_tib(int(nvme["data_units_written"]) * 512000)
    except (TypeError, ValueError):
      tbw_tib = None
  if tbw_tib is None:
    host_written = ata_attr(ata_table, "Total_LBAs_Written", "Host_Writes_32MiB", "Lifetime_Writes_GiB")
    # Best-effort; leave null when unknown units
    if host_written is not None and ata_attr(ata_table, "Lifetime_Writes_GiB") is not None:
      tbw_tib = round(host_written / 1024, 2)

  smart_status = payload.get("smart_status")
  passed = None
  if isinstance(smart_status, dict) and "passed" in smart_status:
    passed = bool(smart_status["passed"])

  critical_warning = 0
  if "critical_warning" in nvme:
    try:
      critical_warning = int(nvme["critical_warning"])
    except (TypeError, ValueError):
      critical_warning = 0

  warning = False
  if passed is False:
    warning = True
  if critical_warning:
    warning = True
  if reallocated is not None and reallocated > 0:
    warning = True
  if media_errors is not None and media_errors > 0:
    warning = True
  if available_spare is not None and available_spare < 10:
    warning = True
  if life_remaining is not None and life_remaining <= 10:
    warning = True

  return {
    "device": device,
    "type": type_name or ("nvme" if is_nvme else protocol),
    "model": model,
    "serial": serial,
    "protocol": "nvme" if is_nvme else (protocol or "ata"),
    "passed": passed,
    "warning": warning,
    "powerOnHours": power_on_hours,
    "reallocatedSectors": reallocated,
    "mediaErrors": media_errors,
    "availableSparePercent": available_spare,
    "percentageUsed": percentage_used,
    "lifeRemainingPercent": life_remaining,
    "tbwTiB": tbw_tib,
    "criticalWarning": critical_warning,
  }


def pick_device(devices: list[dict[str, str]], requested: str) -> dict[str, str] | None:
  if requested:
    for entry in devices:
      if entry["name"] == requested:
        return entry
    return {"name": requested, "type": "", "info": requested}

  for entry in devices:
    blob = f'{entry["name"]} {entry["type"]}'.lower()
    if "nvme" in blob:
      return entry
  return devices[0] if devices else None


def main() -> int:
  requested = ""
  if len(sys.argv) > 1:
    requested = sys.argv[1].strip()

  if smartctl_missing():
    print(json.dumps({
      "ok": False,
      "error": "missing_smartctl",
      "message": "Install smartmontools (omarchy pkg add smartmontools).",
      "needsSetup": False,
      "devices": [],
      "disk": None,
    }))
    return 0

  devices, scan_error, setup = scan_devices()
  if setup:
    print(json.dumps({
      "ok": False,
      "error": "needs_sudoers",
      "message": "Run setup-sudoers.sh once so sudo -n smartctl works.",
      "needsSetup": True,
      "devices": [],
      "disk": None,
    }))
    return 0

  if scan_error == "missing_smartctl":
    print(json.dumps({
      "ok": False,
      "error": "missing_smartctl",
      "message": "Install smartmontools (omarchy pkg add smartmontools).",
      "needsSetup": False,
      "devices": [],
      "disk": None,
    }))
    return 0

  chosen = pick_device(devices, requested)
  if not chosen:
    print(json.dumps({
      "ok": False,
      "error": "no_devices",
      "message": "No SMART devices found.",
      "needsSetup": False,
      "devices": devices,
      "disk": None,
    }))
    return 0

  args = ["-j", "-a", chosen["name"]]
  if chosen.get("type"):
    args = ["-j", "-d", chosen["type"], "-a", chosen["name"]]

  code, stdout, stderr = run_smartctl(args)
  if needs_setup(code, stderr):
    print(json.dumps({
      "ok": False,
      "error": "needs_sudoers",
      "message": "Run setup-sudoers.sh once so sudo -n smartctl works.",
      "needsSetup": True,
      "devices": devices,
      "disk": None,
    }))
    return 0

  payload = parse_json(stdout)
  # smartctl uses exit bitflags; JSON can still be valid with non-zero status
  if payload is None:
    print(json.dumps({
      "ok": False,
      "error": "smartctl_failed",
      "message": (stderr or stdout or "smartctl failed").strip()[:240],
      "needsSetup": False,
      "devices": devices,
      "disk": None,
      "exitCode": code,
    }))
    return 0

  disk = summarize(chosen["name"], chosen.get("type") or "", payload)
  print(json.dumps({
    "ok": True,
    "error": "",
    "message": "",
    "needsSetup": False,
    "devices": devices,
    "disk": disk,
    "exitCode": code,
  }))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
