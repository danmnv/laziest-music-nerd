# Laziest Music Nerd

Неофициальный фан-проект. Не связан с Anthony Fantano и The Needle Drop. Оценки и обзоры — их; ссылки ведут на оригиналы.

Раз в час GitHub Actions проверяет новые обзоры на theneedledrop.com, собирает карточку (оценка, кто это, прошлые оценки Фантано, бриф на русском, ссылки на прослушивание) и публикует её в Telegram-канале [@lasiestmusicnerd](https://t.me/lasiestmusicnerd). Там же закреплён список обзоров за 60 дней.

## Как устроено

- `lmn/tnd.py` — обзоры из открытого API сайта TND, разбор оценки, типа релиза и жанров.
- `lmn/musicbrainz.py`, `lmn/links.py` — артист, длительность, обложка, ссылки (MusicBrainz, Cover Art Archive, Deezer, album.link).
- `lmn/gemini.py` — бриф, «кто это» и настроения через Gemini Flash.
- `lmn/card.py` — текст карточки и закреплённого списка.
- `lmn/check.py` — ежечасный запуск. `data/` — база в JSON, её коммитит сам бот.

## Запуск вручную

Actions → «Проверка новых обзоров» → Run workflow:

- `run` — как по расписанию;
- `test` — карточка свежего обзора только владельцу в личку, ничего не сохраняется;
- `dry` — ничего не отправляет, печатает карточки в лог.

Тесты: `python -m unittest discover -s tests`.
