# systemd

Systemd unit files for all platform services live here.

On the mini PC, unit files are deployed to `/etc/systemd/system/` and enabled with `systemctl enable`.

## Naming convention

All services are named `platform-<service-name>`. See STACK.md for the full registry.

| Unit file | Service | Port |
|---|---|---|
| platform-admin.service | Admin panel backend | 8000 |
| platform-conductor.service | Autocoder Conductor | 8001 |
| platform-re-agent.service | Autocoder RE-agent | 8002 |
| platform-chat.service | Chat app backend | 8010 |
| platform-writer.service | Writer app backend | 8011 |
| platform-coding.service | Coding assistant backend | 8012 |
| platform-chromadb.service | ChromaDB vector store | 8020 |

## Deploy a unit file

```bash
sudo cp systemd/platform-<name>.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable platform-<name>
sudo systemctl start platform-<name>
```

## Unit files are created alongside each service

Unit files are added to this directory as each service is built. See BUILD_SEQUENCE.md for the phase that builds each service.
