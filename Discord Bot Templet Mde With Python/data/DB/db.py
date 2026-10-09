# db.py
import os
import sqlalchemy
from databases import Database
from data.DB.models import metadata

os.makedirs("data", exist_ok=True)
DATABASE_URL = "sqlite:///data/bot.db"

database = Database(DATABASE_URL)
engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)
