# telegram

Talk to duskcode from Telegram: your messages go to a thread, and the agent's answers,
questions and approval requests come back. The bot answers only the one Telegram user
who paired with it by the code `/plugins` shows.

1. Make a bot with @BotFather and copy its token.
2. Install telegram from Plugins, Workshop.
3. Type the token under Plugins (it is kept in memory for the session, never saved).
4. Send the bot the `/start` code that `/plugins` shows.

It may connect to `https://api.telegram.org` only. It reads the token itself, since its
bot library talks to Telegram directly. macOS only for now: Linux keeps plugins that need
the network off until they can be held to duskcode's broker.
