"""
企业微信审批通知服务
通过企业微信应用消息（textcard）通知审批者进行审批。
"""
import httpx
import logging
from backend.models.database import get_db, User, RoleEnum, UserApproverSequence, Task

logger = logging.getLogger(__name__)

# 企业微信应用配置
WEWORK_CORP_ID = "wwbf3d667dc5365208"
WEWORK_AGENT_ID = "1000145"
WEWORK_AGENT_SECRET = "AaExshvmH1AzprG7Y0yiz1JToKfYW8Jfk_6YVq0mBcY"

# 系统地址
SYSTEM_URL = "https://report.zjamp.com"


def _truncate(text: str, max_len: int = 100) -> str:
    """截断文本，超出长度加省略号"""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


async def _get_wework_access_token() -> str:
    """获取企业微信 access_token"""
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    params = {
        "corpid": WEWORK_CORP_ID,
        "corpsecret": WEWORK_AGENT_SECRET,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        data = response.json()
        if data.get("errcode") != 0:
            logger.error(f"获取企微 access_token 失败: {data}")
            raise Exception(f"获取企微 access_token 失败: {data.get('errmsg')}")
        return data.get("access_token")


async def send_wework_textcard(
    userids: list[str], title: str, description: str, url: str
) -> bool:
    """
    发送企业微信 textcard 消息。
    userids: 企微 UserID 列表（使用 phone 字段存储的值）
    返回 True 表示发送成功。
    """
    if not userids:
        logger.warning("未提供接收者，跳过通知发送")
        return False

    try:
        access_token = await _get_wework_access_token()
    except Exception as e:
        logger.error(f"获取 access_token 异常: {e}")
        return False

    send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
    body = {
        "touser": "|".join(userids),
        "msgtype": "textcard",
        "agentid": int(WEWORK_AGENT_ID),
        "textcard": {
            "title": title,
            "description": description,
            "url": url,
            "btntxt": "前往审批",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(send_url, json=body)
            data = response.json()
            if data.get("errcode") == 0:
                logger.info(f"企微通知发送成功: touser={len(userids)}人, title={title}")
                return True
            else:
                logger.error(f"企微通知发送失败: {data}")
                return False
    except Exception as e:
        logger.error(f"企微通知发送异常: {e}")
        return False


def get_first_approvers(db, task_sequence: int) -> list[User]:
    """
    查询一级审批者：所有 role=approver 且 UserApproverSequence.sequence
    匹配 task_sequence 的活跃用户。
    """
    approvers = (
        db.query(User)
        .join(UserApproverSequence, UserApproverSequence.user_id == User.id)
        .filter(
            User.roles == RoleEnum.APPROVER,
            User.is_active == 1,
            UserApproverSequence.sequence == task_sequence,
        )
        .all()
    )
    return approvers


def get_second_approver(db, task: Task) -> User | None:
    """
    获取二级审批人：Task.second_approver_id 指定的活跃用户。
    """
    if not task or not task.second_approver_id:
        return None
    return (
        db.query(User)
        .filter(
            User.id == task.second_approver_id,
            User.is_active == 1,
        )
        .first()
    )


async def notify_first_approvers(
    task_sequence: int,
    task_name: str,
    submitter_name: str,
    month: str,
    task_progress: str | None,
):
    """
    后台任务：通知一级审批者有新的报表待审批。
    此函数在 FastAPI BackgroundTasks 中运行，自行管理 DB 会话。
    """
    db = next(get_db())
    try:
        approvers = get_first_approvers(db, task_sequence)
        if not approvers:
            logger.info(f"未找到序号 {task_sequence} 的一级审批者，跳过通知")
            return

        userids = [a.phone for a in approvers if a.phone]
        if not userids:
            logger.warning(f"序号 {task_sequence} 的一级审批者没有企微 UserID，跳过通知")
            return

        title = "📋 新的报表待审批"
        desc = '<div class="gray">'
        desc += f"填报人：{submitter_name}<br/>"
        desc += f"任务名称：{task_name}<br/>"
        desc += f"填报月份：{month}"
        if task_progress:
            desc += f"<br/>工作进展：{_truncate(task_progress, 100)}"
        desc += "</div>"

        url = f"{SYSTEM_URL}/#/approve?month={month}"
        await send_wework_textcard(userids, title, desc, url)
    finally:
        db.close()


async def notify_second_approver(
    task_id: int,
    task_name: str,
    submitter_name: str,
    first_reviewer_name: str,
    month: str,
    task_progress: str | None,
):
    """
    后台任务：通知二级审批者报表已通过一级审批。
    此函数在 FastAPI BackgroundTasks 中运行，自行管理 DB 会话。
    """
    db = next(get_db())
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            logger.warning(f"未找到任务 id={task_id}，跳过二级审批通知")
            return

        approver = get_second_approver(db, task)
        if not approver:
            logger.info(f"任务 {task_name} 未设置二级审批人，跳过通知")
            return
        if not approver.phone:
            logger.warning(f"二级审批人 {approver.username} 没有企微 UserID，跳过通知")
            return

        title = "📋 报表已通过一级审批，待您二审"
        desc = '<div class="gray">'
        desc += f"填报人：{submitter_name}<br/>"
        desc += f"一级审批人：{first_reviewer_name}<br/>"
        desc += f"任务名称：{task_name}<br/>"
        desc += f"填报月份：{month}"
        if task_progress:
            desc += f"<br/>工作进展：{_truncate(task_progress, 100)}"
        desc += "</div>"

        url = f"{SYSTEM_URL}/#/approve?month={month}"
        await send_wework_textcard([approver.phone], title, desc, url)
    finally:
        db.close()
