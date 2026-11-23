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
| `requirements.in` | Direct dependencies with exact versions (discord.py, davey, PyNaCl, aiohttp, prometheus-client) | You or Dependabot |
| `requirements.txt` | The lock: every package incl. transitive ones, exact versions **and hashes**, compiled from `requirements.in`. The Docker image installs only this | Generated (by you or Dependabot), never hand-edited |
| `requirements-ytdlp.txt` | `yt-dlp[default]`, deliberately **unpinned** | Rarely |
| `requirements-dev.txt` | Test/lint tools (pinned `pytest`, `pytest-asyncio`, `ruff`) | You or Dependabot |

**Why yt-dlp floats:** YouTube breaks old yt-dlp versions within weeks. It's installed with `--pre` at build time, upgraded again by `entrypoint.sh` on every container start, and the bot restarts itself when idle to load new releases. See the [post-mortem](20261123-0300-playback-outage-postmortem/README.md).

**Why everything else is locked:** in Nov 2026 a loose transitive range (`davey>=0.1.0` from discord.py) pulled in davey 0.2.0 on a routine rebuild and silently broke all voice audio. With the lock, the same commit always builds the same image, and changes arrive only as reviewed PRs.

### Regenerating the lock after editing `requirements.in`

Run it in the same base image the bot uses, so wheels and markers match:

```bash
docker run --rm -v "$PWD":/w -w /w python:3.12-alpine sh -c \
  "apk add -q gcc musl-dev libffi-dev && pip install -q pip-tools && \
   pip-compile --generate-hashes --allow-unsafe --strip-extras \
               --output-file=requirements.txt requirements.in"
```

Commit `requirements.in` and `requirements.txt` together.

### Local development

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check src/
```

## Dependabot (automated update PRs)

`.github/dependabot.yml` configures GitHub's built-in Dependabot. **No setup needed:** it's active as soon as the file is on `main`. Every **Monday ~6am (America/Phoenix)** it opens PRs:

| PR | Contents | What to do |
|---|---|---|
| **python-dependencies** group | Everything in the lock except the voice stack (bumps `requirements.in` and regenerates `requirements.txt` with hashes) | Merge if CI is green |
| **voice-stack** group (`needs-voice-test` label + checklist comment) | discord.py, davey, PyNaCl | **Voice test first** (below), then merge |
| **github-actions** group | Workflow action versions | Merge if CI is green |
| Docker base image | `python:3.12-alpine` patch updates only (stays on 3.12) | Merge if CI is green |

yt-dlp and yt-dlp-ejs are ignored on purpose. At most 5 Python PRs are open at once. Nothing merges automatically.

The `needs-voice-test` label and checklist come from `.github/workflows/dependabot-voice-label.yml`, because Dependabot can't label individual groups. That workflow only runs on Dependabot's own PRs and never checks out PR code.

**Managing it:**
- See status, last run and config errors: repo → **Insights → Dependency graph → Dependabot**.
- Don't want a particular update? Comment `@dependabot ignore this minor version` (or `major version` / `dependency`) on the PR.
- Re-run checks for a PR: comment `@dependabot rebase`.
- Pause everything: delete `.github/dependabot.yml`.

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
