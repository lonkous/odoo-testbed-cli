---
name: tb
description: >-
  Runs local Docker Odoo testbeds via tb MCP tools (start, stop, restore, dump,
  tests, logs, psql, shell, module scaffold). Use when the user mentions tb,
  testbed, Odoo Docker, restoring a dump, running module tests, or starting
  or stopping a local Odoo stack.
---

# tb testbed

Use the **tb** MCP tools. Do not invent `docker compose` commands or shell out to `tb` when an MCP tool exists.

## Project name

Omit `name` when the workspace is inside a testbed folder (`.env` plus `.testbed/docker/docker-compose.yml`). Pass `name` (database name, folder name, or path) only when cwd is not a testbed. If a tool returns a project list, pick from that list.

## Tools

- `tb_doctor`, `tb_list_projects`, `tb_status`, `tb_dashboard`
- `tb_start` (`init`, `parallel`), `tb_stop`
- `tb_down` and `tb_restore` require `confirm=true`
- `tb_dump`, `tb_test`, `tb_reload`, `tb_create_module`, `tb_vscode`
- `tb_logs` (`service`, `tail`) is a snapshot, not a follow
- `tb_psql` needs `sql`; `tb_shell` needs Python `code`
- `tb_open` opens the web UI; `tb_setup` writes config (comma-separated paths)
