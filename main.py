"""Lobster Dashboard - Main FastAPI application."""
from datetime import datetime, timedelta
from typing import Optional, List
import os
import json
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError


from fastapi import FastAPI, Request, Response, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

import database
from database import get_db, init_db
from models import Task, TaskStatus, TokenLog, AgentStatus, Project, ChatMessage
from auth import authenticate_user, create_session, clear_session, get_current_user
from config import AGENT_NAME, AGENT_EMAIL, MONTHLY_BUDGET_USD, DEBUG

# Initialize
database.Base.metadata.create_all(bind=database.engine)
app = FastAPI(title="Lobster Dashboard", debug=DEBUG)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
templates.env.globals["min"] = min
templates.env.globals["max"] = max

GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "")
GATEWAY_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")


@app.get("/health")
def health_check():
    """Render health check endpoint (no auth required)."""
    return {"status": "ok"}


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


class ChatCreate(BaseModel):
    sender: str = "Jesse"
    body: str


# Cost calculation
MODEL_RATES = {
    # Anthropic
    "claude-opus-4-5": {"input": 5.0, "output": 25.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "anthropic/claude-opus-4-5": {"input": 5.0, "output": 25.0},
    "anthropic/claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "anthropic/claude-haiku-4-5": {"input": 1.0, "output": 5.0},

    # DeepSeek
    "deepseek": {"input": 0.27, "output": 1.10},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "openrouter/deepseek": {"input": 0.27, "output": 1.10},

    # Codex (user-defined as free)
    "openai-codex/gpt-5.3-codex": {"input": 0.0, "output": 0.0},
    "gpt-5.3-codex": {"input": 0.0, "output": 0.0},
    "codex": {"input": 0.0, "output": 0.0},
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


def ensure_seed_projects(db: Session):
    """Load project definitions from projects_seed.json if DB is empty."""
    if db.query(Project).count() > 0:
        return

    seed_path = os.path.join(os.path.dirname(__file__), "projects_seed.json")
    if not os.path.exists(seed_path):
        return

    with open(seed_path, "r", encoding="utf-8") as f:
        seed_projects = json.load(f)

    for item in seed_projects:
        db.add(Project(
            id=item["id"],
            name=item["name"],
            repo=item["repo"],
            color=item.get("color", "#339af0"),
            status=item.get("status", "planning"),
            priority=item.get("priority", "medium"),
            purpose=item.get("purpose", ""),
            tech_stack=item.get("tech_stack", ""),
            todo_list=item.get("todo_list", ""),
            notes=item.get("notes", ""),
            memory_file=item.get("memory_file", ""),
        ))
    db.commit()


def ensure_seed_tasks(db: Session):
    """Load initial task backlog from tasks_seed.json if tasks are empty."""
    if db.query(Task).count() > 0:
        return

    seed_path = os.path.join(os.path.dirname(__file__), "tasks_seed.json")
    if not os.path.exists(seed_path):
        return

    with open(seed_path, "r", encoding="utf-8") as f:
        seed_tasks = json.load(f)

    for item in seed_tasks:
        db.add(Task(
            title=item["title"],
            description=item.get("description", ""),
            project=item.get("project", "General"),
            priority=item.get("priority", "medium"),
            status=item.get("status", TaskStatus.PROPOSED),
        ))
    db.commit()


def get_gateway_status() -> dict:
    """Best-effort OpenClaw gateway status using configured URL/token."""
    if not GATEWAY_URL:
        return {"ok": False, "reason": "OPENCLAW_GATEWAY_URL not set"}

    url = GATEWAY_URL.rstrip("/") + "/status"
    headers = {"accept": "application/json"}
    if GATEWAY_TOKEN:
        headers["authorization"] = f"Bearer {GATEWAY_TOKEN}"

    try:
        req = urlrequest.Request(url, headers=headers, method="GET")
        with urlrequest.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "status": payload}
    except HTTPError as e:
        return {"ok": False, "reason": f"HTTP {e.code}"}
    except URLError as e:
        return {"ok": False, "reason": str(e.reason)}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


def load_inbox_emails(limit: int = 100) -> List[dict]:
    """Load inbound email webhook JSON files from ~/.openclaw/inbox."""
    inbox_dir = os.path.expanduser("~/.openclaw/inbox")
    if not os.path.isdir(inbox_dir):
        return []

    items = []
    for name in os.listdir(inbox_dir):
        if not name.endswith(".json") or name == ".processed-emails.json":
            continue
        path = os.path.join(inbox_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            data = payload.get("data", {})
            body = payload.get("body", {})
            text = (body.get("text") or "").strip()
            items.append({
                "file": name,
                "email_id": data.get("email_id", ""),
                "subject": data.get("subject", "(no subject)"),
                "from": data.get("from", ""),
                "created_at": data.get("created_at") or payload.get("created_at"),
                "to": data.get("to", []),
                "text_preview": text[:800],
            })
        except Exception:
            continue

    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:limit]


def generate_lexi_reply(user_text: str) -> str:
    """Generate a deterministic local reply (Anthropic disabled by policy)."""
    prompt = (user_text or "").strip()[:3000]
    if not prompt:
        return "Got it — say a bit more and I’ll help from here."

    return f"Got it. I received: \"{prompt[:200]}\". I’m here and ready — tell me the next action and I’ll run it." 

# Web routes
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Login page."""
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login_submit(request: Request, password: str = Form(...)):
    """Handle login."""
    if authenticate_user(password):
        response = RedirectResponse(url="/", status_code=302)
        create_session(response)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})


@app.get("/logout")
def logout():
    """Logout."""
    response = RedirectResponse(url="/login", status_code=302)
    clear_session(response)
    return response


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Dashboard home."""
    ensure_seed_projects(db)
    ensure_seed_tasks(db)
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
    ensure_seed_tasks(db)
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
        "budget_used": stats["total_cost"],
        "budget_percent": round(budget_percent, 1),
        "budget_warning": budget_percent >= 80,
        "budget_critical": budget_percent >= 95
    })


