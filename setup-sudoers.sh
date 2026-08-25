#!/usr/bin/env bash
# Install a narrow NOPASSWD rule so the NVMe Health plugin can poll smartctl -j
# without an interactive password prompt.
set -euo pipefail

RULE_PATH="/etc/sudoers.d/omarchy-nvme-health"
SMARTCTL="/usr/bin/smartctl"

if [[ ! -x $SMARTCTL ]]; then
  echo "smartctl not found at $SMARTCTL"
  echo "Install it first: omarchy pkg add smartmontools"
  exit 1
fi

USER_NAME="${SUDO_USER:-${USER:-$(id -un)}}"
if [[ $USER_NAME == root ]]; then
  echo "Run this script as your normal user (it will ask for elevation)."
  exit 1
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

cat >"$TMP" <<EOF
# Omarchy NVMe Health — read-only smartctl JSON probes only.
# Installed by setup-sudoers.sh from the omarchy-nvme-health plugin.
$USER_NAME ALL=(root) NOPASSWD: $SMARTCTL --scan, $SMARTCTL --scan -j, $SMARTCTL -j --scan
$USER_NAME ALL=(root) NOPASSWD: $SMARTCTL -j -a /dev/*, $SMARTCTL -j -A /dev/*, $SMARTCTL -j -H /dev/*, $SMARTCTL -j -i /dev/*
$USER_NAME ALL=(root) NOPASSWD: $SMARTCTL -j -d nvme -a /dev/*, $SMARTCTL -j -d sat -a /dev/*, $SMARTCTL -j -d auto -a /dev/*
EOF

echo "Will install passwordless sudo rules for user '$USER_NAME' at:"
echo "  $RULE_PATH"
echo
cat "$TMP"
echo

if ! visudo -cf "$TMP" >/dev/null; then
  echo "Generated sudoers snippet failed validation."
  exit 1
fi

if command -v pkexec >/dev/null 2>&1; then
  pkexec bash -c "install -m 0440 '$TMP' '$RULE_PATH' && visudo -cf '$RULE_PATH'"
else
  sudo install -m 0440 "$TMP" "$RULE_PATH"
  sudo visudo -cf "$RULE_PATH"
fi

echo
echo "Installed. Test with:"
echo "  sudo -n $SMARTCTL --scan -j"
echo "  python3 \"$(cd "$(dirname "$0")" && pwd)/status.py\""
