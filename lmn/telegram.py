"""Minimal Telegram Bot API client."""
import json
import os

from . import http


class Telegram:
    def __init__(self, token=None):
        self.token = token or os.environ["TELEGRAM_BOT_TOKEN"]

    def call(self, method, **params):
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            raw = http.request(f"https://api.telegram.org/bot{self.token}/{method}", json_body=payload)
        except http.HttpError as e:
            raise RuntimeError(f"Telegram {method} failed: {e.body[:300]}") from None
        res = json.loads(raw)
        if not res.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {res}")
        return res["result"]

    def send_photo(self, chat_id, photo, caption, buttons=None):
        return self.call("sendPhoto", chat_id=chat_id, photo=photo, caption=caption,
                         parse_mode="HTML", reply_markup=_markup(buttons))

    def send_message(self, chat_id, text, buttons=None, silent=False):
        return self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                         link_preview_options={"is_disabled": True},
                         disable_notification=silent or None, reply_markup=_markup(buttons))

    def edit_message(self, chat_id, message_id, text, buttons=None):
        try:
            return self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                             parse_mode="HTML", link_preview_options={"is_disabled": True},
                             reply_markup=_markup(buttons))
        except RuntimeError as e:
            if "message is not modified" in str(e):
                return None
            raise

    def pin(self, chat_id, message_id):
        return self.call("pinChatMessage", chat_id=chat_id, message_id=message_id, disable_notification=True)


def _markup(buttons):
    """buttons: list of rows; each row a list of dicts like {"text":..., "url":...} or {"text":..., "callback_data":...}."""
    if not buttons:
        return None
    return {"inline_keyboard": buttons}
