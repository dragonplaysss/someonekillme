# Shorekeeper Manual (Discord)

This is the **user manual** for people using Shorekeeper in Discord. (No hosting/setup info.)

## Command style

Most commands use mention syntax:

```text
@Shorekeeper [keyword] [@user] ; [reason/args]
```

Role commands can optionally include a reason after `|`:

```text
@Shorekeeper giverole @user ; RoleNameOrId | reason
@Shorekeeper removerole @user ; RoleNameOrId | reason
```

## Permissions (quick)

- **Admin**: Discord Administrator OR listed in bot `admin_roles`
- **Mod**: Admin OR listed in bot `mod_roles`
- **Owner IDs**: IDs in `owner_ids` (plus the main panel owner)

Check yourself:

- `@Shorekeeper whoami`

## Setup / configuration

See current settings:

- `@Shorekeeper config`

Open config panel (owner-only):

- `@Shorekeeper modpanel`

Common channel keys:

- `logging`
- `mod_logs`
- `welcome`
- `goodbye`
- `tickets`

## Moderation

- `@Shorekeeper kick @user ; reason`
- `@Shorekeeper ban @user ; reason`
- `@Shorekeeper unban @user_or_id ; reason`
- `@Shorekeeper mute @user ; reason` (supports duration in the main part like `10m`)
- `@Shorekeeper unmute @user ; reason`
- `@Shorekeeper warn @user ; reason`
- `@Shorekeeper warns [@user]`

Behavior:

- DMs the punished user with server/action/reason
- Logs to `mod_logs` (fallback: `logging`)

## Verify

- `@Shorekeeper verify @user ; optional reason`

Verify config keys:

- `verify_staff_roles`
- `verified_roles`
- `unverified_role`

## Nick lock (admin)

- `@Shorekeeper locknick @user ; New Nickname`
- `@Shorekeeper unlocknick @user ; reason`
- `@Shorekeeper nicklocks`

## Role tools (mod)

- `@Shorekeeper giverole @user ; RoleNameOrId | optional reason`
- `@Shorekeeper removerole @user ; RoleNameOrId | optional reason`

## Tickets

Send the panel:

- `/ticketpanel`

Anyone can open a ticket from the **Open Ticket** button.

### Ticket pings (helper roles)

To ping helper roles when a ticket is created:

- `@Shorekeeper modpanel` -> **Add Role**
- Type: `ticket_ping`
- Role ID: *(copy role ID from Discord)*

### Ticket commands (only work in ticket channels)

- `@Shorekeeper transcripttk` (archive transcript only)
- `@Shorekeeper closeticket` (archive transcript then delete channel)
- `@Shorekeeper deletetk` (delete without transcript; mod/owner only)

Where transcripts go:

- to `mod_logs` (fallback: `logging`) as a `.txt` attachment

## Welcome / Goodbye

Set channels:

- `/setupwelcome #channel`
- `/setupgoodbye #channel`

Set custom GIF/image per server:

- `/setwelcomegif <url>`
- `/setgoodbyegif <url>`

## Embed / Webhook tools (admin)

- `/embed` (modal: title/description/color/image/thumbnail)
- `/webhook` (creates a webhook and returns URL)

## Vibe / Leveling

- `@Shorekeeper vibe [@user]`

## Fun locks (admin + owner IDs)

These delete the user’s message and re-post via webhook using their name/avatar.

- `@Shorekeeper barklock @user ; reason`
- `@Shorekeeper unbarklock @user ; reason`
- `@Shorekeeper uwulock @user ; reason`
- `@Shorekeeper unuwulock @user ; reason`
- `@Shorekeeper lockstatus @user`

## Utilities

- `@Shorekeeper ping`
- `@Shorekeeper avatar [@user]`
- `@Shorekeeper userinfo [@user]`
- `@Shorekeeper serverinfo`
- `@Shorekeeper shorehelp`
