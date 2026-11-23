#!/bin/sh
# Entrypoint — runs as root, remaps notebane uid/gid to PUID/PGID,
# fixes volume ownership, then drops privileges and starts the bot.
set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

echo "Starting Notebane with UID=${PUID} GID=${PGID}"

# Remap the notebane group to PGID
if [ "$(id -g notebane)" != "${PGID}" ]; then
    groupmod -o -g "${PGID}" notebane
fi

# Remap the notebane user to PUID
if [ "$(id -u notebane)" != "${PUID}" ]; then
    usermod -o -u "${PUID}" notebane
fi

# Fix ownership of mounted volumes
chown -R notebane:notebane /cookies /data

# Upgrade yt-dlp to the newest nightly on every start. Runs as root because the
# bot user can't write to site-packages. Non-fatal: if PyPI is unreachable the
# bot starts on whatever version the image has. Disable with YTDL_AUTO_UPDATE=0.
case "${YTDL_AUTO_UPDATE:-1}" in
    0|false|no|off) echo "yt-dlp auto-update disabled" ;;
    *)
        echo "Updating yt-dlp..."
        if timeout 120 pip install --pre --upgrade --quiet --disable-pip-version-check                 --root-user-action=ignore "yt-dlp[default]"; then
            echo "yt-dlp $(python -c 'import yt_dlp; print(yt_dlp.version.__version__)')"
        else
            echo "WARNING: yt-dlp update failed — continuing with the bundled version"
        fi
        ;;
esac

# Drop to notebane user and exec the bot
exec su-exec notebane python -m notebane
