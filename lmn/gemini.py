"""Gemini Flash: Russian brief, 'who is this', mood guesses. Returns None on any failure (empty field beats broken pipeline)."""
import json
import os
import re
import time

from . import http

# The free tier has a daily request limit per model ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", seen
# 2026-10-31), so when one model's day is used up the next one in this list is tried. Any of them writes the brief well.
# gemini-2.5-flash is not here: it is closed to new API keys (HTTP 404 "no longer available to new users").
MODELS = [m.strip() for m in (os.environ.get("GEMINI_MODEL") or
                              "gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash,gemini-3.5-flash-lite").split(",") if m.strip()]
MODEL = MODELS[0]
BUDGET_SEC = 300      # per review, all models and retries together, so a slow day can't eat the hourly run
CALL_TIMEOUT = 150
# Watching a video is the slow request (~45k tokens): it gets longer (owner, 2026-11-02: a request we stop waiting for
# is likely still counted against the daily limit, and its answer is lost). 90 s timed out three times on 2026-11-02.
# The owner (2026-11-02): three times that, "нам особо некуда торопиться". The review's whole budget is 20 min, not 27,
# so the hourly job ends before its step timeout (check.yml).
VIDEO_BUDGET_SEC = 1200
VIDEO_CALL_TIMEOUT = 810
ABOUT_MAX = 760   # the site's longer brief ("about"); the prompt asks for 700
BRIEF_MAX = 330   # the card's short brief; the prompts ask for 240 (Gemini) and 270 (archive): room for a longer third
# sentence, so a brief isn't cut to two (owner, 2026-11-04: "чтобы ничего не терялось и мысли были законченные")
# The stored mood words; the same list and order as MOODS in worker/src/index.js (buttons carry the index, votes the
# words). Words are only appended, never removed or reordered: old votes, guesses and buttons keep pointing at them.
MOODS = ["для тренировки", "для настроения", "для работы за столом", "для тусовки", "в дорогу", "на прогулку", "ночью",
         "перед сном", "когда грустно", "когда злишься", "в наушниках, вдумчиво", "фоном", "для романтики", "для бодрости",
         "фоном для работы"]
# «Вайб для» since 2026-11-02 (the owner: «изменим когда слушать кнопку на кнопку Вайб для», «когда слушать на время
# намекает»): the moods offered and shown, in this order, as the words after «Вайб для». The owner the same evening:
# «для настроения конечно убрать», «для работы за столом и фоном объединить … отлично ложится инструментальная или
# какая-то монотонная но жёсткая музыка», «для ночи не надо», «для бодрости тоже не надо, уже покрыто тренировкой».
# The same in worker/src/index.js VIBES and site_src/app.js VIBES (a test keeps them equal).
VIBES = {"для тренировки": "тренировки", "фоном для работы": "фона за работой", "для тусовки": "тусовки",
         "в дорогу": "дороги", "на прогулку": "прогулки", "перед сном": "сна", "когда грустно": "грусти",
         "когда злишься": "злости", "в наушниках, вдумчиво": "вдумчивого слушания", "для романтики": "романтики"}
# old words that now count as one of VIBES (their guesses and votes go there); any other word not in VIBES is hidden
MOOD_ALIAS = {"для работы за столом": "фоном для работы", "фоном": "фоном для работы"}
AI_MOODS = list(VIBES)


def shown_moods(moods):
    """Stored words → the ones shown now: old words merged, retired ones dropped, no repeats; order kept."""
    out = []
    for m in moods or []:
        m = MOOD_ALIAS.get(m, m)
        if m in VIBES and m not in out:
            out.append(m)
    return out


def vibe(mood):
    """A stored mood as shown after «Вайб для»: «в дорогу» → «дороги»."""
    m = MOOD_ALIAS.get(mood, mood)
    return VIBES.get(m, m)


_unavailable = set()  # models found used up for today (or closed) during this run: skipped for the next reviews

