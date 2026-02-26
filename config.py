"""Configuration for Lobster Dashboard."""
import os
from dotenv import load_dotenv

load_dotenv()

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 3600 * 24 * 7  # 7 days

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lobster.db")

# Authentication
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")

# Agent info
AGENT_NAME = os.getenv("AGENT_NAME", "Lobster")
AGENT_EMAIL = os.getenv("AGENT_EMAIL", "agent@lobster.local")

# Budget
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "500.0"))

# Environment
ENV = os.getenv("ENV", "development")
DEBUG = ENV == "development"