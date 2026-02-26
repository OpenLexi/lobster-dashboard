"""Lobster Dashboard - Main FastAPI application."""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

import database
from database import get_db, init_db
from models import Task, TaskStatus, TokenLog, AgentStatus
from auth import authenticate_user, create_session, clear_session, get_current_user
from config import AGENT_NAME, AGENT_EMAIL, MONTHLY_BUDGET_USD, DEBUG

# Initialize
database.Base.metadata.create_all(bind=database.engine)
app = FastAPI(title="Lobster Dashboard", debug=DEBUG)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# Pydantic models
class TaskCreate(BaseModel):
    title: str
    description: str = ""
    project: str = "General"
    priority: str = "medium"


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None


class TokenLogCreate(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    session_id: str = ""


class HeartbeatCreate(BaseModel):
    agent_name: Optional[str] = None
    agent_email: Optional[str] = None


# Cost calculation
MODEL_RATES = {
    "claude-opus-4-5": {"input": 5.0, "output": 25.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "deepseek": {"input": 0.27, "output": 1.10},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "openrouter/deepseek": {"input": 0.27, "output": 1.10},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD."""
    rates = MODEL_RATES.get(model.lower(), MODEL_RATES.get("claude-sonnet-4-5"))
    input_cost = (input_tokens / 1_000_000) * rates["input"]
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return round(input_cost + output_cost, 6)


# Helper functions
def get_agent_status(db: Session) -> AgentStatus:
    """Get or create agent status."""
    status = db.query(AgentStatus).first()
    if not status:
        status = AgentStatus(agent_name=AGENT_NAME, agent_email=AGENT_EMAIL)
        db.add(status)
        db.commit()
    return status


def get_task_stats(db: Session) -> dict:
    """Get task statistics."""
    stats = {}
    for status in TaskStatus:
        stats[status.value] = db.query(Task).filter(Task.status == status.value).count()
    return stats


def get_token_stats(db: Session, days: int = 30) -> dict:
    """Get token usage statistics."""
    since = datetime.utcnow() - timedelta(days=days)
    
    logs = db.query(TokenLog).filter(TokenLog.timestamp >= since).all()
    
    total_input = sum(log.input_tokens for log in logs)
    total_output = sum(log.output_tokens for log in logs)
    total_cost = sum(log.cost_usd for log in logs)
    
    # By model
    by_model = {}
    for log in logs:
        if log.model not in by_model:
            by_model[log.model] = {"input": 0, "output": 0, "cost": 0}
        by_model[log.model]["input"] += log.input_tokens
        by_model[log.model]["output"] += log.output_tokens
        by_model[log.model]["cost"] += log.cost_usd
    
    # Daily breakdown
    daily = {}
    for log in logs:
        day = log.timestamp.strftime("%Y-%m-%d")
        if day not in daily:
            daily[day] = 0
        daily[day] += log.cost_usd
    
    return {
        "total_input": total_input,
        "total_output": total_output,
        "total_cost": round(total_cost, 4),
        "count": len(logs),
        "by_model": by_model,
        "daily": daily
    }


# Web routes
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login_submit(request: Request, response: Response, password: str = Form(...)):
    """Handle login."""
    if authenticate_user(password):
        create_session(response)
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})


@app.get("/logout")
def logout(response: Response):
    """Logout."""
    clear_session(response)
    return RedirectResponse(url="/login", status_code=302)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Dashboard home."""
    agent_status = get_agent_status(db)
    task_stats = get_task_stats(db)
    token_stats = get_token_stats(db, days=30)
    
    # Budget status
    budget_used = token_stats["total_cost"]
    budget_percent = (budget_used / MONTHLY_BUDGET_USD) * 100 if MONTHLY_BUDGET_USD > 0 else 0
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "agent": agent_status.to_dict(),
        "task_stats": task_stats,
        "token_stats": token_stats,
        "monthly_budget": MONTHLY_BUDGET_USD,
        "budget_used": budget_used,
        "budget_percent": round(budget_percent, 1),
        "budget_warning": budget_percent >= 80,
        "budget_critical": budget_percent >= 95
    })


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Task board page."""
    tasks = db.query(Task).all()
    
    # Group by status
    columns = {status.value: [] for status in TaskStatus}
    for task in tasks:
        if task.status in columns:
            columns[task.status].append(task)
    
    return templates.TemplateResponse("tasks.html", {
        "request": request,
        "columns": columns
    })


@app.get("/tokens", response_class=HTMLResponse)
def tokens_page(request: Request, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Token tracker page."""
    stats = get_token_stats(db, days=30)
    logs = db.query(TokenLog).order_by(TokenLog.timestamp.desc()).limit(100).all()
    
    budget_percent = (stats["total_cost"] / MONTHLY_BUDGET_USD) * 100 if MONTHLY_BUDGET_USD > 0 else 0
    
    return templates.TemplateResponse("tokens.html", {
        "request": request,
        "stats": stats,
        "logs": logs,
        "monthly_budget": MONTHLY_BUDGET_USD,
        "budget_percent": round(budget_percent, 1),
        "budget_warning": budget_percent >= 80,
        "budget_critical": budget_percent >= 95
    })


# API routes
@app.post("/api/tasks")
def create_task_api(task: TaskCreate, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Create a new task."""
    db_task = Task(
        title=task.title,
        description=task.description,
        project=task.project,
        priority=task.priority,
        status=TaskStatus.PROPOSED
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task.to_dict()


@app.patch("/api/tasks/{task_id}")
def update_task_api(task_id: int, update: TaskUpdate, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Update task status or notes."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if update.status:
        task.status = update.status
    if update.notes:
        task.description = update.notes
    task.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(task)
    return task.to_dict()


@app.get("/api/tasks")
def list_tasks_api(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """List all tasks."""
    tasks = db.query(Task).all()
    return [task.to_dict() for task in tasks]


@app.post("/api/heartbeat")
def heartbeat_api(data: HeartbeatCreate, db: Session = Depends(get_db)):
    """Update agent heartbeat."""
    status = get_agent_status(db)
    status.last_heartbeat = datetime.utcnow()
    if data.agent_name:
        status.agent_name = data.agent_name
    if data.agent_email:
        status.agent_email = data.agent_email
    db.commit()
    return {"status": "ok", "last_heartbeat": status.last_heartbeat.isoformat()}


@app.post("/api/tokens/log")
def log_tokens_api(data: TokenLogCreate, db: Session = Depends(get_db)):
    """Log token usage."""
    cost = calculate_cost(data.model, data.input_tokens, data.output_tokens)
    
    log = TokenLog(
        model=data.model,
        input_tokens=data.input_tokens,
        output_tokens=data.output_tokens,
        cost_usd=cost,
        session_id=data.session_id
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    
    return {
        "id": log.id,
        "cost_usd": cost,
        "timestamp": log.timestamp.isoformat()
    }


@app.get("/api/tokens/summary")
def token_summary_api(db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Get token usage summary."""
    return get_token_stats(db, days=30)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)