PROMPT = """Ты помогаешь вести русскоязычный Telegram-канал о музыкальных обзорах Anthony Fantano (The Needle Drop).
{source} Ответь строго JSON-объектом с полями:
- "brief": ровно 3 коротких предложения на русском, своими словами, о том, что Фантано думает о релизе: как он звучит (звучание, продакшн, вокал, настроение) и что в нём обращает на себя внимание — сильные и слабые стороны, или только сильные, или только слабые, смотря что говорит обзор. Выбирай то, что даёт слушателю контекст или может его заинтересовать; не придумывай недостатки или достоинства, о которых в обзоре нет. Не пиши, кто исполнитель, откуда он, в каком жанре и какой это по счёту релиз: всё это уже есть в карточке строками выше. Без оценки: она уже стоит в заголовке карточки, не повторяй её. Не цитируй обзор, не переводи его дословно. До 240 символов. Слова light, decent, strong не переводи и не используй.
- "about": 4–5 предложений на русском, своими словами, для страницы сайта: как звучит релиз, что Фантано в нём хвалит (с названиями треков), что ругает и к чему пришёл — тоже без оценки. Не начинай с того, кто исполнитель, в каком жанре и какой это по счёту релиз: это уже есть на странице. Не цитируй обзор, не переводи его дословно. До 700 символов.
- "who": одна строка на русском строго по образцу «Ирландская пост-панк-группа из Дублина; пятый альбом.» или «Рэпер из Атланты, участник Migos; третий сольный альбом.»: откуда, жанр, кто (группа, рэпер, певица, продюсер), чей участник, если это важно; после точки с запятой — какой это релиз. Без имени исполнителя и названия релиза, без оценочных слов. Только факты из текста; чего нет в тексте — пропусти, но известную часть пиши («Психоделический хип-хоп-проект; восьмой альбом.»); не пиши «новый альбом» и не угадывай, какой это по счёту релиз. Пустая строка — только если в тексте об этом ничего нет. До 120 символов.
- "moods": список из 1–2 вариантов ровно из этого набора: {moods}. Для чего лучше всего подходит этот релиз: исходи из жанра, звучания и настроения, которые описывает обзор (тихий и грустный — не «для тусовки»). «Фоном для работы» — инструментальная или монотонная музыка, которая не отвлекает, в том числе жёсткая. «В наушниках, вдумчиво» — только если обзор подчёркивает плотную, детальную, требующую внимания музыку, а не по умолчанию; слабому альбому тоже выбирай то, к чему подходит его звучание.
- "best_tracks": до 3 названий треков, которые Фантано выделил как лучшие, точно как они написаны в тексте. Если не выделил — пустой список.
- "artist": имя исполнителя как в оригинале.
- "album": название релиза как в оригинале.
- "score_note": если Фантано назвал оценку вместе со словом light, decent или strong (например «a strong 7» или «light to decent 6»), это слово или пара слов по-английски строчными буквами; иначе пустая строка.
Названия альбомов, треков и жанров оставляй в оригинале.

Заголовок: {title}
{text}"""
SOURCE_TEXT = "Ниже — расшифровка его видеообзора."

