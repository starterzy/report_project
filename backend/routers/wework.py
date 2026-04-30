from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import httpx
from backend.models import get_db, User
from backend.models.schemas import LoginResponse, UserResponse
from backend.services.auth_service import create_access_token
import json

router = APIRouter(prefix="/api/auth", tags=["认证"])

# 企业微信SSO配置
WEWORK_CORP_ID = "wwbf3d667dc5365208"
WEWORK_AGENT_ID = "1000145"
WEWORK_AGENT_SECRET = "AaExshvmH1AzprG7Y0yiz1JToKfYW8Jfk_6YVq0mBcY"

@router.get("/wework/redirect")
async def wework_redirect():
    """生成企业微信授权跳转URL"""
    redirect_uri = "https://report.zjamp.com/api/auth/wework/callback"
    url = f"https://open.weixin.qq.com/connect/oauth2/authorize?appid={WEWORK_CORP_ID}&agentid={WEWORK_AGENT_ID}&redirect_uri={redirect_uri}&state=1"
    return {"redirect_url": url}

@router.get("/wework/callback", response_class=HTMLResponse)
async def wework_callback(code: str, db: Session = Depends(get_db)):
    """企业微信OAuth2回调，处理单点登录"""
    try:
        wework_userid = await get_wework_userid(code)
        if not wework_userid:
            return error_html("无法获取企业微信用户身份")

        user = db.query(User).filter(User.phone == wework_userid).first()
        if not user:
            return error_html("该用户未注册，请联系管理员授权")

        if not user.is_active:
            return error_html("用户已被禁用")

        access_token = create_access_token(data={"sub": user.username})
        departments = [ud.department.name for ud in user.user_departments]
        approver_sequences = [seq.sequence for seq in user.approver_sequences]

        login_data = {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "roles": [user.roles.value] if user.roles else [],
                "departments": departments,
                "approver_sequences": approver_sequences
            }
        }

        return success_html(json.dumps(login_data))
    except Exception as e:
        return error_html(str(e))

def success_html(data: str) -> HTMLResponse:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>登录成功</title>
    </head>
    <body>
        <script>
            localStorage.setItem('token', '{data}');
            window.location.href = 'https://report.zjamp.com/#/';
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

def error_html(message: str) -> HTMLResponse:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>登录失败</title>
    </head>
    <body>
        <script>
            alert('{message}');
            window.location.href = 'https://report.zjamp.com/#/login';
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

async def get_wework_userid(code: str) -> str:
    """通过code获取企业微信用户userid"""
    access_token = await get_wework_access_token()
    url = "https://qyapi.weixin.qq.com/cgi-bin/user/getuserinfo"
    params = {
        "access_token": access_token,
        "code": code
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        data = response.json()
        if data.get("errcode") != 0:
            return None
        # UserId is the user identity in WeChat Work
        return data.get("UserId")

async def get_wework_access_token() -> str:
    """获取企业微信access_token"""
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    params = {
        "corpid": WEWORK_CORP_ID,
        "corpsecret": WEWORK_AGENT_SECRET
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        data = response.json()
        if data.get("errcode") != 0:
            raise HTTPException(status_code=500, detail="Failed to get WeChat Work access token")
        return data.get("access_token")
