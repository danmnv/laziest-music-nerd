// node worker/tools/pack-archive.mjs data/archive.json data/archive.min.json
// Writes the Worker's compact copy of the archive (worker/src/archive.mjs). Run by the check workflow before it saves
// the data, so the copy follows every change of archive.json within an hour, whoever made it. The file is rewritten
// only when its content changes, and a copy that doesn't read back as the same reviews is an error.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { pack, unpack, plain } from "../src/archive.mjs";

const [src, out] = process.argv.slice(2);
if (!src || !out) { console.error("usage: pack-archive.mjs <archive.json> <archive.min.json>"); process.exit(2); }
const raw = JSON.parse(readFileSync(src, "utf8"));
const text = JSON.stringify(pack(raw)) + "\n";
const back = unpack(JSON.parse(text));
const want = plain(raw).data;
if (!back || back.data.length !== want.length || back.data.some((a, i) => a.id !== want[i].id || a.album !== want[i].album)) {
  console.error("the packed archive doesn't read back as archive.json: not written");
  process.exit(1);
}
if (!existsSync(out) || readFileSync(out, "utf8") !== text) writeFileSync(out, text);
console.log(`archive.min.json: ${back.data.length} reviews, ${Math.round(text.length / 1024)} KB`);