# The same answer in English, for models that write Russian poorly (lmn/llm.py); translate() then makes it Russian.
PROMPT_EN = """You help run a Russian-language Telegram channel about Anthony Fantano's (The Needle Drop) music reviews.
Below is the transcript of his video review. {verdict} Answer with a JSON object only, with the fields:
- "brief": exactly 3 short sentences in English, in your own words, on what Fantano thinks of the release: how it sounds (sound, production, vocals, mood) and what stands out: strengths and weaknesses, or only strengths, or only weaknesses, as the review has it. Pick what gives a listener context or could catch their interest; don't invent strengths or weaknesses the review doesn't mention. Don't say who the artist is, where from, the genre or which release this is: the card shows all that in the lines above. Never state the score or verdict: the card shows it right above, a repeat is noise. Don't quote the review. Up to 220 characters.
- "about": 4-5 sentences in English, in your own words, for the website: how the release sounds, what Fantano praises (name the tracks), what he criticizes and where he lands, again without the score. Don't open with who the artist is, the genre or which release this is: the page shows that already. Don't quote the review. Up to 650 characters.
- "who": one line in English, strictly in the pattern "Irish post-punk band from Dublin; fifth album." or "Atlanta rapper, member of Migos; third solo album.": where from, genre, what (band, rapper, singer, producer), whose member if it matters; after the semicolon, which release this is. No artist name, no release title, no opinions. Only facts from the text; leave out what the text doesn't say, but write the part that is known (genre and what, or which release: "Psychedelic hip-hop project; eighth album."); never "new album"; never guess which release it is. An empty string only if the text says nothing of it. Up to 110 characters.
- "moods": a list of 1-2 items copied exactly from this list: {moods}. What this release suits best, judging by the genre, sound and mood the review describes (quiet and sad is not "для тусовки"). "фоном для работы" is instrumental or monotonous music that doesn't distract, heavy music included. "в наушниках, вдумчиво" only when the review stresses dense, detailed, demanding music, never as a default; a bad record still gets what its sound fits.
- "best_tracks": up to 3 track titles Fantano singled out as the best, exactly as written in the text; else an empty list.
- "artist": the artist's name as in the original.
- "album": the release title as in the original.
- "score_note": if Fantano gave the score with light, decent or strong (e.g. "a strong 7", "light to decent 6"), that word or pair in lowercase; else an empty string.
Keep album, track and genre names in the original.
Title: {title}
Transcript:
{text}"""

# The same fields written in Russian straight from the English text, for paid models that write Russian well (Selectel's
# router, lmn/llm.py): the verdict and the translation's style rules in one prompt, so no Gemini translation is needed.
PROMPT_RU = """Ты помогаешь вести русскоязычный Telegram-канал о музыкальных обзорах Anthony Fantano (The Needle Drop).
Ниже — текст его обзора на английском. {verdict} Ответь строго JSON-объектом с полями:
- "brief": ровно 3 коротких предложения на русском, своими словами, о релизе целиком: как он звучит (звучание, продакшн, вокал, настроение), чего от него ждать и в чём его сильные и слабые стороны, или только сильные, или только слабые, смотря что говорит обзор. Выбирай то, что даёт слушателю контекст, может его заинтересовать и помогает понять, что это за музыка и чего ждать от звучания; не придумывай достоинства или недостатки, о которых в обзоре нет. Отдельные треки не называй; исключение — один трек, который резко выделяется на фоне остального (например, единственный удачный). Не называй исполнителя и релиз, не пиши, откуда исполнитель и какой это по счёту релиз: карточка показывает это строками выше; жанры упоминай только чтобы описать звучание этого релиза. Если релиз инструментальный, скажи об этом. Не цитируй обзор и не переводи его дословно. До 270 символов.
- "about": 4–5 предложений на русском, своими словами, для страницы сайта: как звучит релиз, что Фантано хвалит (с названиями треков), что ругает и к чему пришёл — тоже без оценки. Не начинай с имени исполнителя, названия релиза, жанра и того, какой это по счёту релиз: это уже есть на странице. До 700 символов.
- "who": одна строка на русском строго по образцу «Ирландская пост-панк-группа из Дублина; пятый альбом.», «Рэпер из Атланты, участник Migos; третий сольный альбом.» или «Психоделический хип-хоп-проект; мини-альбом.». До точки с запятой — кто исполнитель: откуда, чем известен в целом (жанр, которым он известен, а не жанр этого релиза; если обзор говорит о смене жанра — прежний), кто это (группа, рэпер, певица, продюсер), чей участник, если это важно. После точки с запятой — только какой это по счёту релиз и его тип, без описания содержания. Если номер неизвестен: у мини-альбома, микстейпа, сборника, концертного альбома пиши только тип («; мини-альбом.»), а у обычного альбома часть после точки с запятой опусти. Без имени исполнителя и названия релиза, без оценочных слов. Факты бери из текста обзора и из тегов сайта (строка «Теги» ниже, если она есть: в ней бывают не только жанры и места, но и лейблы, рубрики, имена — их не используй). Если там об исполнителе почти ничего нет, а исполнитель широко известен, допиши общеизвестное, в чём уверен: кто это, откуда, чем известен. О малоизвестном исполнителе не угадывай. Пустая строка — только если об исполнителе ничего не известно. До 150 символов.
{en}- "moods": список из 1–2 вариантов ровно из этого набора: {moods}. Для чего лучше всего подходит этот релиз: исходи из жанра, звучания и настроения, которые описывает обзор (тихий и грустный — не «для тусовки»). «фоном для работы» — инструментальная или монотонная музыка, которая не отвлекает, в том числе жёсткая. «в наушниках, вдумчиво» — только если обзор подчёркивает плотную, детальную, требующую внимания музыку, а не по умолчанию; слабому альбому тоже выбирай то, к чему подходит его звучание.
Как писать: естественным, грамотным русским языком, как музыкальный журналист, без кальки с английского и без сленга («выкатил», «залетел»). Названия альбомов и треков, имена людей и названия групп — в оригинале латиницей, без транслитерации; названия треков — в кавычках-«ёлочках». Жанры — по-русски, если у жанра есть привычное русское название (хип-хоп, пост-панк, индастриал-метал, синти-фанк, кантри); латиницей — только если его нет. Фамилию пиши «Фантано». Слова light, decent, strong не переводи и не используй.
Заголовок: {title}
{tags}Текст обзора:
{text}"""
# PROMPT_RU's "en" field: the same three texts in English, kept for an English version of the bot and site (owner,
# 2026-11-03), written in the same request so no translation is needed either way
EN_FIELD = """- "en": объект с полями "brief", "about", "who" — те же три текста на естественном английском, для англоязычной версии: те же правила, без оценки, до 250, 650 и 140 символов; "who" по образцу "Irish post-punk band from Dublin; fifth album.". Пиши их не переводом русских, а так, как написал бы англоязычный музыкальный журналист.
"""

