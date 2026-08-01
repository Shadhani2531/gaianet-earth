from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
import os

# Use SQLite for persistence
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'reports.db')}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    incident_type = Column(String, nullable=False)
    severity = Column(Integer, nullable=False)
    description = Column(String)
    reporter_name = Column(String, nullable=False, default="Anonymous")
    reporter_email = Column(String, nullable=True)
    satellite_confirmed = Column(Integer, default=0)  # 0/1 boolean (SQLite-friendly)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

# Create tables
Base.metadata.create_all(bind=engine)

# --- Lightweight migration for existing databases ---
# Base.metadata.create_all() only creates missing TABLES, not missing
# COLUMNS on tables that already exist. Since reports.db may already exist
# from before reporter_name/reporter_email were added, patch it in place.
def _migrate_add_missing_columns():
    with engine.connect() as conn:
        existing_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(reports)").fetchall()}
        if "reporter_name" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE reports ADD COLUMN reporter_name VARCHAR DEFAULT 'Anonymous'")
        if "reporter_email" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE reports ADD COLUMN reporter_email VARCHAR")
        if "satellite_confirmed" not in existing_cols:
            conn.exec_driver_sql("ALTER TABLE reports ADD COLUMN satellite_confirmed INTEGER DEFAULT 0")
        conn.commit()

_migrate_add_missing_columns()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
