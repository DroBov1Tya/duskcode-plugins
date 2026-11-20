# Submitting a connector

A connector is an MCP server that duskcode adds to the user's connectors in one click, from
Customize, Connectors, Discover. It has no package and nothing is built: the listing says
where the server is (an `https` address) or which pinned package starts it (`npx` or
`uvx`), how it signs in, and the names of the secrets the user fills in. duskcode writes it
into the config exactly as the MCP settings would, after a confirmation that shows all of
that; removing it removes the server.

A connector is a pull request like any other item. The maintainer checks the endpoint
against the service's own documentation and signs the next list.

## What qualifies

- The service's **own** server, documented on the service's own site, or a reference
  server of the Model Context Protocol project. Community servers for a service that has
  none of its own are not listed here; say so in the pull request if you think one should
  be, with who runs it.
- A remote server speaks **Streamable HTTP** (duskcode does not speak the older SSE
  transport) at an `https` address on a public host.
- Signing in is either none, a **key** the user pastes into the server's settings, or
  **OAuth** with dynamic client registration (the MCP authorization spec): duskcode
  registers itself on the first sign-in. A server that only accepts clients registered
  in advance by the vendor (an allowlist, a client ID the user must create) does not work
  with one click; leave it out.
- A local server starts with `npx -y <package>@<version>` or `uvx <package>==<version>`:
  one exact version, never `latest` or a range. It runs on the user's computer with their
  rights, so the Workshop lists it only signed (Official or Verified); duskcode refuses a
  local connector from any other source.

## The files

`connectors/<name>/connector.yml`, and nothing else in that folder:

```yaml
name: linear                 # the service's name, a-z, 0-9 and -; the MCP server's name
version: 1.0.0               # raise it whenever anything below changes
description: "Find, create and update the issues of a Linear workspace. Linear's own
  server; you sign in with your Linear account. Not affiliated with or endorsed by Linear."
server:
  url: https://mcp.linear.app/mcp   # or command + args for a local server
  auth: oauth                # none, oauth or key
  docs: https://linear.app/docs/mcp # the service's own page about its server
  run_by: vendor             # vendor: the service runs or publishes it; community: anybody else
  reaches: the issues, projects and comments of the Linear workspace you allow
```

A local one:

```yaml
server:
  command: npx               # npx or uvx
  args: ["-y", "@playwright/mcp@0.0.86"]   # flags, the pinned package, then its own args
  auth: none
```

With a key, name the headers (remote) or environment variables (local) the user fills in;
never a value. duskcode adds such a server switched off, with those fields empty, until the
user puts the key in its settings:

```yaml
  auth: key
  secrets: [Authorization]
```

And its line in `catalog.yml`, under `connectors:`:

```yaml
connectors:
  linear:
    author: Linear                       # who runs or publishes the server
    license: LicenseRef-vendor-terms     # or the SPDX license of an open-source server
    source: https://linear.app/docs/mcp  # where the facts above come from
    categories: [productivity, coding]
    tags: [issues, projects]
```

`LicenseRef-vendor-terms` is for a hosted service: nothing of it is copied here and the
service's own terms apply. A local server names its package's license.

## Names and covers

A connector is the one kind of item named for somebody else's product: its name is the
service it connects to, since that is what it is and the agent's tools carry it
(`linear__create_issue`). Nothing else changes: the description says it is the service's
own server and ends with "Not affiliated with or endorsed by <author>."; the cover is
duskcode's own drawing and names what the service is for ("Issues & cycles"), never the
service, with no logo, mark, colours or trade dress of it. Add the cover to
`scripts/make-covers.py` and render it (`scripts/render-covers.sh`).

## Checks

`scripts/check-index.py --repo .` checks every connector as duskcode's reader does: the
address is `https` on a named public host, a package is pinned, secrets are plain names,
OAuth only for a remote server, a key with one to four secrets. `scripts/publish.py` puts
each connector in the list as `kind: connector` with its `server`; a duskcode older than
connectors leaves such entries out and reads the rest of the list.
