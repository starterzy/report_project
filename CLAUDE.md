# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

报表系统 (Report Management System) - A Vue.js + FastAPI application for managing monthly work reports. Fillers submit reports on tasks, approvers review/approve/reject them (with optional two-level approval), and leaders view approved records.

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
│   ├── database.py      # SQLAlchemy models (User, Task, Measure, ReportRecord, Department, etc.)
│   └── schemas.py       # Pydantic request/response schemas
├── routers/
│   ├── auth.py          # Login, register, /me endpoints
│   ├── report.py        # Tasks, records CRUD, approve/reject (two-level), export
│   ├── department.py    # Department management
│   ├── user.py          # User management (admin), second_approver assignment
│   └── wework.py        # WeChat Work OAuth SSO
└── services/
    ├── auth_service.py   # JWT token handling, password hashing
    └── excel_service.py  # Import/export Excel with openpyxl
```

### Database Schema
- **User**: username, phone (unique), password_hash, roles (RoleEnum: filler/approver/leader/admin), is_active
- **UserDepartment**: user_id, department_id (many-to-many user-department)
- **UserApproverSequence**: user_id, sequence (defines which task sequences an approver can approve)
- **UserFillerSequence**: user_id, sequence (defines which task sequences a filler can submit reports for; empty = all)
- **Task**: sequence, name, target, deadline, year, second_approver_id (nullable FK to User)
- **TaskLeader**: task_id, leader_name (multiple leaders per task)
- **TaskDepartment**: task_id, department_id (牵头部门)
- **TaskPartnerDepartment**: task_id, department_id, department_name (配合部门)
- **Measure**: task_id, content, person_liable, specific_measure (年度措施)
- **ReportRecord**: task_id, submitter_id, month (YYYY-MM), current_content, next_plan, task_progress, status, submitted_at, reviewed_at, reviewer_id, first_reviewer_id, first_reviewer_name, reject_reason
- **Department**: name

### Status Flow (Two-Level Approval)
```
draft → submitted → first_approved → approved
  ↑         ↑            │
  └─────────┘            └──→ submitted (second-level reject)
  (first-level reject)
```
- Status enum: `draft`, `submitted`, `first_approved`, `approved`, `rejected`
- If a Task has `second_approver_id` set, approval requires two levels:
  1. First approver (matching `UserApproverSequence`) → `first_approved`
  2. Second approver (the designated user) or admin → `approved`
- If no `second_approver_id`, single approval goes directly to `approved`
- Reject from `first_approved` → back to `submitted` (second-level reject)
- Reject from `submitted` → back to `draft` (first-level reject)

### Permission Control
- **Filler**: Can only submit reports for tasks matching their `UserFillerSequence.sequence`; if no sequences configured, can submit for all tasks
- **Approver**: Can only approve/reject records for tasks matching their `UserApproverSequence.sequence`; admin bypasses this check
- **Leader**: Read-only, can only view `approved` records
- **Admin**: Full access, can edit approved records, bypass all permission checks, manage users

### Frontend Structure
```
frontend/src/
├── main.js              # Vue app entry
├── App.vue              # Root component
├── router/index.js      # Vue Router routes
├── stores/auth.js       # Pinia auth store
├── api/                 # Axios API modules
│   ├── index.js         # Axios instance with interceptors
│   ├── auth.js          # login, register, me, WeChat redirect
│   ├── report.js        # tasks, records, approve/reject, export
│   └── user.js          # user management (admin)
└── views/
    ├── LoginView.vue    # Login page (username/password + WeChat SSO)
    ├── LayoutView.vue   # App shell (header nav + main content)
    ├── DashboardView.vue # Dashboard with stats cards and monthly table
    ├── TasksView.vue    # Task list with inline editing, save/submit (filler)
    ├── ApproveView.vue  # Approve/reject interface with two-level approval UI
    └── AdminView.vue    # Admin panel: user management + approved records
```

### API Endpoints
- `POST /api/auth/login` - Login with username/password
- `GET /api/auth/me` - Get current user info
- `GET /api/report/tasks` - List tasks (year filter)
- `GET /api/report/records` - List report records (month, status filters)
- `POST /api/report/records` - Create record (upsert by task_id + month)
- `PUT /api/report/records/{id}` - Update draft/approved record
- `POST /api/report/records/{id}/submit` - Submit for review
- `POST /api/report/records/{id}/approve` - Approve (one-level or two-level)
- `POST /api/report/records/{id}/reject` - Reject (with reason)
- `GET /api/report/export` - Export to Excel (month, columns filters)
- `GET /api/users` - List all users (admin only)
- `POST /api/users` - Create user (admin only)
- `PUT /api/users/{id}` - Update user, assign second_approver_task_ids (admin only)
- `DELETE /api/users/{id}` - Deactivate user (admin only)
- `POST /api/users/{id}/activate` - Activate user (admin only)
- `GET /api/departments` - List departments
- `POST /api/departments` - Create department
- `GET /api/wework/auto-login` - Redirect to WeChat Work OAuth
- `GET /api/wework/callback` - WeChat Work OAuth callback

### Deployment
- **Server**: 10.8.252.170
- **Frontend path**: `/var/www/html/report/` (nginx root for port 3000)
- **Backend path**: `/root/report_project/` (running via systemd service `report-backend`)
- **Database**: `/root/report_project/report.db`
- **Deploy frontend**: `scp -r frontend/dist/* root@10.8.252.170:/var/www/html/report/`
- **Reload nginx**: `ssh root@10.8.252.170 "nginx -t && systemctl reload nginx"`

## Notes

- Report records use `task_id` + `month` as unique constraint (one record per task per month)
- `create_record` does upsert: if a record for the same task+month exists, it updates instead of creating
- Approver permission is checked against `UserApproverSequence.sequence` matching `Task.sequence`
- Filler permission is checked against `UserFillerSequence.sequence` matching `Task.sequence`; empty sequences = no restriction
- Leader role can only view approved records
- On first backend startup, tasks are auto-imported from Excel if database is empty
- No database migration tool (Alembic) is configured; `init_db()` uses `create_all()` which only creates new tables, does not alter existing ones
- Known issue: actual SQLite schema may be out of sync with ORM models due to lack of migrations
