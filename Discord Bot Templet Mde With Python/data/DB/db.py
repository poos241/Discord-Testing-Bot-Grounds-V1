# db.py
import os
import sqlalchemy
from databases import Database
from data.DB.models import metadata

# Resolve the data dir relative to this file so the bot works
# no matter which folder you launch it from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../data/DB
DATA_DIR = os.path.dirname(os.path.dirname(BASE_DIR))  # .../data
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'bot.db')}"

database = Database(DATABASE_URL)
engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)
