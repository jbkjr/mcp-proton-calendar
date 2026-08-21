# mcp-proton-calendar

MCP server for creating, updating, and cancelling Proton Calendar events by sending
ICS invitation emails through the local ProtonMail Bridge SMTP listener.

Tools: `create_proton_calendar_event`, `update_proton_calendar_event`,
`cancel_proton_calendar_event`.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PROTON_CALENDAR_EMAIL` | `""` | Your Proton address; organizer and always-included recipient. |
| `PROTON_CALENDAR_FULL_NAME` | `""` | Display name used in `From` and `ORGANIZER`. |
| `PROTON_CALENDAR_SMTP_HOST` | `127.0.0.1` | Proton Bridge SMTP host. |
| `PROTON_CALENDAR_SMTP_PORT` | `1025` | Proton Bridge SMTP port. |
| `PROTON_CALENDAR_SMTP_USER` | `""` | Bridge SMTP username (usually the same address). |
| `PROTON_CALENDAR_SMTP_PASSWORD` | unset | Bridge SMTP token. **Fallback only** — prefer the keyring (below). |
| `PROTON_CALENDAR_KEYRING_SERVICE` | `mcp-proton-calendar` | Override the keyring service name to read the token from. |
| `PROTON_CALENDAR_KEYRING_USERNAME` | `smtp` | Override the keyring entry name to read the token from. |

## Credential resolution

The Bridge SMTP token does not need to be stored in plaintext in an MCP client
config. It is resolved lazily on each send, in this order:

1. The keyring entry named by `PROTON_CALENDAR_KEYRING_SERVICE` /
   `PROTON_CALENDAR_KEYRING_USERNAME`, if either is set. That pair is then the only
   keyring entry consulted.
2. This server's own entry: service `mcp-proton-calendar`, username `smtp`.
3. The sibling [mcp-email-server](https://github.com/ai-zerolab/mcp-email-server)
   entry for the same Bridge token: service `mcp-email-server`, username
   `proton:outgoing`. Bridge issues one token per account, so sharing that entry
   keeps one token in one place rather than two copies that drift apart when Bridge
   regenerates it.
4. `PROTON_CALENDAR_SMTP_PASSWORD`.

Nothing here imports the mcp-email-server package — step 3 is only a
`(service, username)` string pair, and steps 1–2 let you move off it without a code
change. A locked keychain, a denied prompt, or a missing backend is logged and
falls through to the next source rather than failing the send.

To store a dedicated entry for this server (macOS; prompts for the token instead of
taking it on the command line, so it stays out of your shell history):

```sh
security add-generic-password -s mcp-proton-calendar -a smtp -w
```

## MCP client configuration

```json
{
  "mcpServers": {
    "proton-calendar": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-proton-calendar", "mcp-proton-calendar"],
      "env": {
        "PROTON_CALENDAR_EMAIL": "you@example.com",
        "PROTON_CALENDAR_FULL_NAME": "Your Name",
        "PROTON_CALENDAR_SMTP_HOST": "127.0.0.1",
        "PROTON_CALENDAR_SMTP_PORT": "1025",
        "PROTON_CALENDAR_SMTP_USER": "you@example.com"
      }
    }
  }
}
```

No `PROTON_CALENDAR_SMTP_PASSWORD` entry is needed once the token is in the keyring.

## Development

```sh
uv sync
uv run pytest
```
