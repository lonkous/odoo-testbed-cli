# testbed-cli

A local development CLI for Odoo. It starts and stops Docker-based Odoo instances on your machine, and wraps a handful of existing tools into one place: restore, dump, tests, module scaffold, translations, logs, and the rest of the `.testbed` stack, via a single `tb` command.

The other point of this repo is practice: coordinating an AI to a **100% implementation**. A person directed the work; no line of the product was hand-written first.

## New computer

You need Python 3.12+, Docker, pipx, and GitHub SSH (for `odoo/enterprise` and the `.testbed` submodule). Then:

```bash
git clone git@github.com:lonkous/testbed.git
cd testbed
./install.sh
```

That puts `tb` and `tb-mcp` on your PATH, writes `~/.config/testbed-cli/config.toml` with defaults (`~/Documents` for projects, `/opt/odoo` for enterprise, one stack at a time), registers a Cursor MCP server in `~/.cursor/mcp.json`, copies a personal Cursor skill to `~/.cursor/skills/tb/`, installs a local Cursor plugin under `~/.cursor/plugins/local/tb/`, and runs `tb doctor`. Open a new terminal if `tb` is not found yet.

**Cursor.** After install, open **Settings → Tools & MCP** and enable the `tb` server if it is not already on (or **Developer: Reload Window** so the local plugin loads). The agent can start/stop/restore/test, tail a log snapshot, run SQL or odoo-shell code, open the web UI, and write setup from any Odoo repo. `tb_down` / `tb_restore` need `confirm=true`. Hosts that support MCP Apps can render `tb_dashboard`.

Optional Streamable HTTP instead of stdio:

```bash
tb-mcp --http --host 127.0.0.1 --port 8765
```

Then add a Cursor MCP server with URL `http://127.0.0.1:8765/mcp`. The GitHub repo can be submitted as a Cursor marketplace (plugin lives in `plugin/`).

If you already cloned it somewhere else, `./install.sh` still works from that folder. After pulling updates, run it again (or `pipx install --editable . --force` from the repo).

`tb doctor` is the checklist. Fix whatever it flags, then run it until Docker is ok.

**Docker.** Install the engine, add yourself to the `docker` group, then log out and back in:

```bash
sudo usermod -aG docker "$USER"
```

**Odoo enterprise clone.** First `tb start` will `git clone` into the odoo root. `/opt/odoo` usually needs to exist and be yours:

```bash
sudo mkdir -p /opt/odoo
sudo chown "$USER" /opt/odoo
```

If you would rather not touch `/opt`, skip that and point at a folder you own:

```bash
tb setup --odoo-root ~/odoo
```

**Odoo project repos.** Defaults look under `~/Documents`. Clone each repo *there* (or tell setup another parent), and bring the `.testbed` submodule with it:

```bash
cd ~/Documents
git clone --recurse-submodules git@github.com:example/your-project.git
```

Already cloned without the submodule?

```bash
cd ~/Documents/your-project
git submodule update --init --recursive
```

A project is a folder with `.env` (`DATABASE_NAME`, `ODOO_VERSION`) and `.testbed/docker/docker-compose.yml`. You can pass the database name (`demo`), the folder name, or a path.

**Paths that are not the defaults.** `install.sh` does not prompt. Change them when you need to:

```bash
tb setup
tb setup --odoo-root /opt/odoo --project-root ~/Documents --no-parallel
tb setup --show
```

`tb setup` asks for project folders, odoo source root, optional backup folders, and whether two testbeds may run at once. An older `~/.config/testbed-tui/config.toml` is still read if the new file is missing.

If an old `testbed-tui` pipx install is on the machine, remove it first: `pipx uninstall testbed-tui`.

When `tb doctor` lists your projects and `docker: ok`, start one. From inside the repo you can omit the name:

```bash
cd ~/Documents/your-project
tb start --init
tb start
```

From anywhere else, pass the name (`tb start demo`) or omit it and pick from the list.

## A normal day on an existing repo

From the project folder, omit the name. `--init` is for an empty database with `MODULES_TO_TEST` installed (first time, or after you wiped volumes). Later starts skip that:

```bash
tb status
tb start --init
tb start
tb logs
tb open
```

`tb open` hits the published HTTP port (`admin` / `admin` after a restore). Stop keeps volumes. `tb down` throws the database away (it asks first; `--yes` skips the prompt). Names still work from anywhere (`tb start demo`).

`tb vscode` writes launch/tasks/settings into that Odoo repo from the templates in this project.

## Restore a customer dump

This is the old `start_db_from_backup.sh` path, plus filestore when the zip contains one.

```bash
tb restore demo ~/backups/demo-prod.zip
```

It wipes volumes, loads `.zip` / `.sql` / `.dump`, runs neutralize SQL, copies filestore if present, then starts web. You confirm first. Login is `admin` / `admin`.

`tb dump demo` writes under `.testbed/snapshots/` (or pass a path). `tb neutralize demo` is the same SQL on a running database. `tb psql demo` and `tb shell demo` drop you into Postgres or an Odoo shell. Mail: `tb mailpit demo`.

## Write a module and run tests

Scaffold under `addons/`. `-d` / `--full` also creates data, security, tests, wizards, reports, and static folders:

```bash
tb create-module demo sale_custom
tb create-module demo sale_custom -d --odoo 18
```

After Python/XML changes: `tb reload demo sale_custom` or `tb update-modules demo` for every custom addon.

Tests use the test compose file when the repo has one. Custom addons go through pytest-odoo; standard/enterprise modules use Odoo `--test-tags`. Coverage HTML, if generated, lands in `htmlcov/`.

```bash
tb test demo
tb test demo -m sale_custom -k test_partner --reinit-db
```

`--reinit-db` drops the `test` database first. Translations: `tb i18n export demo de_CH sale_custom` and `tb i18n import …`. Licence keys: `tb license demo`. Stuck debugpy: `tb debug-restart demo`.

## Brand new repo

```bash
tb init ~/Documents/new-project --db newdb --odoo 18 --module sale_custom
```

That writes `.env` and VS Code files. The folder must already contain `.testbed` (compose under `.testbed/docker/`). Then `tb start newdb --init`.

## Only one stack at a time

Host ports in compose are the usual 8069 / 8068 / 8888. By default `tb start` stops any other running testbed first and prints a heads-up. Pass `--parallel` (or set `allow_parallel = true` in setup) to leave the other stack up. Parallel mode reassigns host ports when they clash.

`tb --help` lists every command in the same groups the CLI uses: setup, create, docker, database, modules.

## Development of this repo

Open this folder in VS Code or Cursor. Run and Debug has `tb doctor`, `tb status`, and Pytest. Select the `.venv` interpreter if the editor does not pick it up.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

Background, layout, and what was dropped from the old TUI live in [plan.md](plan.md).