TRANSLATE = """Переведи на русский тексты для русскоязычного канала о музыкальных обзорах Anthony Fantano. Пиши естественным,
грамотным русским языком, как музыкальный журналист, а не дословно. Названия альбомов и треков, имена людей и названия групп
оставляй в оригинале латиницей, без транслитерации. Жанры пиши по-русски, если у жанра есть привычное русское название
(хип-хоп, пост-панк, индастриал-метал, синти-фанк, кантри); латиницей — только если его нет. Названия треков бери в
кавычки-«ёлочки». Оценки пиши как в оригинале («7/10», «NOT GOOD», «CLASSIC»); слова light, decent, strong не переводи и
не используй. Фамилию Fantano пиши «Фантано». Без сленга («выкатил», «залетел»). Ответь строго JSON-списком той же длины и
в том же порядке, где у каждого элемента те же поля "brief", "about", "who" по-русски. "who" сохраняет образец
оригинала: «Ирландская пост-панк-группа из Дублина; пятый альбом.»
{items}"""


def translate(items, api_key=None):
    """English brief/about/who dicts -> the same list in Russian, in one Gemini request (its limit counts requests,
    not words); None on any failure or a list of another length."""
    api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key or not items:
        return None
    src = [{k: (x.get(k) or "") for k in ("brief", "about", "who")} for x in items]
    body = {"contents": [{"parts": [{"text": TRANSLATE.format(items=json.dumps(src, ensure_ascii=False, indent=1))}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}}
    model, raw = generate(body, api_key, budget=300)
    if raw is None:
        return None
    try:
        out = json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])
        if not isinstance(out, list) or len(out) != len(src) or not all(isinstance(x, dict) for x in out):
            raise ValueError("not a list of the same length")
        return [{"brief": trim_brief(drop_score(str(x.get("brief") or ""))), "about": trim_about(drop_score(str(x.get("about") or ""))),
                 "who": str(x.get("who") or "").strip(), "tr": model} for x in out]
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        print(f"gemini {model}: bad translation {e!r}")
        return None
SOURCE_VIDEO = "Выше — сам его видеообзор на YouTube; ниже — описание видео."
NOTE = re.compile(r"^(?:light|decent|strong)(?: to (?:light|decent|strong))?$")


