# Update the Viewer

After pulling new changes to this repo, rebuild the Viewer:

```bash
cd ~/repos/literature-vault-system
git pull
./setup/install-viewer.sh
```

The scripts update automatically — the vault's `scripts/` symlink points into this repo, and the agent's container mounts the same repo read-only. No manual sync needed.

If you've changed `embed_server.py` or `embed_models.json`, reload the launchd service:

```bash
launchctl kickstart -k gui/$(id -u)/com.literature-vault.embed-server
```

If you've changed `agent/CLAUDE.local.md` or the container template, re-run `setup/install-agent.sh` to re-render the group, then force a fresh container:

```bash
docker ps | grep nano   # find your group's container
docker rm -f <id>       # next message spawns fresh
```
