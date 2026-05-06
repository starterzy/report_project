import time
import re
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from backend.models import get_db, User, UserDepartment, Department
from backend.services.auth_service import authenticate_user, create_access_token, get_current_user, get_password_hash, login_attempts, LOGIN_MAX_ATTEMPTS, LOGIN_WINDOW_SECONDS
from backend.models.schemas import LoginResponse, UserResponse, UserCreate, LoginRequest

router = APIRouter(prefix="/api/auth", tags=["认证"])

def check_rate_limit(ip: str) -> bool:
    """检查IP登录频率，返回True表示允许，False表示被限制"""
    now = time.time()
    if ip in login_attempts:
        count, reset_time = login_attempts[ip]
        if now < reset_time:
            if count >= LOGIN_MAX_ATTEMPTS:
                return False
            login_attempts[ip] = (count + 1, reset_time)
        else:
            login_attempts[ip] = (1, now + LOGIN_WINDOW_SECONDS)
    else:
        login_attempts[ip] = (1, now + LOGIN_WINDOW_SECONDS)
    return True

def validate_password_strength(password: str) -> tuple[bool, str]:
    """验证密码强度，返回(是否通过, 错误信息)"""
    if len(password) < 8:
        return False, "密码长度至少8位"
    if not re.search(r"[A-Z]", password):
        return False, "密码必须包含大写字母"
    if not re.search(r"[a-z]", password):
        return False, "密码必须包含小写字母"
    if not re.search(r"\d", password):
        return False, "密码必须包含数字"
    return True, ""

@router.post("/login", response_model=LoginResponse)
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"

    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="登录次数过于频繁，请稍后再试")

    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    access_token = create_access_token(data={"sub": user.username})
    departments = [ud.department.name for ud in user.user_departments]
    approver_sequences = [seq.sequence for seq in user.approver_sequences]
    filler_sequences = [seq.sequence for seq in user.filler_sequences]
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=user.id,
            username=user.username,
            roles=[user.roles.value] if isinstance(user.roles, type) else [user.roles],
            departments=departments,
            approver_sequences=approver_sequences,
            filler_sequences=filler_sequences
        )
    )

@router.post("/register", response_model=UserResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    # 密码强度验证
    valid, msg = validate_password_strength(user_data.password)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    user = User(
        username=user_data.username,
        password_hash=get_password_hash(user_data.password),
        roles=user_data.roles[0] if user_data.roles else None
    )
    db.add(user)
    db.flush()

    for dept_id in user_data.department_ids:
        ud = UserDepartment(user_id=user.id, department_id=dept_id)
        db.add(ud)

    db.commit()
    db.refresh(user)
    departments = [ud.department.name for ud in user.user_departments]
    return UserResponse(
        id=user.id,
        username=user.username,
        roles=[user.roles.value] if user.roles else [],
        departments=departments
    )

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    departments = [ud.department.name for ud in current_user.user_departments]
    approver_sequences = [seq.sequence for seq in current_user.approver_sequences]
    filler_sequences = [seq.sequence for seq in current_user.filler_sequences]
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        roles=[current_user.roles.value] if current_user.roles else [],
        departments=departments,
        approver_sequences=approver_sequences,
        filler_sequences=filler_sequences
    )
