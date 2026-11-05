// The owner's custom emoji pack t.me/addemoji/laziestmusicnerd (2026-11-03). Only in bot messages that have no
// channel counterpart: a bot can't post custom emoji to a channel (Bot API 9.4 allows private chats and groups when
// the bot's owner has Telegram Premium), and the cards must look the same in both places (owner's call).
// Ids from getStickerSet; the second value is the ordinary emoji shown when custom emoji are off.
export const EMOJI = {
  wave: ["5433666080830696116", "👋"],
  neutral: ["5426974410114376218", "🙂"],
  laugh: ["5427277845258874949", "😁"],
  wow: ["5427084653334932237", "😳"],
  sleepy: ["5424614677772545217", "💤"],
  facepalm: ["5426958591749844081", "🤦‍♂️"],
  love: ["5426883120584501626", "❤️"],
  think: ["5426915225465040108", "🤔"],
  shrug: ["5427279855303569184", "🤷"],
  kaif: ["5426999518493191919", "👌"],
  adore: ["5427302335162395715", "❤️"],
  banger: ["5427076385522887347", "🤘"],
  dislike: ["5427072185044875806", "👎"],
  turnoff: ["5425023940911213083", "👎"],
  cry: ["5427045440283521037", "🥹"],
};

// One emoji for an HTML message. CUSTOM_EMOJI = "0" in wrangler.toml turns them all into the ordinary ones
// (if the owner's Premium lapses).
export function ce(env, name) {
  const [id, plain] = EMOJI[name];
  return env.CUSTOM_EMOJI === "0" ? plain : `<tg-emoji emoji-id="${id}">${plain}</tg-emoji>`;
}

// The same text with every custom emoji replaced by its ordinary one: the retry when Telegram refuses them.
export function plainEmoji(html) {
  return String(html).replace(/<tg-emoji emoji-id="\d+">(.*?)<\/tg-emoji>/g, "$1");
}