@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Projects overview page."""
    ensure_seed_projects(db)
    projects = db.query(Project).order_by(Project.priority.desc(), Project.name.asc()).all()
    return templates.TemplateResponse("projects.html", {
        "request": request,
        "projects": [p.to_dict() for p in projects],
        "gateway": get_gateway_status(),
    })


@app.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail_page(project_id: str, request: Request, db: Session = Depends(get_db), user: str = Depends(get_current_user)):
    """Project detail page."""
    ensure_seed_projects(db)
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_tasks = db.query(Task).filter(Task.project == project.name).order_by(Task.updated_at.desc()).all()

    return templates.TemplateResponse("project_detail.html", {
        "request": request,
        "project": project.to_dict(),
        "tasks": [t.to_dict() for t in project_tasks],
        "gateway": get_gateway_status(),
    })


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request, db: Session = Depends(get_db)):
    """Internal chat page for Jesse + Lexi."""
    messages = db.query(ChatMessage).order_by(ChatMessage.created_at.asc()).limit(200).all()
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "messages": [m.to_dict() for m in messages],
    })


@app.get("/inbox", response_class=HTMLResponse)
def inbox_page(request: Request, user: str = Depends(get_current_user)):
    """Inbox page: shows received email webhooks from local OpenClaw inbox."""
    emails = load_inbox_emails(limit=200)
    return templates.TemplateResponse("inbox.html", {
        "request": request,
        "emails": emails,
        "email_count": len(emails),
    })


@app.get("/api/inbox")
def list_inbox_api(user: str = Depends(get_current_user)):
    """JSON API for inbox data shown in dashboard."""
    return load_inbox_emails(limit=200)


# API routes
@app.post("/api/tasks")
def create_task_api(task: TaskCreate, db: Session = Depends(get_db)):
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
def update_task_api(task_id: int, update: TaskUpdate, db: Session = Depends(get_db)):
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
def list_tasks_api(db: Session = Depends(get_db)):
    """List all tasks."""
    tasks = db.query(Task).all()
    return [task.to_dict() for task in tasks]


@app.delete("/api/tasks/{task_id}")
def delete_task_api(task_id: int, db: Session = Depends(get_db)):
    """Delete a task."""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    return {"ok": True, "deleted_id": task_id}


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
def token_summary_api(db: Session = Depends(get_db)):
    """Get token usage summary."""
    return get_token_stats(db, days=30)


@app.get("/api/gateway/status")
def gateway_status_api(user: str = Depends(get_current_user)):
    """Expose configured OpenClaw gateway status for dashboard monitoring."""
    return get_gateway_status()


@app.get("/api/chat")
def list_chat_api(db: Session = Depends(get_db)):
    """List recent chat messages."""
    messages = db.query(ChatMessage).order_by(ChatMessage.created_at.asc()).limit(200).all()
    return [m.to_dict() for m in messages]


@app.post("/api/chat")
def create_chat_api(data: ChatCreate, db: Session = Depends(get_db)):
    """Create chat message. If Jesse posts, generate an immediate Lexi reply."""
    body = (data.body or "").strip()
    sender = (data.sender or "Jesse").strip()[:40]
    if not body:
        raise HTTPException(status_code=400, detail="Message body is required")

    msg = ChatMessage(sender=sender, body=body[:4000])
    db.add(msg)
    db.commit()
    db.refresh(msg)

    response = {"message": msg.to_dict()}

    if sender.lower() == "jesse":
        lexi_body = generate_lexi_reply(body)
        lexi_msg = ChatMessage(sender="Lexi", body=lexi_body[:4000])
        db.add(lexi_msg)
        db.commit()
        db.refresh(lexi_msg)
        response["reply"] = lexi_msg.to_dict()

    return response


if __name__ == "__main__":
    import uvicorn
    # Get port from environment variable (Render sets this) or default to 8000
    port = int(os.getenv("PORT", 8000))
    print(f"Starting Lobster Dashboard on port {port}")
    print(f"Host: 0.0.0.0")
    uvicorn.run(app, host="0.0.0.0", port=port)
