# 🏷️ Releasing & Dependency Updates (maintainers)

How code and dependency changes get from a commit to production, and what to check along the way. For running the bot, see the [Deployment Guide](deployment.md).

---

## Pipeline at a glance

```
PR ──► CI: lint · tests · Docker build ──► merge to main ──► CI again ──► publish :latest, :main, :sha-xxxxxxx
                                                    tag vX.Y.Z ──► CI ──► publish :X.Y.Z, :X.Y, :sha-xxxxxxx
```

- **Publishing is gated.** The `publish` job in `.github/workflows/ci.yml` only runs after `lint`, `test` and `docker-build` pass. A red check means no new image.
- **Every build gets an immutable `:sha-<commit>` tag**, which is what you roll back to.
- Pull requests never publish.

## Dependency model

| File | What it holds | Who edits it |
|---|---|---|
| `requirements.txt` | Direct dependencies with exact versions (discord.py, davey, PyNaCl, aiohttp, prometheus-client) | You or Renovate |
| `requirements.lock` | Every package incl. transitive ones, exact versions **and hashes**. The Docker image installs only this | Generated, never hand-edited |
| `requirements-ytdlp.txt` | `yt-dlp[default]`, deliberately **unpinned** | Rarely |
| `requirements-dev.txt` | Test/lint tools (pinned `pytest`, `pytest-asyncio`, `ruff`) | You or Renovate |

**Why yt-dlp floats:** YouTube breaks old yt-dlp versions within weeks. It's installed with `--pre` at build time, upgraded again by `entrypoint.sh` on every container start, and the bot restarts itself when idle to load new releases. See the [post-mortem](20261123-0300-playback-outage-postmortem/README.md).

**Why everything else is locked:** in Nov 2026 a loose transitive range (`davey>=0.1.0` from discord.py) pulled in davey 0.2.0 on a routine rebuild and silently broke all voice audio. With the lock, the same commit always builds the same image, and changes arrive only as reviewed PRs.

### Regenerating the lock after editing `requirements.txt`

Run it in the same base image the bot uses, so wheels and markers match:

```bash
docker run --rm -v "$PWD":/w -w /w python:3.12-alpine sh -c \
  "apk add -q gcc musl-dev libffi-dev && pip install -q pip-tools && \
   pip-compile --generate-hashes --allow-unsafe --strip-extras \
               --output-file=requirements.lock requirements.txt"
```

Commit `requirements.txt` and `requirements.lock` together.

### Local development

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check src/
```

## Renovate (automated update PRs)

`renovate.json` configures [Renovate](https://docs.renovatebot.com/) to open PRs **before 6am on Mondays** (America/Phoenix):

| PR group | Contents | What to do |
|---|---|---|
| **python dependencies** | Everything in the lock except the voice stack | Merge if CI is green |
| **voice stack** (`needs-voice-test` label) | discord.py, davey, PyNaCl | **Voice test first** (below), then merge |
| **github actions** | Workflow action versions | Merge if CI is green |
| Docker base image | `python:3.12-alpine` digest/patch (stays on 3.12) | Merge if CI is green |
| Lock file maintenance | Monthly refresh of transitive deps | Merge if CI is green |

yt-dlp and yt-dlp-ejs are excluded on purpose.

**One-time setup:** install the [Renovate GitHub App](https://github.com/apps/renovate) on `KeeperOfStack/notebane` (choose "Only select repositories"). Renovate opens an onboarding PR first; merge it and the weekly schedule starts.

### Voice test checklist (`needs-voice-test` PRs)

1. Build the PR branch and run it as the test bot (`docker compose -f docker-compose.test.yml up -d --build`).
2. `/play` a track in a voice channel. **Confirm you can hear it.**
3. `docker logs notebane-test 2>&1 | grep -E "DAVE not ready|retry|canary"`: there should be no `DAVE not ready`, and `canary PASS` about 2 minutes after start.
4. Only then merge.

## Cutting a versioned release

```bash
git checkout main && git pull
git tag -a v1.5.0 -m "v1.5.0"
git push origin v1.5.0
```

CI publishes `:1.5.0` and `:1.5`. Use [semver](https://semver.org/): bump the patch for fixes, the minor for features, the major for breaking config changes (renamed env vars, volume layout).

## Rolling back production

Find the last good image (a version tag, or a `:sha-xxxxxxx` from the [package page](https://github.com/KeeperOfStack/notebane/pkgs/container/notebane) or the CI run), point the container at it, and recreate:

```bash
# compose / Portainer: set  image: ghcr.io/keeperofstack/notebane:sha-51fbcda
docker compose up -d --force-recreate
```

Note that yt-dlp is still upgraded at container start even on an old image (set `YTDL_AUTO_UPDATE=0` to freeze it while debugging).
