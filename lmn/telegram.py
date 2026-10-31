"""Minimal Telegram Bot API client."""
import json
import os
import urllib.error

from . import http


class Telegram:
    def __init__(self, token=None):
        self.token = token or os.environ["TELEGRAM_BOT_TOKEN"].strip()

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

    def send_photo_file(self, chat_id, data, caption, buttons=None):
        """Upload image bytes (multipart), so Telegram never has to fetch a slow third-party URL itself."""
        import uuid
        import urllib.request
        boundary = uuid.uuid4().hex
        fields = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
        if buttons:
            fields["reply_markup"] = json.dumps(_markup(buttons))
        body = b""
        for k, v in fields.items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="cover.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        body += data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/sendPhoto", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Telegram sendPhoto failed: {e.read()[:300]!r}") from None
        return res["result"]

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
