[README.md](https://github.com/user-attachments/files/34875738/README.md)
# ED ExoTool

Watches the Elite Dangerous journal and shows your exobiology samples on a web
dashboard: current body and sample progress, bio signals in the current system,
unsold samples with estimated value, and which bodies to revisit after a death.

## Setup (once)

1. Put the `ed-exotool` folder where it should stay, e.g. `~/Apps/ed-exotool`.
2. In a terminal inside that folder run `./install-shortcut.sh`.
   On KDE Plasma, the first click on the desktop icon may ask whether you trust it.
3. If a firewall is active on your PC, allow the port so the tablet can connect,
   e.g. with ufw: `sudo ufw allow 8765/tcp`

## Use

Start ExoTool from the desktop icon. A terminal window opens, reads all new
journal entries and prints the address for your tablet, e.g. `http://192.168.1.20:8765`.
Close the window to stop it. Starting it later is fine: it catches up on
everything that happened while it wasn't running.

## Files

- Database: `~/.local/share/ed-exotool/exotool.db` (SQLite). It can always be
  rebuilt from the journals: delete it or start with `python3 exotool.py --reimport`.
- Settings: `~/.config/ed-exotool/config.json`
  - `journal_dir`: empty means auto-detect (Steam/Proton, also Flatpak Steam and
    extra Steam libraries). Set it if your journals are somewhere else.
  - `port`: dashboard port (default 8765)
  - `assume_first_footfall` / `footfall_multiplier`: how estimates are calculated

## Values

Estimates use a built-in table of community base values. After you sell a
species once, the real value from Vista Genomics is stored in `learned_values`
and used from then on. If the game runs in a language where species names differ
from the English table, values show as "?" until the first sale.

## Your own queries

Open the database with `sqlite3` or DB Browser for SQLite. Useful tables:
`samples` (status unsold / sold / lost), `bodies`, `systems`, `deaths`, `scans`
(every single scan), `learned_values`.
<img width="1798" height="1866" alt="Exotool" src="https://github.com/user-attachments/assets/0586c84b-9e25-4d44-9f7b-4cf12db5a590" />
