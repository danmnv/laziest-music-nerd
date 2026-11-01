// Links that open a card in the private chat with the bot. Kept out of index.js: the Worker runtime reads the entry
// module's named exports as entrypoints, so index.js exports only its default handler.

// A card's button action ("a:<id>", "dz:<id>", "mb:<mbid>") as a link that opens it in the private chat:
// t.me/<bot>?start=a_<id>. Start parameters allow only A-Z, a-z, 0-9, _ and -, up to 64 characters.
export function startLink(env, open) {
  return `https://t.me/${env.BOT_USERNAME}?start=${open.replace(":", "_")}`;
}

export function openFromStart(text) {
  const m = /^\/start (a|dz|mb)_([A-Za-z0-9_-]{1,60})$/.exec(text);
  return m ? `${m[1]}:${m[2]}` : null;
}
