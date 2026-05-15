# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

报表系统 (Report Management System) - A Vue.js + FastAPI application for managing monthly work reports. Users submit reports on tasks, approvers review/reject them, and leaders view approved records.

## Tech Stack

- **Frontend**: Vue 3 + Vite + Element Plus + Pinia + Vue Router
- **Backend**: FastAPI + SQLAlchemy (SQLite)
- **Auth**: JWT tokens + WeChat Work (企业微信) OAuth SSO
- **Server**: nginx (frontend on port 3000, API proxied to port 8080)

## Common Commands

### Frontend
```bash
cd frontend
npm install          # Install dependencies
npm run dev          # Start dev server (port 3000)
npm run build        # Build for production → dist/
npm run preview      # Preview production build
```

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8080   # Start API server
python -c "from models.database import init_db; init_db()"  # Initialize DB
```

### Database
```bash
sqlite3 report.db                    # Open SQLite shell
sqlite3 report.db ".schema"          # Show table schemas
sqlite3 report.db "SELECT * FROM users;"  # Query data
```

## Architecture

### Backend Structure
```
backend/
├── main.py              # FastAPI app entry, lifespan events, CORS, routers
├── models/
│   ├── database.py      # SQLAlchemy models (User, Task, Measure, ReportRecord, Department)
│   └── schemas.py        # Pydantic request/response schemas
├── routers/
│   ├── auth.py          # Login, register, /me endpoints
│   ├── report.py        # Tasks, records CRUD, approve/reject, export
│   ├── department.py    # Department management
│   ├── user.py           # User management
│   └── wework.py        # WeChat Work OAuth SSO
└── services/
    ├── auth_service.py   # JWT token handling, password hashing
    └── excel_service.py  # Import/export Excel with openpyxl
```

### Database Schema
- **User**: username, phone, password_hash, roles (filler/approver/leader/admin), departments
- **Task**: sequence, name, target, deadline, year, leaders, departments, partner_departments
- **Measure**: task_id, content, person_liable (年度措施)
- **ReportRecord**: task_id, submitter_id, month (YYYY-MM), current_content, next_plan, status (draft/submitted/approved/rejected), submitted_at, reviewed_at, reviewer_id, reject_reason
- **Department**: name
- **UserApproverSequence**: user_id, sequence (defines which task sequences an approver can approve)

### Frontend Structure
```
frontend/src/
├── main.js              # Vue app entry
├── App.vue              # Root component
├── router/index.js      # Vue Router routes
├── stores/auth.js       # Pinia auth store
├── api/                 # Axios API modules
│   ├── auth.js          # login, register, me
│   ├── report.js        # tasks, records, approve/reject
│   └── user.js
└── views/
    ├── LoginView.vue    # Login page
    ├── DashboardView.vue # Task overview
    ├── TasksView.vue    # Task list with measures
    ├── ApproveView.vue  # Approve/reject interface
    └── AdminView.vue    # User/department management
```

### API Endpoints
- `POST /api/auth/login` - Login with username/password
- `GET /api/auth/me` - Get current user info
- `GET /api/report/tasks` - List tasks (year filter)
- `GET /api/report/records` - List report records (month, status filters)
- `POST /api/report/records` - Create record
- `PUT /api/report/records/{id}` - Update draft record
- `POST /api/report/records/{id}/submit` - Submit for review
- `POST /api/report/records/{id}/approve` - Approve (approver/admin only)
- `POST /api/report/records/{id}/reject` - Reject back to draft
- `GET /api/report/export` - Export to Excel

### Deployment
- **Server**: 10.8.252.170
- **Frontend path**: `/var/www/html/report/` (nginx root for port 3000)
- **Backend path**: `/root/report_project/` (running via systemd service `report-backend`)
- **Database**: `/root/report_project/report.db`
- **Deploy frontend**: `scp -r frontend/dist/* root@10.8.252.170:/var/www/html/report/`
- **Reload nginx**: `ssh root@10.8.252.170 "nginx -t && systemctl reload nginx"`

## Notes

- Report records use `task_id` + `month` as unique constraint (one record per task per month)
- Approver permission is checked against `UserApproverSequence.sequence` matching `Task.sequence`
- Leader role can only view approved records
- On first backend startup, tasks are auto-imported from Excel if database is empty
