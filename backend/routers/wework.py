from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
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

def get_oauth_url() -> str:
    """生成企微OAuth授权URL"""
    from urllib.parse import quote
    redirect_uri = quote("https://report.zjamp.com/api/auth/wework/callback", safe='')
    return f"https://open.weixin.qq.com/connect/oauth2/authorize?appid={WEWORK_CORP_ID}&redirect_uri={redirect_uri}&response_type=code&scope=snsapi_base&state=1#wechat_redirect"

@router.get("/wework/auto-login")
async def wework_auto_login():
    """自动登录端点 - 访问时直接跳转企微授权页（用于企微应用首页地址）"""
    return RedirectResponse(url=get_oauth_url())

@router.get("/wework/redirect")
async def wework_redirect():
    """生成企业微信授权跳转URL"""
    return {"redirect_url": get_oauth_url()}

@router.get("/wework/callback", response_class=HTMLResponse)
async def wework_callback(code: str = None, state: str = None, db: Session = Depends(get_db)):
    """企业微信OAuth2回调，处理单点登录"""
    print(f"[DEBUG] Callback received: code={code}, state={state}")

    if not code:
        print("[DEBUG] No code provided")
        return error_html("授权码无效，请重试")

    try:
        # 获取用户身份标识
        wework_userid = await get_wework_userid(code)
        print(f"[DEBUG] wework_userid: {wework_userid}")

        if not wework_userid:
            print(f"[DEBUG] Failed to get userid for code: {code}")
            return error_html("无法获取企业微信用户身份")

        # 查询本地用户 - 使用 phone 字段匹配 wework_userid
        user = db.query(User).filter(User.phone == wework_userid).first()
        print(f"[DEBUG] User query result: {user}")

        if not user:
            print(f"[DEBUG] No user found with phone={wework_userid}")
            # 调试：打印所有用户的phone
            all_phones = [u.phone for u in db.query(User).all()]
            print(f"[DEBUG] All user phones in DB: {all_phones}")
            return error_html("该用户未注册，请联系管理员授权")

        if not user.is_active:
            return error_html("用户已被禁用")

        access_token = create_access_token(data={"sub": user.username})
        departments = [ud.department.name for ud in user.user_departments]
        approver_sequences = [seq.sequence for seq in user.approver_sequences]
        filler_sequences = [seq.sequence for seq in user.filler_sequences]

        login_data = {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "roles": [user.roles.value] if user.roles else [],
                "departments": departments,
                "approver_sequences": approver_sequences,
                "filler_sequences": filler_sequences
            }
        }

        print(f"[INFO] SSO登录成功: userid={wework_userid}, username={user.username}, phone={user.phone}")
        return success_html(access_token, login_data["user"])
    except Exception as e:
        return error_html(str(e))

def success_html(access_token: str, user_data: dict) -> HTMLResponse:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>登录成功</title>
    </head>
    <body>
        <script>
            localStorage.setItem('token', '{access_token}');
            localStorage.setItem('user', JSON.stringify({json.dumps(user_data)}));
            window.location.href = 'https://report.zjamp.com/';
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
    """通过code获取企业微信用户userid（企业OAuth）"""
    print(f"[DEBUG] get_wework_userid called with code: {code}")

    # 企业OAuth使用corp API获取UserId
    access_token = await get_wework_access_token()
    print(f"[DEBUG] Got access token: {access_token[:20]}...")

    # 使用corp API的getuserinfo接口，直接传code
    url = "https://qyapi.weixin.qq.com/cgi-bin/user/getuserinfo"
    params = {
        "access_token": access_token,
        "code": code
    }
    print(f"[DEBUG] Calling getuserinfo with code...")

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        data = response.json()
        print(f"[DEBUG] getuserinfo response: {data}")

        if data.get("errcode") != 0:
            print(f"[DEBUG] errcode: {data.get('errcode')}, errmsg: {data.get('errmsg')}")
            return None
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
