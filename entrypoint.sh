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

# Drop to notebane user and exec the bot
exec su-exec notebane python -m notebane