last_sec = None  # how long the answer that generate() returned took, for the average (stored with the brief)


def generate(body, api_key, budget=BUDGET_SEC, sleep=time.sleep, clock=time.monotonic, call_timeout=CALL_TIMEOUT):
    """POST generateContent, walking down MODELS. Returns (model, response) or (None, None)."""
    global last_sec
    last_sec = None
    deadline = clock() + budget
    for model in MODELS:
        if model in _unavailable:
            continue
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            left = deadline - clock()
            if left < 15:
                print("gemini: time budget for this review used up")
                return None, None
            t0 = clock()
            try:
                out = http.get_json(url, json_body=body, method="POST", headers={"x-goog-api-key": api_key},
                                    timeout=min(call_timeout, left), retries=0)
                last_sec = round(clock() - t0)
                print(f"gemini {model}: answered in {last_sec} s")
                return model, out
            except http.HttpError as e:
                print(f"gemini {model}: HTTP {e.status} {_reason(e.body)} after {round(clock() - t0)} s")
                if e.status == 404 or (e.status == 429 and "PerDay" in e.body):
                    _unavailable.add(model)  # closed to this key, or today's limit is gone: next model right away
                    break
                if e.status not in (0, 429, 500, 502, 503, 504):  # a bad key or request: no other model will do better
                    return None, None
                if e.status in (0, 504):  # no answer in time (ours or Google's own deadline): waiting again on the same model
                    break          # (2026-11-02: 3.8 twice and 3.7 timed out, 3.5 was never tried); the next model now
                wait = 30 if "PerMinute" in e.body else 10
                if attempt == 0 and deadline - clock() > wait + 15:  # timeout, overload or per-minute limit:
                    sleep(wait)                                       # one more try a bit later, then the next model
    print("gemini: no model answered")
    return None, None


def summarize(title, text=None, api_key=None, video_id=None, notes=""):
    """From the transcript (text) or, when there is none yet, from the video itself (video_id; notes = its description)."""
    api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key or not (text or video_id):
        return None
    moods = json.dumps(AI_MOODS, ensure_ascii=False)
    if text:
        parts = [{"text": PROMPT.format(source=SOURCE_TEXT, moods=moods, title=title, text="\nТекст обзора:\n" + text[:30000])}]
        config = {}
    else:
        parts = [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={video_id}"}},
                 {"text": PROMPT.format(source=SOURCE_VIDEO, moods=moods, title=title, text="\nОписание видео:\n" + (notes or "")[:3000])}]
        config = {"mediaResolution": "MEDIA_RESOLUTION_LOW"}  # ~45k tokens for a 8-minute review instead of ~130k
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4, **config}}
    model, raw = generate(body, api_key, **({} if text else {"budget": VIDEO_BUDGET_SEC, "call_timeout": VIDEO_CALL_TIMEOUT}))
    if raw is None:
        return None
    try:
        out = parse_answer(raw["candidates"][0]["content"]["parts"][0]["text"])
        out.update(m=model, sec=last_sec, src="text" if text else "video")  # for the average time (owner, 2026-11-02)
        return out
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        print(f"gemini {model}: bad response {e!r}")
        return None


def parse_answer(text):
    """The model's JSON answer to PROMPT, checked (also used for lmn/mistral.py). Raises ValueError on a bad answer."""
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text)  # some models wrap the JSON in a code fence
    out = json.loads(text)
    if isinstance(out, list):  # gemini-3.5-flash sometimes wraps the object in a list (seen 2026-10-31 on HMLTD)
        out = next((x for x in out if isinstance(x, dict)), None)
    if not isinstance(out, dict):
        raise ValueError(f"expected a JSON object, got {type(out).__name__}")
    out["moods"] = shown_moods(out.get("moods"))[:2]
    note = str(out.get("score_note") or "").strip().lower()
    out["score_note"] = note if NOTE.match(note) else None
    out["brief"] = trim_brief(drop_score(str(out.get("brief") or ""))) or None
    out["about"] = trim_about(drop_score(str(out.get("about") or ""))) or None
    en = out.get("en") if isinstance(out.get("en"), dict) else {}
    out["en"] = {k: drop_score(str(en.get(k) or "")).strip() for k in ("brief", "about", "who") if str(en.get(k) or "").strip()} or None
    return out


