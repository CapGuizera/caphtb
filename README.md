# caphtb

A pretty (and industrial) CLI for the **Hack The Box** v4 API, built with
`typer` + `rich`. List and control machines, track first bloods live, explore
challenges (Forensics, Pwn, etc.) and Sherlocks (DFIR), and view world,
country, team and university rankings.

```
  ___ __ _ _ __ | |__ | |_| |__
 / __/ _` | '_ \| '_ \| __| '_ \
| (_| (_| | |_) | | | | |_| |_) |
 \___\__,_| .__/|_| |_|\__|_.__/
          |_|   hack the box cli
```

---

## Quick install

```bash
chmod +x start.sh
./start.sh            # creates .venv, installs everything and shows the help
./start.sh login      # paste your App Token (stored locally only)
```

`start.sh` creates an isolated virtualenv in `.venv/`, installs the
dependencies and forwards any argument to the `caphtb` command.

### Manual install (optional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
caphtb --help
```

### Call it from anywhere (symlink)

After installing, symlink the entry point so you can run it as `caphtbcli`:

```bash
sudo ln -s "$(pwd)/.venv/bin/caphtb" /usr/local/bin/caphtbcli
caphtbcli --help
```

---

## Authentication

1. Generate an **App Token** at <https://app.hackthebox.com/profile/settings>
   (the *App Tokens* / *Create App Token* tab).
2. Run `caphtb login` and paste the token. It is written to
   `~/.config/caphtb/config.json` with permission `0600`.

Alternative without writing to disk: export `HTB_TOKEN`.

```bash
export HTB_TOKEN="eyJ0eXAiOiJKV1Qi..."
```

> The token is a secret. Never put it in a repository or share it.
> `.gitignore` already blocks `config.json`, `.env` and `*.token`.

---

## Usage

Every command has its own `--help` (`caphtb machines --help`).

### Profile

| Command            | What it does                                         |
|--------------------|------------------------------------------------------|
| `caphtb login`     | Save and validate your App Token                     |
| `caphtb whoami`    | Your profile: rank, points, owns and team            |
| `caphtb config`    | Show the current config (without revealing the token)|
| `caphtb version`   | Tool version                                         |

### Machines

```bash
caphtb machines                       # active
caphtb machines --retired             # retired
caphtb machines --retired --done      # retired ones you have owned
caphtb machines --retired --undone    # retired ones you have NOT owned
caphtb machines --os linux -d easy    # filter by OS and difficulty
caphtb machines --todo                # only the ones in your to-do list
caphtb machines --search lame         # search by name
caphtb machine Lame                   # detail (id or name)
caphtb active                         # which machine you have spawned
caphtb startingpoint 1                # starting point by tier
```

`machines` filters: `--retired/-r`, `--done/-D`, `--undone/-u`, `--os`,
`--difficulty/-d`, `--todo` (HTB to-do list), `--search/-s`, `--limit/-n`.

### VM lifecycle

```bash
caphtb spawn Lame          # start (accepts id or name)
caphtb active              # see the IP after a few seconds
caphtb stop                # stop the active machine
caphtb stop Lame           # stop a specific one
caphtb reset Lame          # reset the instance
caphtb submit Lame "HTB{...}" -d 4   # submit flag (difficulty 1-10)
```

### Bloods and live tracking

```bash
caphtb bloods Lame                 # first bloods + own counters
caphtb watch Lame                  # AUTO-REFRESHES and alerts on the blood
caphtb watch Lame --interval 15    # polling interval in seconds
```

`watch` is made for freshly released machines: the screen refreshes on its
own, and when the **user blood** or **root blood** is taken, the tool
highlights it in red and rings the terminal bell.

### Challenges and DFIR (Sherlocks)

```bash
caphtb challenges                          # active
caphtb challenges -c Forensics             # by category
caphtb challenges -c Pwn -d hard --undone  # category + difficulty + unsolved
caphtb challenges --retired --done         # retired ones you have solved
caphtb categories                          # list the categories
caphtb challenge 123                       # challenge detail
caphtb challenge-submit 123 "HTB{...}" -d 3

caphtb dfir                                # Sherlocks (HTB DFIR)
caphtb dfir --retired                      # only retired Sherlocks
caphtb dfir --active --undone              # active Sherlocks you have not solved
caphtb dfir --done                         # solved Sherlocks
caphtb sherlock 631                        # Sherlock detail
```

Done/undone filters work the same way on `challenges` and `dfir`:
`--done/-D` (solved) and `--undone/-u` (unsolved). On `dfir` you also get
`--retired/-r` and `--active/-a`.

> On HTB, **DFIR is the "Sherlocks" product** (blue team investigations),
> not a challenge category, so `dfir` lists Sherlocks.

### Ranking

```bash
caphtb ranking world                 # worldwide Hall of Fame
caphtb ranking --country BR          # users by country (--country implies country scope)
caphtb ranking team                  # teams (global)
caphtb ranking team --country BR     # only Brazilian teams (keeps global rank)
caphtb ranking uni                   # universities
caphtb ranking world -n 50           # how many rows to show
```

---

## Project structure

```
caphtb_cli/
├── caphtb/
│   ├── __init__.py     # package metadata
│   ├── __main__.py     # enables `python -m caphtb`
│   ├── config.py       # token + config + JWT reading
│   ├── api.py          # HTTP client for the HTB v4 API
│   ├── ui.py           # theme, banner, tables and panels (rich)
│   └── cli.py          # commands (typer)
├── requirements.txt
├── pyproject.toml      # packaging + `caphtb` entry point
├── start.sh            # installer/launcher
├── .gitignore
├── LICENSE
└── README.md
```

---

## Technical notes

- **API base:** `https://labs.hackthebox.com/api/v4`. You can change it by
  editing `base_url` in `config.json` if HTB changes the domain.
- **User id:** read from the `sub` claim of your own JWT, with no extra call.
- **Challenge endpoints:** HTB has renamed these endpoints; the client tries
  the new path (`/challenges`) and falls back to the legacy one
  (`/challenge/list`).
- **First bloods:** come from the machine profile itself
  (`userBlood`/`rootBlood`), since the old top-owns endpoint was removed.
- **Rate limit:** excessive calls return `429`; `watch` uses spaced polling
  (default 20s) precisely to avoid hitting the limit.

---

## License

MIT. See `LICENSE`.
