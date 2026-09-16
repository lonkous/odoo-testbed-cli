---
name: tb
description: >-
  Runs local Docker Odoo testbeds via tb MCP tools (start, stop, restore, dump,
  tests, module scaffold). Use when the user mentions tb, testbed, Odoo Docker,
  restoring a dump, running module tests, or starting/stopping a local Odoo stack.
---

# tb testbed

Use the **tb** MCP tools. Do not invent `docker compose` commands or shell out to `tb` when an MCP tool exists.

## Project name

Omit `name` when the workspace is inside a testbed folder (`.env` plus `.testbed/docker/docker-compose.yml`). Pass `name` (database name, folder name, or path) only when cwd is not a testbed. If a tool returns a project list, pick from that list.

## Tools

- `tb_doctor`, `tb_list_projects`, `tb_status`
- `tb_start` (`init`, `parallel`), `tb_stop`
- `tb_down` and `tb_restore` require `confirm=true`
- `tb_dump`, `tb_test`, `tb_reload`, `tb_create_module`, `tb_vscode`

## Terminal only

`tb logs`, `tb psql`, `tb shell`, `tb open`, and `tb setup` need a real terminal. Tell the user to run those in the CLI.
