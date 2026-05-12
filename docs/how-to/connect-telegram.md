# Connect a Telegram bot

The Librarian agent runs as a nanoclaw group bound to a Telegram bot. You need to create the bot once, give nanoclaw its token, and then install the Librarian on top.

The Telegram side is owned by [nanoclaw](https://github.com/henriasv/nanoclaw); this page only covers the parts specific to Literature Vault.

## Steps

1. Open Telegram and talk to [@BotFather](https://t.me/BotFather). Use `/newbot`. BotFather gives you a token like `1234567890:AAH…`.

2. Install nanoclaw if you haven't. Follow its README. Docker and an Anthropic API key are the main prerequisites.

3. Run nanoclaw's onboarding flow to pair your bot. nanoclaw will ask for the token and walk you through enabling the right Telegram privacy settings.

4. Sanity check: DM your bot from Telegram and verify nanoclaw replies.

5. Now [install the Librarian agent](install-the-librarian-agent.md) — that puts the literature-specific behavior on top of the bot.

## Other chat surfaces

nanoclaw supports Slack, Discord, iMessage, and others. The Librarian doesn't care — it talks to nanoclaw, not to Telegram directly. If you'd rather use Slack, pair Slack instead of Telegram in step 3 and the rest of the flow is the same.
