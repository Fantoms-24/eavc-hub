# web_portal (EAVC)

Flask-портал для работы с перехватами, анализом, сессиями и смежными модулями.
Поставляется двумя способами: как центральный **SERVER** и как офлайн **HUB** (оба
собираются в `.exe` через PyInstaller). Отдельно есть приёмник Telegram (`TG_RECEIVER`).

---

## Быстрый старт (разработка)

```bash
# 1. Виртуальное окружение
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Зависимости
pip install -r requirements.txt

# 3. Конфиг: скопируйте нужный пример из config/ в корень и заполните
cp config/server_config.example.json server_config.json    # для SERVER
# или
cp config/hub_config.example.json    hub_config.json       # для HUB

# 4. Запуск
python server_main.py     # центральный сервер
python hub_main.py        # офлайн-хаб
```

> Рантайм ищет реальные `*_config.json` (без `.example`) рядом с точкой входа /
> исполняемым файлом. Файлы в `config/` — это **шаблоны**, их коммитим; заполненные
> `*_config.json` в `.gitignore`.

---

## Структура проекта

```
web_portal/
├── README.md                  ← вы здесь
├── AGENTS.md / CLAUDE.md      ← инструкции для AI-ассистентов (GitNexus)
│
├── Точки входа (запускаются напрямую / собираются в .exe)
│   ├── server_main.py         Центральный сервер (data-central/)
│   ├── hub_main.py            Офлайн-хаб (data-hub/)
│   ├── telegram_receiver_main.py   Приёмник Telegram → перехваты
│   ├── jobs_worker.py         Фоновый воркер задач
│   └── seans_watch_child.py   Отдельный процесс автопоиска сеансов
│
├── Ядро приложения
│   ├── app.py                 Фабрика Flask-приложения create_app()
│   ├── config.py              Пути к данным (SQLite/JSON), выбор data_dir
│   ├── positions.py           Позиции пользователя (сессия + БД портала)
│   ├── app_perf.py            Перф-метрики по endpoint'ам
│   └── app_runtime_caches.py  In-memory кэши и состояние прослушивания аудио
│
├── webapp/                    HTTP-слой: маршруты по доменам
│   ├── context.py             AppContext — единый DI для register_*_routes
│   ├── routes/                register(app, ctx) на каждый домен:
│   │   ├── intercepts.py        перехваты / аудио
│   │   ├── analysis.py          анализ
│   │   ├── admin.py             администрирование
│   │   ├── sessions.py          сессии
│   │   ├── online_search.py     онлайн-поиск
│   │   ├── aviation.py          авиация
│   │   ├── chat.py              оператор-чат (AI)
│   │   ├── crypto.py            крипто-модуль
│   │   ├── auth_pages.py        login / logout
│   │   ├── shell.py             вкладки, set-position, pick-folder
│   │   ├── jobs.py              export-jobs / AI analyze
│   │   ├── sync_api.py          /api/sync/*
│   │   └── misc.py              health, databases, targeting
│   ├── auth.py                авторизация / права доступа
│   ├── security.py            безопасность запросов
│   ├── httputils.py           JSON/ETag-хелперы ответа
│   ├── timeutils.py           работа со временем
│   ├── network_analysis.py    графы связей
│   └── online_search_filters.py
│
├── application/               Бизнес-логика (без Flask)
│   ├── intercepts/            эталон: DOCX, каталоги, позывные, AI-вычитка
│   ├── sessions/              избранное, folder-import, параметры экспорта
│   └── analysis/              assignments, stats rows, period bounds, network-order
│
├── lib/                       Переиспользуемые библиотеки/сервисы
│   ├── db/                    доступ к БД (пакет + доменные модули)
│   │   ├── sync.py ai.py      физически вынесены
│   │   ├── connection/seans/intercepts/…  фасады → _impl
│   │   └── _impl.py           остальная реализация (распил продолжается)
│   ├── auth_db.py             портальная БД / пользователи
│   ├── sync_agent.py          синхронизация SERVER ↔ HUB
│   ├── word_push.py           отправка в «Парсер WORD»
│   ├── asr/                   распознавание речи (ASR)
│   └── ml/                    ML-модели (обучение / предсказание)
│
├── templates/                 Jinja2-шаблоны (16 шт.)
├── static/                    Статика
│   ├── css/  js/  images/
│   └── vendor/                офлайн Bootstrap + иконки (скачиваются при сборке)
│
├── config/                    ШАБЛОНЫ конфигов (*.example.json)
│   ├── server_config.example.json
│   ├── hub_config.example.json
│   ├── telegram_receiver_config.example.json
│   └── word_push_config.example.json
│
├── requirements/              Наборы зависимостей под варианты сборки
│   ├── hub.txt
│   ├── pg.txt                 (PostgreSQL)
│   └── tg-receiver.txt
│   └── (базовый requirements.txt — в корне)
│
├── packaging/                 Всё для сборки .exe (PyInstaller)
│   ├── server.spec  hub.spec  telegram_receiver.spec  TG_RECEIVER.spec
│   ├── BUILD_SERVER_EXE.bat   BUILD_HUB_EXE.bat   BUILD_TG_RECEIVER_EXE.bat
│   └── icon.ico
│
├── docs/                      Документация (ТЗ, описание, operator-ai-chat …)
└── tests/                     pytest: lib-модули + HTTP smoke + снимок маршрутов
```

