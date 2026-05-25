# 🎮 Mine Collection — Modrinth Search Bot

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blue.svg)](https://postgresql.org)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-green.svg)](https://github.com/aiogram/aiogram)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Telegram-бот для поиска и отслеживания модов Minecraft с платформы Modrinth**

> Подписки на обновления, удобный поиск, поддержка псевдонимов и многое другое

---

## 📋 Оглавление

- [Возможности](#-возможности)
- [Технологии](#-технологии)
- [Установка](#-установка)
- [Конфигурация](#-конфигурация)
- [Запуск](#-запуск)
- [Команды бота](#-команды-бота)
- [Админ-команды](#-админ-команды)
- [Структура проекта](#-структура-проекта)
- [База данных](#-база-данных)
- [Парсинг модов](#-парсинг-модов)
- [Roadmap](#-roadmap)
- [Лицензия](#-лицензия)

---

## ✨ Возможности

### Для пользователей

| Функция | Описание |
|---------|----------|
| 🔍 **Умный поиск** | Поиск модов по названию с поддержкой псевдонимов (jei → Just Enough Items) |
| ⭐ **Приоритет псевдонимов** | Результаты по псевдонимам отображаются первыми со звёздочкой |
| 📦 **Информация о моде** | Название, описание, загрузки, категории, лицензия |
| 📄 **Список версий** | Все доступные версии мода с выбором подходящей |
| 🔔 **Подписки** | Автоматические уведомления о новых версиях в Telegram |
| 📋 **Управление подписками** | Просмотр и отписка от модов в одном месте |
| 🌐 **Ссылка на Modrinth** | Быстрый переход на страницу мода на сайте |

### Для администраторов

| Функция | Описание |
|---------|----------|
| 📊 **Статистика** | Количество модов, версий, пользователей, подписок |
| 🔄 **Управление кэшем** | Перезагрузка и сброс кэша поиска |
| 📝 **Управление псевдонимами** | Перезагрузка файла с псевдонимами |
| 📨 **Массовая рассылка** | Отправка сообщений всем пользователям |
| 🔍 **Проверка модов** | Поиск конкретного мода в базе данных |

---

## 🛠 Технологии

| Компонент | Технология | Назначение |
|-----------|------------|------------|
| **Бот** | Python 3.11 + aiogram 3.x | Telegram Bot API |
| **База данных** | PostgreSQL 15+ + asyncpg | Хранение модов, версий, пользователей, подписок |
| **Кэширование** | Redis | Кэширование результатов поиска |
| **Поиск** | SQL LIKE + rapidfuzz | Точный и нечёткий поиск |
| **Парсинг** | aiohttp + asyncio | Асинхронный парсинг Modrinth API |

---

## 📦 Установка

### Требования

- Python 3.11 или выше
- PostgreSQL 15 или выше
- Redis (опционально, для кэширования)

---

## 1. Клонирование репозитория

```bash
git clone https://github.com/aapsl/Mine-Collection.git
cd Mine-Collection
```

## 2. Установка зависимостей
```bash
pip install -r requirements.txt
```

Или вручную:
```bash
pip install aiogram python-dotenv rapidfuzz redis asyncpg tenacity aiohttp
```

## 3. Настройка базы данных PostgreSQL
```sql

CREATE DATABASE minecollection;
CREATE USER bot_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE minecollection TO bot_user;
```

## 4. Конфигурация

Скопируйте .env.example в .env и заполните:
```env

# Telegram
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_IDS=123456789,987654321

# PostgreSQL
DB_HOST=localhost
DB_PORT=5432
DB_USER=bot_user
DB_PASSWORD=your_password
DB_NAME=minecollection

# Redis (опционально)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Modrinth API (опционально, для увеличения лимита запросов)
MODRINTH_API_TOKEN=your_modrinth_token
```

## 5. Инициализация базы данных

Таблицы создадутся автоматически при первом запуске бота.

## 6. Заполнение базы данных модами
```bash

python FinalParser.py
```
> Парсер добавит все моды с ≥1000 загрузок с Modrinth API.

### 🚀 Запуск
Запуск бота
```bash

python bot/main.py
```
Запуск парсера (добавление новых модов)
```bash

python FinalParser.py
```

Обновление существующих модов
```bash

python FinalUpdater.py
```
## При запуске будет предложен выбор:

**1** — Топ-1000 модов (быстро, ~15 мин

**2** — Топ-5000 модов (средне, ~1.5 часа)

**3** — Топ-10000 модов (долго, ~3-4 часа)

**4** — Все моды (очень долго, ~10-15 часов)


## 🤖 Команды бота
### Основные команды
| Компонент | Технология |
|-----------|------------|
|**/start**	|**Начать работу с ботом**|
|**/help**	|**Показать справку**|
|**/mysubs**	|**Показать мои подписки**|

### Поиск

Просто введите название мода в чат:

    create — найдёт мод Create

    jei — найдёт Just Enough Items (по псевдониму)

    create: aeronautics — работает со спецсимволами

### ⚙️ Админ-команды
| **Команда** |	**Описание** |
|-----------|------------|
|**/stats**|	Статистика базы данных|
|**/check_db**|	Проверка подключения к БД|
|**/reload_cache**|	Перезагрузка кэша поиска|
|**/reload_aliases**|	Перезагрузка псевдонимов|
|**/reset_cache**|	Полный сброс кэша (Redis + локальный)|
|**/user_stats**|	Статистика пользователей и топ подписок|
|**/broadcast [текст]** |	Рассылка сообщения всем пользователям|
|**/check_mod [название]**| Проверка наличия мода в базе|
|**/help_admin**|	Полный список админ-команд|

### 📁 Структура проекта
```text

Mine-Collection/
├── bot/
│   ├── __init__.py
│   ├── main.py              # Главный файл бота
│   ├── config.py            # Конфигурация из .env
│   ├── database.py          # Работа с PostgreSQL
│   ├── cache.py             # Redis кэширование
│   ├── utils.py             # Поиск, форматирование, псевдонимы
│   ├── keyboards.py         # Inline клавиатуры
│   └── tasks/
│       └── updates.py       # Фоновая проверка обновлений
├── FinalParser.py           # Безопасный парсер модов
├── FinalUpdater.py          # Обновление существующих модов
├── mod_aliases.json         # Псевдонимы модов
├── requirements.txt         # Зависимости
├── .env                     # Конфигурация (не в репозитории)
└── README.md                # Документация
```
## 🗄️ База данных
### Схема таблиц

**mods**
| Поле |	Тип	| Описание |
|-----------|------------|------------|
| **id** |	TEXT |	Уникальный ID мода (primary key) |
| **title** |	TEXT |	Название мода |
| **description** |	TEXT |	Описание |
| **slug** |	TEXT |	URL-дружественное имя |
| **downloads** |	BIGINT |	Количество загрузок |
| **updated_at** |	TIMESTAMPTZ| 	Дата последнего обновления |
| **categories** |	TEXT[] |	Категории мода |
| **license** |	TEXT |	Лицензия |
| **client_side** |	TEXT |	Требования на клиенте |
| **server_side** |	TEXT |	Требования на сервере |

**versions**
|Поле|	Тип|	Описание|
|-----------|------------|------------|
|**id**|	TEXT|	Уникальный ID версии (primary key)|
|**mod_id**|	TEXT|	Ссылка на мод (foreign key)|
|**version_number**|	TEXT|	Номер версии|
|**loaders**|	TEXT[]|	Поддерживаемые модлоадеры|
|**game_versions**|	TEXT[]|	Поддерживаемые версии Minecraft|
|**download_url**|	TEXT|	Ссылка на скачивание|
|**published_at**|	TIMESTAMPTZ|	Дата публикации|

**users**
|Поле|	Тип	|Описание|
|-----------|------------|------------|
|**user_id**|	BIGINT|	Telegram ID пользователя (primary key)|
|**username**|TEXT|	Имя пользователя|
|**created_at**	|TIMESTAMPTZ|	Дата регистрации|

**subscriptions**
|Поле|	Тип	|Описание|
|-----------|------------|------------|
|**id**|	SERIAL|	Автоинкрементный ID|
|**user_id**|	BIGINT|	Ссылка на пользователя|
|**mod_id**|	TEXT|	Ссылка на мод|
|**last_version**|	TEXT|	Последняя известная версия|

## 🔄 Парсинг модов
### FinalParser.py

Безопасный парсер, который:
   
  ✅ Не удаляет существующие данные
  

  ✅ Добавляет только новые моды
  

  ✅ Обновляет информацию о существующих
  

  ✅ Сохраняет все версии модов
  

### FinalUpdater.py

  Интерактивный скрипт для обновления:
  
  Выбор количества модов для обновления
  
  Прогресс-бар
  
  Статистика после завершения
  
  Обработка ошибок


## 📅 Roadmap
### Реализовано

    Поиск модов с псевдонимами

    Подписки на обновления

    Фоновая проверка обновлений

    Админ-панель

    PostgreSQL вместо SQLite

    Кэширование через Redis

    Безопасный парсер

### В планах

    Кнопка "Скачать" для прямого скачивания модов

    Группировка версий по Minecraft

    Перевод интерфейса на русский

    Кастомные сборки модов

    Автоматическое определение зависимостей

    Web-панель администратора

# 🤝 Вклад в проект

## Приветствуются любые вклады в проект!

    Форкните репозиторий

    Создайте ветку для фичи (git checkout -b feature/amazing-feature)

    Зафиксируйте изменения (git commit -m 'Add amazing feature')

    Отправьте в ветку (git push origin feature/amazing-feature)

    Откройте Pull Request

## 📄 Лицензия

Проект распространяется под лицензией MIT.

# 🙏 Благодарности

  **Modrinth за отличное API
  aiogram за удобную библиотеку для ботов
  Всем тестерам и пользователям бота**

## 📞 Контакты

    Разработчик: @qldkj

    Бот в Telegram: @MineModCollectionBot

<div align="center">

⭐ Поставьте звезду репозиторию, если проект вам полезен! ⭐
</div> 

### requirements.txt
```markdown

aiogram==3.0.0b7
python-dotenv==1.0.0
rapidfuzz==3.0.0
redis==4.5.4
asyncpg==0.28.0
aiohttp==3.8.4
tenacity==8.2.0
```

### .env.example
```markdown

# Telegram Bot Configuration
BOT_TOKEN=your_bot_token_here
ADMIN_IDS=123456789,987654321

# PostgreSQL Configuration
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password_here
DB_NAME=minecollection

# Redis Configuration (optional)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Modrinth API (optional, для увеличения лимита запросов)
MODRINTH_API_TOKEN=your_modrinth_token_here

# Logging
LOG_LEVEL=INFO

# Paths
MOD_ALIASES_PATH=mod_aliases.json
```
