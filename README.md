# Laziest Music Nerd

Неофициальный проект. Не связан с Anthony Fantano и The Needle Drop. Оценки и обзоры — их; ссылки ведут на оригиналы.

Дважды в час GitHub Actions ищет новые обзоры Фантано (сначала на YouTube, потом на theneedledrop.com), собирает карточку (оценка, описание звучания на русском, критики, треклист, ссылки, где послушать) и публикует её в Telegram-канале [@laziestmusicnerd](https://t.me/laziestmusicnerd). Там же закреплены 30 последних обзоров. Бот ищет по всему архиву, а сайт laziest-music-nerd.pages.dev показывает каталог.

## Как устроено

- `lmn/tnd.py` — обзоры из открытого API сайта TND, разбор оценки, типа релиза и жанров.
- `lmn/musicbrainz.py`, `lmn/links.py` — артист, длительность, обложка, ссылки (MusicBrainz, Cover Art Archive, Deezer, album.link).
- `lmn/gemini.py` — описание и «Вайб для» через Gemini Flash.
- `lmn/card.py` — текст карточки и закреплённого списка.
- `worker/` — бот (Cloudflare Worker): кнопки, поиск, отметки, вход на сайт. `lmn/site.py` и `site_src/` — сайт.
- `lmn/check.py` — запуск дважды в час. База в JSON (`data/`) лежит в отдельном приватном репозитории: Actions забирают её токеном `DATA_TOKEN` и коммитят туда же, бот читает её токеном `DATA_READ_TOKEN`. Код открыт, собранные базы — нет.

## Запуск вручную

Actions → «Проверка новых обзоров» → Run workflow:

- `run` — как по расписанию;
- `test` — карточка свежего обзора только владельцу в личку, ничего не сохраняется;
- `dry` — ничего не отправляет, печатает карточки в лог.

Тесты: `python -m unittest discover -s tests`.

## Бэкап

Данные людей из бота (подписки, отметки, оценки, голоса) живут в Cloudflare D1. Каждый день — зашифрованный бэкап на 90 дней, плюс Time Travel на 7 дней. Как откатить и восстановить: [docs/backup.md](docs/backup.md). Раз в неделю бот присылает владельцу оба репозитория и бэкап базы в Telegram; как поднять всё заново с нуля: [docs/restore-everything.md](docs/restore-everything.md).
