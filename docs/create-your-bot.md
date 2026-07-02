# 🤖 Creating Your Own Discord Bot

This guide walks you through creating a Discord bot application, getting your credentials, and adding the bot to your servers. It takes about 5 minutes.

---

## Step 1 — Create a Discord Application

1. Go to **[discord.com/developers/applications](https://discord.com/developers/applications)**

2. Click **New Application** (top-right)

3. Give it a name — this is your bot's display name (e.g. `Notebane`)

4. Accept the Terms of Service → click **Create**

---

## Step 2 — Create the Bot User

1. In the left sidebar, click **Bot**

2. Click **Add Bot** → confirm with **Yes, do it!**

3. Under **Privileged Gateway Intents**, enable:

   - ✅ **Server Members Intent**
   - ✅ **Message Content Intent**

   > These are required for the bot to function correctly.

4. Click **Save Changes**

---

## Step 3 — Get Your Bot Token

1. Still on the **Bot** page, click **Reset Token**

2. Confirm the prompt — your token will appear **once**

3. Click **Copy** and save it somewhere safe immediately

   > ⚠️ Treat your token like a password. Never share it or commit it to git. If it leaks, hit **Reset Token** again immediately.

---

## Step 4 — Get Your Application ID

1. In the left sidebar, click **General Information**

2. Copy the **Application ID** shown at the top

   > This is different from your bot token — you need both.

---

## Step 5 — Generate an Invite Link

1. In the left sidebar, click **OAuth2** → **URL Generator**

2. Under **Scopes**, check:
   - ✅ `bot`
   - ✅ `applications.commands`

3. Under **Bot Permissions**, check:
   - ✅ Connect
   - ✅ Speak
   - ✅ Send Messages
   - ✅ Embed Links
   - ✅ Read Message History
   - ✅ Use Slash Commands
   - ✅ Use Voice Activity

4. At the bottom, copy the **Generated URL**

---

## Step 6 — Add the Bot to Your Server

1. Paste the invite URL into your browser

2. Select the server you want to add the bot to from the dropdown

   > You must have **Manage Server** permission on that server.

3. Click **Authorise** → complete any CAPTCHA

4. The bot will appear in your server's member list as **offline** — that's expected until the container is running.

---

## Step 7 — Deploy Your Container

Now that you have your **Bot Token** and **Application ID**, head to the [Deployment Guide](deployment.md) and plug them into the `DISCORD_TOKEN` and `APPLICATION_ID` environment variables.

Once the container starts, the bot will come online and register all slash commands automatically. This takes a few seconds on first boot.

---

## Adding the Bot to More Servers

Repeat **Step 6** with the same invite URL for as many servers as you want. The same bot application supports multiple servers simultaneously — no extra setup needed.

---

## Troubleshooting

**Bot is online but slash commands aren't showing up**

Discord can take up to an hour to propagate global slash commands on first registration. Check the container logs for:
```
{"level": "INFO", "msg": "Synced 18 slash commands"}
```
If that line is missing, check that `APPLICATION_ID` is set correctly.

**`Invalid Token` error in logs**

Your `DISCORD_TOKEN` is wrong or expired. Go back to the Developer Portal → Bot → **Reset Token** and update your container's environment variable.

**Bot joins VC but plays no audio**

Make sure the bot has **Connect** and **Speak** permissions in that specific voice channel, not just the server level.
