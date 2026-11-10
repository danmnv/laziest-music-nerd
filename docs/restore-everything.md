# Поднять проект заново, если пропало всё

Это инструкция для Claude (и для тебя). Нужны три файла, которые бот каждое воскресенье присылает тебе в личку:

- `📦 laziest-music-nerd-ДАТА.bundle`: публичный репозиторий с кодом и его история;
- `🗂 laziest-music-nerd-data-ДАТА.bundle`: приватный репозиторий `laziest-music-nerd-data` с `data/` (обзоры, оценки, архив, описания) и его история;
- `🔐 d1-ДАТА.sql.gz.key.gpg`: данные людей из бота, зашифрованные ключом `BACKUP_KEY`.

**Чего в файлах нет и не должно быть: ключей и токенов.** Их нужно выпустить заново (список ниже) или взять из своего менеджера паролей.

## Что пропало и что делать

| Пропало | Что делать |
|---|---|
| Ошибка в данных людей за последние 7 дней | Только откат Time Travel (`docs/backup.md`) |
| База D1 удалена или испорчена давно | «Восстановить базу D1 из бэкапа», режим `live` (`docs/backup.md`) |
| Репозиторий удалён, а аккаунт GitHub цел | Шаги 1–4 ниже, в тот же аккаунт |
| Нет аккаунта GitHub и/или Cloudflare | Все шаги ниже, в новые аккаунты |

Бот и канал живут в Telegram. Они не пропадают вместе с GitHub или Cloudflare: после переустановки бот просто снова начинает отвечать.

## Шаги (Claude делает сам всё, кроме помеченного 👤)

1. 👤 Создать на GitHub пустой **публичный** репозиторий `laziest-music-nerd` и пустой **приватный** `laziest-music-nerd-data`, подключить оба к проекту Claude. Прислать Claude оба файла `.bundle`.
2. Claude: для каждого `git clone <файл>.bundle <папка>`, затем `git remote set-url origin <новый репозиторий>` и `git push origin main`.
   Если пришёл `.zip` (бандл стал больше 50 МБ), распаковать, `git init`, сделать коммит и запушить. Истории в этом случае не будет.
   Если поменялся логин GitHub, заменить `danmnv/laziest-music-nerd` по всему коду (`grep -rn danmnv lmn worker .github`) или задать переменную `DATA_REPO`.
3. 👤 Settings → Secrets and variables → Actions → **Secrets**. Добавить:

   | Секрет | Откуда взять |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | @BotFather → твой бот → API Token (можно Revoke и выпустить новый) |
   | `TELEGRAM_OWNER_ID` | твой Telegram ID (бот @userinfobot его покажет) |
   | `TELEGRAM_CHANNEL` | `@laziestmusicnerd` |
   | `YOUTUBE_API_KEY`, `GEMINI_API_KEY` | Google Cloud, проект «Laziest Music Nerd» → APIs & Services → Credentials; Gemini: aistudio.google.com → API keys |
   | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | dash.cloudflare.com → My Profile → API Tokens (шаблон «Edit Cloudflare Workers» + права D1 и Pages); Account ID справа на главной |
   | `BACKUP_KEY` | **тот же**, что был: из твоего менеджера паролей. Без него файл `🔐` не откроется |
   | `GROQ_API_KEY`, `MISTRAL_API_KEY`, `ODESLI_API_KEY` | только те, что были раньше; без них проект работает, просто без части описаний/ссылок |
   | `DATA_TOKEN` | github.com/settings/personal-access-tokens → Generate new token (fine-grained): только репозиторий `laziest-music-nerd-data`, Contents: Read and write. Им Actions читают и пишут данные |
   | `DATA_READ_TOKEN` | такой же токен, но Contents: Read-only. Его получает бот (Worker), чтобы читать `data/` |

   У обоих токенов данных есть срок. День, когда они кончаются, записан в `worker/wrangler.toml` (`DATA_TOKEN_EXPIRES`): за 30 дней бот начнёт напоминать владельцу в личку. После выпуска новых токенов поправь там дату.

   Вкладка **Variables**: `CLOUDFLARE_READY` = `1`, `WORKER_LIVE` = `1`, `SITE_LIVE` = `1`.
4. Claude запускает Actions по порядку:
   1. «Деплой Cloudflare Worker». Создаёт базу D1, Worker и webhook бота.
   2. Восстановление базы: Claude присылает файл `🔐` в Actions через поле «Telegram» в «Восстановить базу D1 из бэкапа», режим `live`. Код берётся из подписи к файлу. Работает, только если бот тот же (тот же токен или токен, перевыпущенный у того же бота).
   3. «Сайт». Собирает и выкладывает laziest-music-nerd.pages.dev. Если адрес занят, Cloudflare даст другой, и тогда его нужно поменять в `SITE_URL` (`worker/wrangler.toml`, `lmn/card.py`).
   4. «Проверка новых обзоров» в режиме `dry`, потом `run`.
5. 👤 Если адрес сайта поменялся: @BotFather → /setdomain → новый адрес (для входа через Telegram на сайте).

Проверка: бот отвечает на /start, твои отметки на месте, сайт открывается, а через час в канале появляется карточка нового обзора, если он вышел.
