"""Application configuration for InvestHome.

This module intentionally contains constants and environment-derived settings only.
It is the first step of the v3 backend refactor and should not contain route,
database, or business logic.
"""

import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
DB_BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DB_UNDO_DIR = os.path.join(DATA_DIR, "undo")
LEGACY_DB_NAME = os.path.join(APP_DIR, "finance.db")
DB_NAME = os.path.join(DATA_DIR, "finance.db")

APP_VERSION = "3.0.0-rc.1"

MAX_DATABASE_BACKUPS = 30
MAX_DATABASE_UNDO_POINTS = 5

GOLDAPI_KEY = os.getenv("GOLDAPI_KEY", "").strip()  # Optional .env fallback; Settings-stored key takes priority.

TRADING212_PROVIDER = "trading212"
TRADING212_AUTO_ACCOUNT_NAME = "Trading 212 ISA (Auto)"
TRADING212_AUTO_ACCOUNT_TYPE = "Stocks and Shares ISA"
TRADING212_AUTO_TERM_TYPE = "Mid Term"

ACCOUNT_TYPES = [
    "Emergency Fund",
    "Cash ISA",
    "Stocks and Shares ISA",
    "Lifetime ISA",
    "Pension",
    "Premium Bonds",
    "Physical Bullion",
]

TERM_TYPES = ["Emergency", "Liquid", "Short Term", "Mid Term", "Long Term", "Ignore"]

DEBT_TYPES = ["Credit Card", "Loan", "Car Finance", "Overdraft", "BNPL", "Finance Agreement", "Other"]
