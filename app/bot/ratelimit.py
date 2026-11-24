"""Rate limiting for calls that send messages only.

python-telegram-bot's AIORateLimiter counts every call that names a channel or
group against Telegram's 20-messages-a-minute group limit, including the
getChatMember membership check. With every user's check aimed at the same
channel, that would queue all users behind 20 checks a minute (and make a
1,000-user recap take ~50 minutes). Telegram's limits are on sending messages,
so only sending calls go through the limiter; everything else passes straight
through.
"""
from telegram.ext import AIORateLimiter

SENDING_PREFIXES = ("send", "copyMessage", "forwardMessage")


class SendRateLimiter(AIORateLimiter):
    async def process_request(self, callback, args, kwargs, endpoint, data, rate_limit_args):
        if not endpoint.startswith(SENDING_PREFIXES):
            return await callback(*args, **kwargs)
        return await super().process_request(callback, args, kwargs, endpoint, data, rate_limit_args)
