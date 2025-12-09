# Database connection management for FOMC project

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fomc.config import MAIN_DB_PATH, load_env
from .base import Base

load_env()
DATABASE_URL = f"sqlite:///{MAIN_DB_PATH}"

# Create engine and session
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """
    Dependency to get DB session
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        print(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    """
    Initialize database tables
    """
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables created successfully.")
        return True
    except Exception as e:
        print(f"Error initializing database: {e}")
        return False