SCORE = r"(?:\d{1,2}(?:[.,]\d)?\s*/\s*10|NOT GOOD|NOT BAD|NOT MUSIC|CLASSIC)"
_VERB = (r"(?:ставит|оценива\w*|оценил\w*|постави\w*|получа\w*|получил\w*|выставля\w*|дал\w*|даёт|дает|считает|называет|"
         r"gives?|gave|rates?|rated|rating|awards?|awarding|earn\w*|scor\w*|giving|calls?)")
_VERB_RE = re.compile(r"\b" + _VERB + r"\b", re.I)
# what may stand before the verb in that clause: ", и Фантано", "; в итоге он", " that earns", " однако Фантано"
_LEAD = re.compile(r"(?:\s*[,;—–-])?\s*(?:(?:и|а|но|однако|что|and|but|that|which)\s+)?(?:(?:в итоге|в целом)\s+)?(?:(?:Фантано|Fantano|он|he)\s+)?$", re.I)


def _cut_score_clause(body):
    """body without its trailing clause that only gives the score ("…, и ставит 4/10", "…, получая оценку 6/10"), or
    body itself. The clause starts at the last verb before the score, so "считает его безликим и ставит 4/10" keeps
    "считает его безликим"."""
    for m in reversed(list(_VERB_RE.finditer(body))):
        rest = body[m.start():]
        if re.fullmatch(r"[^.;,!?]*?" + SCORE + r"[^.;,!?]*", rest, re.I):
            lead = _LEAD.search(body[:m.start()])
            return body[:lead.start() if lead else m.start()]
        if re.search(SCORE, rest) is None:
            break
    return body


def drop_score(text):
    """The text without the score: the card and the page show it in their first lines, so a brief that ends "…и ставит
    4/10" repeats it (owner, 2026-11-01). The prompts say so too; this catches what a model still writes. A trailing
    score clause is cut; a sentence led by the score is dropped when other sentences remain; else the text stays."""
    if not text or not re.search(SCORE, text):
        return text
    parts = re.split(r"(?<=[.!?])(?<![A-Z]\.[A-Z]\.)\s+(?=[«\"A-ZА-ЯЁ])", text.strip())  # not after "D.C." before a lowercase word
    out = []
    for s in parts:
        if not re.search(SCORE, s):
            out.append(s)
            continue
        body = s.rstrip(".!? ")
        cut = _cut_score_clause(body)
        if cut != body and len(cut) >= 25:
            out.append(cut.rstrip(" ,;—–-") + ".")
        elif len(parts) == 1:
            out.append(s)
    return " ".join(out).strip() or text


def trim_brief(brief):
    """Too long for the card: the whole sentences that fit, if at least two remain; else as it is (the caption's own
    trim handles it). The brief is 3 sentences on the sound, strengths and weaknesses, so one alone says too little."""
    brief = brief.strip()
    if len(brief) > BRIEF_MAX:
        cut = brief[:BRIEF_MAX]
        cut = cut[:cut.rfind(". ") + 1] if ". " in cut else ""
        if cut.count(". ") >= 1:  # two sentences or more
            brief = cut
    return brief


def trim_about(about):
    """The site's brief cut at the last full sentence that fits."""
    about = about.strip()
    if len(about) > ABOUT_MAX:
        cut = about[:ABOUT_MAX]
        about = cut[:cut.rfind(". ") + 1] if ". " in cut else cut.rstrip() + "…"
    return about


def _reason(body):
    """Google's error message (says e.g. which quota ran out and its size). Contains no key."""
    try:
        err = json.loads(body)["error"]
        quota = [f"{v['quotaId']}={v.get('quotaValue', '?')}" for d in err.get("details", [])
                 for v in d.get("violations", []) if v.get("quotaId")]
        return (err.get("message") or "")[:200] + (f" quota={quota}" if quota else "")
    except Exception:
        return (body or "")[:200]
