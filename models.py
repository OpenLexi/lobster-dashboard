"""Database models."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Enum
from database import Base
import enum


class TaskStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    project = Column(String, default="General")
    priority = Column(String, default=TaskPriority.MEDIUM)
    status = Column(String, default=TaskStatus.PROPOSED)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "project": self.project,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class TokenLog(Base):
    __tablename__ = "token_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    model = Column(String, nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    session_id = Column(String, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }


class AgentStatus(Base):
    __tablename__ = "agent_status"
    
    id = Column(Integer, primary_key=True)
    agent_name = Column(String, default="Lobster")
    agent_email = Column(String, default="agent@lobster.local")
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "agent_name": self.agent_name,
            "agent_email": self.agent_email,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "last_heartbeat_human": self.last_heartbeat.strftime("%Y-%m-%d %H:%M UTC") if self.last_heartbeat else "Never"
        }