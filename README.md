# Velobike2

A Telegram bot and API gateway for managing Velobike accounts, searching and renting bikes, and automating account authentication.  
Includes a FastAPI backend, Telegram bot (aiogram), and database integration (PostgreSQL via SQLAlchemy).

## Features

- **Telegram Bot**: Rent bikes, manage accounts, and interact with Velobike via Telegram.
- **REST API**: FastAPI endpoints for searching, renting, and managing bikes.
- **Database**: Stores user accounts, rides, and Telegram user data in PostgreSQL.
- **Automation**: Script to refresh and authenticate accounts using Playwright.

## Requirements

- Python 3.10+
- PostgreSQL database
- Chrome browser (for Playwright automation)
- Telegram Bot Token

## Installation

1. **Clone the repository:**

   ```sh
   git clone https://github.com/yourusername/velobike2.git
   cd velobike2
   ```

2. **Create and activate a virtual environment (optional but recommended):**

   ```sh
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install dependencies:**

   ```sh
   pip install -r requirements.txt
   ```

4. **Configure secrets:**

   - Copy `secrets.yaml.example` to `secrets.yaml` and fill in your real credentials:
     ```yaml
     bot_token: "YOUR_BOT_TOKEN_HERE"
     database_url: "postgresql://user:password@host:port/database"
     api_base_url: "http://localhost:8000/api/v1"
     ```

5. **Run database migrations (if using Alembic):**

   ```sh
   alembic upgrade head
   ```

6. **Create database tables (if not using Alembic):**
   ```sh
   python database.py
   ```

## Usage

### 1. Start the API server

```sh
uvicorn api:app --reload
```

- The API will be available at `http://localhost:8000`.

### 2. Start the Telegram bot

```sh
python bot.py
```

### 3. Refresh account tokens (optional, for automation)

```sh
python refresh.py
```

## Project Structure

- `api.py` — FastAPI application (REST API for bike operations)
- `bot.py` — Telegram bot (aiogram)
- `database.py` — SQLAlchemy models and DB utilities
- `refresh.py` — Automation for account authentication (Playwright)
- `config.py` — Configuration and secrets loading

## Environment Variables

- `BOT_TOKEN` (or in `secrets.yaml`)
- `DATABASE_URL` (or in `secrets.yaml`)
- `API_BASE_URL` (or in `secrets.yaml`)
- `LOG_LEVEL` (optional, default: DEBUG)

## Notes

- For Playwright automation, Chrome must be installed and accessible.
- The bot only allows approved Telegram users (see `database.py` for user approval logic).
- For production, configure a secure database and restrict access to secrets.
