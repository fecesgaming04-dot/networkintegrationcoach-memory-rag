# Security

This project is designed for local-only development. Default services bind to `127.0.0.1`.

## Do Not Commit

- AnythingLLM `storage`.
- LanceDB table files.
- Memory tables.
- Generated JSONL datasets if they include personal details.
- Logs.
- Slot-state files.
- `.env` files.

## Network Exposure

Do not expose these ports directly to a LAN or the internet:

- `11434`
- `3001`
- `8080`
- `8081`

If remote access is needed, put authentication and transport security in front of the services.

## Reporting Issues

Before sharing logs, review them for:

- local paths,
- device serials,
- phone IPs,
- usernames,
- file names,
- prompt or memory content.
