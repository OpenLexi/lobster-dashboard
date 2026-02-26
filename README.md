# 🦞 Lobster Dashboard

A FastAPI dashboard for managing AI agent tasks and tracking token usage costs.

## Features

- **Task Board**: Kanban-style board with drag & drop (SortableJS)
- **Token Tracking**: Real-time cost tracking for AI models
- **Budget Management**: Monthly budget warnings and alerts
- **Agent Monitoring**: Heartbeat tracking for agent status
- **Simple Auth**: Password-based login with bcrypt hashing

## Tech Stack

- **Backend**: Python + FastAPI + SQLAlchemy
- **Frontend**: Jinja2 templates (server-side rendered)
- **Database**: SQLite
- **Deployment**: Render (with render.yaml)

## Setup

1. Clone the repository:
```bash
git clone https://github.com/OpenLexi/lobster-dashboard.git
cd lobster-dashboard
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your values
```

4. Generate password hash:
```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"
```

5. Run the app:
```bash
uvicorn main:app --reload
```

6. Open http://localhost:8000

## Usage

### Authentication
- Default password is set via `ADMIN_PASSWORD_HASH` environment variable
- First run: Set any password, the app will authenticate (hash will be generated)

### Task Management
- Create tasks via UI or API (`POST /api/tasks`)
- Drag & drop between columns: Proposed → Approved → In Progress → Done
- Update status via API (`PATCH /api/tasks/{id}`)

### Token Tracking
Every time your agent makes an API call, log the usage:
```python
import requests
requests.post("http://localhost:8000/api/tokens/log", json={
    "model": "claude-sonnet-4-5",
    "input_tokens": 1000,
    "output_tokens": 500,
    "session_id": "session_123"
})
```

### Heartbeat
Update agent status every 30 minutes:
```bash
curl -X POST http://localhost:8000/api/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "Lobster", "agent_email": "agent@lobster.local"}'
```

## API Reference

### Tasks
- `GET /api/tasks` - List all tasks
- `POST /api/tasks` - Create new task
- `PATCH /api/tasks/{id}` - Update task status

### Tokens
- `POST /api/tokens/log` - Log token usage
- `GET /api/tokens/summary` - Get usage statistics

### Agent
- `POST /api/heartbeat` - Update last seen timestamp

## Cost Calculation

Supported models and rates:

| Model | Input Cost | Output Cost |
|-------|------------|-------------|
| Claude Opus 4.5 | $5 / 1M | $25 / 1M |
| Claude Sonnet 4.5 | $3 / 1M | $15 / 1M |
| Claude Haiku 4.5 | $1 / 1M | $5 / 1M |
| DeepSeek | $0.27 / 1M | $1.10 / 1M |

## Deployment on Render

1. Push to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com)
3. Click "New +" → "Blueprint"
4. Connect your repository
5. Render will automatically deploy using `render.yaml`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_PASSWORD_HASH` | - | Bcrypt hash of admin password |
| `SECRET_KEY` | - | Secret key for session cookies |
| `DATABASE_URL` | `sqlite:///./lobster.db` | Database connection string |
| `AGENT_NAME` | `Lobster` | Agent display name |
| `AGENT_EMAIL` | `agent@lobster.local` | Agent email |
| `MONTHLY_BUDGET_USD` | `500` | Monthly budget in USD |
| `ENV` | `development` | Environment (development/production) |

## License

MIT