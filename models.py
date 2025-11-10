from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import declarative_base, sessionmaker
import datetime
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///emails.db")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class EmailLog(Base):
    __tablename__ = "email_logs"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String, index=True, nullable=False)   # IMAP message id
    sender = Column(String)
    subject = Column(String)
    body = Column(Text)
    category = Column(String)         # classification label
    confidence = Column(Float)        # classification confidence 0-1
    reply_text = Column(Text)         # reply that was sent or suggested
    action = Column(String)           # "auto-sent" | "manual-sent" | "skipped"
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.message_id,
            "from": self.sender,
            "subject": self.subject,
            "body": self.body,
            "reply_text": self.reply_text,
        }

def init_db():
    Base.metadata.create_all(bind=engine)

'''Uncomment the line below and run this module once'''
# init_db()