---

## Сборка .exe

Bat-скрипты в `packaging/` сами переходят в корень проекта, поэтому запускать их
можно как из корня, так и из папки `packaging/`:

```bat
packaging\BUILD_SERVER_EXE.bat        REM → dist\EAVC - SERVER\EAVC - SERVER.exe
packaging\BUILD_HUB_EXE.bat           REM → dist\EAVC - HUB\EAVC - HUB.exe
packaging\BUILD_TG_RECEIVER_EXE.bat   REM → dist\TG_RECEIVER.exe (+ TG_USER_LOGIN.exe)
```

Каждый скрипт создаёт временное окружение `.venv-build`, ставит зависимости из
`requirements/`, докачивает офлайн-стили в `static/vendor/` и вызывает
соответствующий `.spec` из `packaging/`.

---

## SERVER и три HUB

SERVER — единственная центральная точка данных: он работает на мини‑ПК, хранит
`data-central/` и принимает изменения от каждого HUB. HUB хранит локальную
рабочую копию в `data-hub/`, отправляет свои изменения на SERVER и забирает только
изменения с SERVER. Не запускайте HUB вместо центрального SERVER.

> Переход со старого HUB, который раньше использовали как «сервер»: сначала
> остановите старый процесс и сделайте резервную копию его папки данных. Не
> запускайте новый SERVER с пустым `data-central/`, если рабочая история ещё в
> `data-hub/`. Для первого контролируемого запуска либо задайте SERVER в
> `server_config.json` существующую папку как `data_dir`, либо перенесите все
> файлы SQLite вместе с `-wal` и `-shm` при остановленных процессах. Только после
> проверки данных можно переносить их в отдельный `data-central/`.

Для трёх позиций в `server_config.json` оставьте `sync_pull_workers: 3` и
`wsgi_threads` не меньше 8. HUB опрашивает SERVER раз в 5 секунд по умолчанию,
причём после запуска запросы разнесены во времени; срочные правки по-прежнему
уходят через очередь сразу.

### Публикация обновления HUB

При первом запуске SERVER создаёт папку `Update/` рядом с `SERVER.exe`. В неё
копируется ZIP, содержащий **содержимое** папки `dist\EAVC - HUB\`: файл
`EAVC - HUB.exe`, каталог `_internal/` и `EAVC Updater.exe`.

В SERVER под ролью `admin` откройте «Админ → Настройки → Обновления HUB», выберите
ZIP, укажите версию, название и краткое описание, затем опубликуйте. Все HUB
увидят уведомление; оператор сам нажимает «Скачать и перезапустить HUB» после
сохранения своей работы. Обновление не является принудительным.

Перед заменой HUB скачивает ZIP, сверяет SHA-256 и подпись манифеста, останавливает
фоновый автопоиск, фиксирует SQLite, а независимый updater проверяет `/health`
новой версии. Если запуск не проходит, он возвращает прежний EXE и `_internal`.
`data-hub/`, настройки и БД не заменяются. Короткая пауза самого HUB неизбежна:
Windows не позволяет заменить работающий EXE. Первый переход со старой сборки,
где нет `EAVC Updater.exe`, выполняется вручную — дальше обновления идут из панели.

Ограничьте запись в `Update/` только администратору мини‑ПК. Проверка по общему
sync-ключу защищает передачу в локальной сети, но не заменяет подпись релиза:
для защиты от скомпрометированного SERVER следует подписывать сборки сертификатом
организации и настроить контроль доступа Windows к этой папке.

---

## Тесты

```bash
pytest tests/ -q
```

`tests/test_http_smoke.py` поднимает `create_app()` на временных SQLite-БД и
сверяет карту маршрутов со снимком `tests/route_map_snapshot.json` — страховка
на случай рефакторинга HTTP-слоя.
```
