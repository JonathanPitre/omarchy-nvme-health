# NVMe Health

SMART disk health for the Omarchy Quattro bar: remaining life, power-on hours, reallocated sectors / media errors, and TBW.

**Local development only** — not published to the marketplace.

## Dependencies

```sh
omarchy pkg add smartmontools
```

`smartctl` needs root on this system. Install a narrow passwordless rule once:

```sh
cd ~/Projects/omarchy-nvme-health
chmod +x setup-sudoers.sh status.py
./setup-sudoers.sh
```

## Install into the shell (local copy)

```sh
PLUGIN_ID=io.github.qadram.nvme-health
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
mkdir -p "$PLUGIN_DIR"
cp -a manifest.json BarWidget.qml Panel.qml Model.js status.py setup-sudoers.sh "$PLUGIN_DIR/"
chmod +x "$PLUGIN_DIR/status.py" "$PLUGIN_DIR/setup-sudoers.sh"
omarchy plugin validate "$PLUGIN_DIR"
omarchy-shell shell rescanPlugins
omarchy plugin enable "$PLUGIN_ID" --section right
```

## Usage

- Left click: open details panel
- Middle click / `R` in panel: refresh
- Bar label: remaining life `%`, or `!` when warning / setup needed

## Configure

```sh
omarchy bar move io.github.qadram.nvme-health --section right
```

Optional inline settings in `~/.config/omarchy/shell.json`: `refreshIntervalSec`, `device` (e.g. `/dev/nvme0`).

## Remove

```sh
omarchy plugin remove io.github.qadram.nvme-health
# optional: sudo rm /etc/sudoers.d/omarchy-nvme-health
```

## License

MIT
