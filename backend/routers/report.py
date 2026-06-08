from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from typing import Optional
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from backend.models import get_db, User, Task, Measure, ReportRecord, Department, RoleEnum, StatusEnum, TaskLeader, TaskDepartment, TaskPartnerDepartment, UserApproverSequence, UserFillerSequence
from backend.models.schemas import (
    TaskResponse, MeasureResponse, ReportRecordCreate, ReportRecordUpdate,
    ReportRecordResponse, RejectRequest
)
from backend.services.auth_service import get_current_user
from backend.services.excel_service import export_excel_from_db
from backend.services.notification_service import notify_first_approvers, notify_second_approver
import io

router = APIRouter(prefix="/api/report", tags=["报表"])

def task_to_response(task: Task) -> TaskResponse:
    # 牵头领导 - 多人用换行分隔
    leader = "\n".join([l.leader_name for l in task.leaders]) if task.leaders else ""

    # 牵头部门 - 多个部门用换行分隔
    department_name = "\n".join([d.department.name for d in task.departments]) if task.departments else ""

    # 配合部门 - 多个部门用换行分隔
    partner_list = []
    for p in task.partner_departments:
        if p.department:
            partner_list.append(p.department.name)
        elif p.department_name:
            partner_list.append(p.department_name)
    partner_depts = "\n".join(partner_list) if partner_list else ""

    return TaskResponse(
        id=task.id,
        sequence=task.sequence,
        name=task.name,
        target=task.target,
        leader=leader,
        department_name=department_name,
        partner_depts=partner_depts,
        deadline=task.deadline or "",
        measures=[
            MeasureResponse(
                id=m.id,
                content=m.content,
                task_id=m.task_id,
                person_liable=m.person_liable,
                specific_measure=m.specific_measure
            ) for m in task.measures
        ]
    )

@router.get("/tasks", response_model=list[TaskResponse])
async def get_tasks(
    year: int = Query(2026),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    tasks = db.query(Task).filter(Task.year == year).order_by(Task.sequence).all()
    return [task_to_response(t) for t in tasks]

@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_to_response(task)

@router.get("/records", response_model=list[ReportRecordResponse])
async def get_records(
    month: Optional[str] = None,  # YYYY-MM格式
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取填报记录列表，按用户权限过滤"""
    query = db.query(ReportRecord).options(
        joinedload(ReportRecord.task)
    )

    user_role = current_user.roles.value if hasattr(current_user.roles, 'value') else str(current_user.roles)

    # 权限控制：基于用户的角色和任务权限过滤可查看的记录
    if user_role != 'admin':
        accessible_ids = set()

        if user_role == 'approver':
            # 审批者：可查看其审批序号匹配的任务记录
            approver_seqs = [s.sequence for s in current_user.approver_sequences]
            if approver_seqs:
                tasks = db.query(Task.id).filter(Task.sequence.in_(approver_seqs)).all()
                accessible_ids.update(t.id for t in tasks)

        elif user_role == 'filler':
            # 填报者：可查看其填报序号匹配的任务记录（无限制则可查看所有）
            filler_seqs = [s.sequence for s in current_user.filler_sequences]
            if filler_seqs:
                tasks = db.query(Task.id).filter(Task.sequence.in_(filler_seqs)).all()
                accessible_ids.update(t.id for t in tasks)
            else:
                # 无填报限制，可查看所有任务
                all_tasks = db.query(Task.id).all()
                accessible_ids.update(t.id for t in all_tasks)

        # 所有角色：如果被设为某任务的二级审批人，也可查看该任务记录
        second_approver_tasks = db.query(Task.id).filter(Task.second_approver_id == current_user.id).all()
        second_ids = [t.id for t in second_approver_tasks]
        accessible_ids.update(second_ids)

        if not accessible_ids:
            return []

        query = query.filter(ReportRecord.task_id.in_(accessible_ids))

        # Leader 只能看已审核记录（但其作为二级审批人的任务可看全部状态）
        if user_role == 'leader':
            if second_ids:
                query = query.filter(
                    or_(
                        ReportRecord.status == StatusEnum.APPROVED,
                        ReportRecord.task_id.in_(second_ids)
                    )
                )
            else:
                query = query.filter(ReportRecord.status == StatusEnum.APPROVED)

    if status_filter:
        query = query.filter(ReportRecord.status == StatusEnum[status_filter.upper()])

    if month:
        query = query.filter(ReportRecord.month == month)

    records = query.all()
    result = []
    for r in records:
        result.append(ReportRecordResponse(
            id=r.id,
            task_id=r.task_id,
            submitter_id=r.submitter_id,
            submitter_name=r.submitter.username,
            month=r.month,
            current_content=r.current_content,
            next_plan=r.next_plan,
            task_progress=r.task_progress,
            status=r.status.value,
            submitted_at=r.submitted_at,
            reviewed_at=r.reviewed_at,
            reviewer_id=r.reviewer_id,
            reviewer_name=r.reviewer.username if r.reviewer else None,
            reject_reason=r.reject_reason,
            task_name=r.task.name,
            target=r.task.target,
            task_sequence=r.task.sequence,
            task_second_approver_id=r.task.second_approver_id if r.task else None,
            first_reviewer_name=r.first_reviewer_name
        ))
    return result

@router.post("/records", response_model=ReportRecordResponse)
async def create_record(
    record: ReportRecordCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建填报记录，现在按 task_id + month 创建（一个 task 一个月只有一条记录）"""
    task = db.query(Task).filter(Task.id == record.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 填报者权限检查
    _check_filler_permission(current_user, task, db)

    # 检查是否已存在当月记录（按 task_id + month 检查）
    existing = db.query(ReportRecord).filter(
        ReportRecord.task_id == record.task_id,
        ReportRecord.month == record.month
    ).first()

    if existing:
        # 更新现有记录（upsert）
        existing.current_content = record.current_content
        existing.next_plan = record.next_plan
        existing.task_progress = record.task_progress
        db.commit()
        db.refresh(existing)
        return ReportRecordResponse(
            id=existing.id,
            task_id=existing.task_id,
            submitter_id=existing.submitter_id,
            submitter_name=existing.submitter.username,
            month=existing.month,
            current_content=existing.current_content,
            next_plan=existing.next_plan,
            task_progress=existing.task_progress,
            status=existing.status.value,
            submitted_at=existing.submitted_at,
            reviewed_at=existing.reviewed_at,
            reviewer_id=existing.reviewer_id,
            reviewer_name=existing.reviewer.username if existing.reviewer else None,
            reject_reason=existing.reject_reason,
            task_name=task.name,
            target=task.target,
            task_sequence=task.sequence,
            task_second_approver_id=task.second_approver_id if task else None
        )

    new_record = ReportRecord(
        task_id=record.task_id,
        submitter_id=current_user.id,
        month=record.month,
        current_content=record.current_content,
        next_plan=record.next_plan,
        task_progress=record.task_progress,
        status=StatusEnum.DRAFT
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return ReportRecordResponse(
        id=new_record.id,
        task_id=new_record.task_id,
        submitter_id=new_record.submitter_id,
        submitter_name=current_user.username,
        month=new_record.month,
        current_content=new_record.current_content,
        next_plan=new_record.next_plan,
        status=new_record.status.value,
        submitted_at=new_record.submitted_at,
        reviewed_at=new_record.reviewed_at,
        reviewer_id=new_record.reviewer_id,
        reviewer_name=None,
        reject_reason=None,
        task_name=task.name,
        target=task.target,
        task_sequence=task.sequence,
        task_second_approver_id=task.second_approver_id if task else None,
        task_progress=new_record.task_progress
    )

@router.put("/records/{record_id}", response_model=ReportRecordResponse)
async def update_record(
    record_id: int,
    update_data: ReportRecordUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    record = db.query(ReportRecord).filter(ReportRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    # 填报者权限检查
    _check_filler_permission(current_user, record.task, db)

    user_role = current_user.roles.value if hasattr(current_user.roles, 'value') else str(current_user.roles)

    # 草稿可以修改，已审批的记录只有管理员可以修改
    if record.status.value == StatusEnum.APPROVED.value and user_role != 'admin':
        db.rollback()
        raise HTTPException(status_code=400, detail="已审核的记录无法修改")
    if record.status.value != StatusEnum.DRAFT.value and user_role not in ('approver', 'admin'):
        db.rollback()
        raise HTTPException(status_code=400, detail="Only draft records or approvers can modify")

    if update_data.current_content is not None:
        record.current_content = update_data.current_content
    if update_data.next_plan is not None:
        record.next_plan = update_data.next_plan
    if update_data.task_progress is not None:
        record.task_progress = update_data.task_progress

    db.commit()
    db.refresh(record)
    return ReportRecordResponse(
        id=record.id,
        task_id=record.task_id,
        submitter_id=record.submitter_id,
        submitter_name=record.submitter.username,
        month=record.month,
        current_content=record.current_content,
        next_plan=record.next_plan,
        task_progress=record.task_progress,
        status=record.status.value,
        submitted_at=record.submitted_at,
        reviewed_at=record.reviewed_at,
        reviewer_id=record.reviewer_id,
        reviewer_name=record.reviewer.username if record.reviewer else None,
        reject_reason=record.reject_reason,
        task_name=record.task.name,
        target=record.task.target,
        task_sequence=record.task.sequence,
        task_second_approver_id=record.task.second_approver_id if record.task else None,
        first_reviewer_name=record.first_reviewer_name
    )

@router.post("/records/{record_id}/submit", response_model=ReportRecordResponse)
async def submit_record(
    record_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    record = db.query(ReportRecord).filter(ReportRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="请先保存后再提交")
    if record.submitter_id != current_user.id:
        raise HTTPException(status_code=403, detail="仅能提交自己的记录")

    # 填报者权限检查
    _check_filler_permission(current_user, record.task, db)

    record.status = StatusEnum.SUBMITTED
    record.submitted_at = datetime.now()
    db.commit()
    db.refresh(record)

    # 后台通知一级审批者
    _task_sequence = record.task.sequence
    _task_target = record.task.target
    _submitter_name = current_user.username
    _month = record.month
    _progress = record.task_progress
    background_tasks.add_task(
        notify_first_approvers,
        _task_sequence,
        _task_target,
        _submitter_name,
        _month,
        _progress,
    )

    return ReportRecordResponse(
        id=record.id,
        task_id=record.task_id,
        submitter_id=record.submitter_id,
        submitter_name=current_user.username,
        month=record.month,
        current_content=record.current_content,
        next_plan=record.next_plan,
        status=record.status.value,
        submitted_at=record.submitted_at,
        reviewed_at=record.reviewed_at,
        reviewer_id=record.reviewer_id,
        reviewer_name=None,
        reject_reason=None,
        task_name=record.task.name,
        target=record.task.target,
        task_sequence=record.task.sequence,
        task_second_approver_id=record.task.second_approver_id,
        first_reviewer_name=record.first_reviewer_name,
        task_progress=record.task_progress
    )

def _check_approver_permission(user: User, record: ReportRecord, db: Session) -> None:
    """审批者权限检查：检查该记录对应的任务序号是否在审批者的可审批序号列表中"""
    user_role = user.roles.value if hasattr(user.roles, 'value') else str(user.roles)
    if user_role != 'approver':
        return

    task_sequence = record.task.sequence

    # 检查该序号是否在审批者的可审批序号列表中
    user_sequences = [seq.sequence for seq in user.approver_sequences]
    if task_sequence not in user_sequences:
        raise HTTPException(status_code=403, detail="No permission to approve this record")

def _check_filler_permission(user: User, task: Task, db: Session) -> None:
    """填报者权限检查：检查该记录对应的任务序号是否在填报者的可填报序号列表中"""
    user_role = user.roles.value if hasattr(user.roles, 'value') else str(user.roles)
    if user_role not in ('filler', 'approver', 'admin'):
        return

    # admin 和 approver 不受限制
    if user_role in ('approver', 'admin'):
        return

    # filler 检查序号限制
    task_sequence = task.sequence
    filler_sequences = [seq.sequence for seq in user.filler_sequences]

    # 如果没有设置限制，则可以填报所有
    if len(filler_sequences) == 0:
        return

    if task_sequence not in filler_sequences:
        raise HTTPException(status_code=403, detail="您没有权限填报此任务")

@router.post("/records/{record_id}/approve", response_model=ReportRecordResponse)
async def approve_record(
    record_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_role = current_user.roles.value if hasattr(current_user.roles, 'value') else str(current_user.roles)
    if user_role not in ('approver', 'admin'):
        raise HTTPException(status_code=403, detail="Only approvers can approve records")

    record = db.query(ReportRecord).filter(ReportRecord.id == record_id).first()
    if not record:
        db.rollback()
        raise HTTPException(status_code=404, detail="Record not found")

    # 获取任务信息
    task = db.query(Task).filter(Task.id == record.task_id).first()
    second_approver_id = task.second_approver_id if task else None

    if record.status.value == StatusEnum.APPROVED.value:
        db.rollback()
        raise HTTPException(status_code=400, detail="该记录已审核，请勿重复操作")

    if record.status.value == StatusEnum.FIRST_APPROVED.value:
        # 二级审批
        if second_approver_id and current_user.id != second_approver_id and user_role != 'admin':
            raise HTTPException(status_code=403, detail="您没有权限进行二级审批")
        record.status = StatusEnum.APPROVED
        record.reviewed_at = datetime.now()
        record.reviewer_id = current_user.id
        db.commit()
        db.refresh(record)
    elif record.status.value == StatusEnum.SUBMITTED.value:
        # 一级审批
        _check_approver_permission(current_user, record, db)

        if second_approver_id:
            # 需要二级审批
            record.status = StatusEnum.FIRST_APPROVED
            record.reviewed_at = datetime.now()
            record.first_reviewer_id = current_user.id
            record.first_reviewer_name = current_user.username
            record.reviewer_id = None
        else:
            # 不需要二级审批，直接完成
            record.status = StatusEnum.APPROVED
            record.reviewed_at = datetime.now()
            record.first_reviewer_id = current_user.id
            record.first_reviewer_name = current_user.username
            record.reviewer_id = current_user.id
        db.commit()
        db.refresh(record)

        # 一级审批通过且有二级审批人时，后台通知二级审批者
        if second_approver_id:
            _task_id = record.task_id
            _task_target = record.task.target
            _submitter_name = record.submitter.username
            _first_reviewer_name = current_user.username
            _month = record.month
            _progress = record.task_progress
            background_tasks.add_task(
                notify_second_approver,
                _task_id,
                _task_target,
                _submitter_name,
                _first_reviewer_name,
                _month,
                _progress,
            )
    else:
        db.rollback()
        raise HTTPException(status_code=400, detail="只能审核已提交或一级已审的记录")
    return ReportRecordResponse(
        id=record.id,
        task_id=record.task_id,
        submitter_id=record.submitter_id,
        submitter_name=record.submitter.username,
        month=record.month,
        current_content=record.current_content,
        next_plan=record.next_plan,
        task_progress=record.task_progress,
        status=record.status.value,
        submitted_at=record.submitted_at,
        reviewed_at=record.reviewed_at,
        reviewer_id=record.reviewer_id,
        reviewer_name=record.reviewer.username if record.reviewer else None,
        reject_reason=record.reject_reason,
        task_name=record.task.name,
        target=record.task.target,
        task_sequence=record.task.sequence,
        task_second_approver_id=task.second_approver_id if task else None,
        first_reviewer_name=record.first_reviewer_name
    )

@router.post("/records/{record_id}/reject", response_model=ReportRecordResponse)
async def reject_record(
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_role = current_user.roles.value if hasattr(current_user.roles, 'value') else str(current_user.roles)
    if user_role not in ('approver', 'admin'):
        raise HTTPException(status_code=403, detail="Only approvers can reject records")

    record = db.query(ReportRecord).filter(ReportRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    task = db.query(Task).filter(Task.id == record.task_id).first()
    second_approver_id = task.second_approver_id if task else None

    # 根据状态判断退回逻辑
    if record.status.value == StatusEnum.FIRST_APPROVED.value:
        # 二级审批退回 → 退回到一级审批（状态变为 submitted）
        if second_approver_id and current_user.id != second_approver_id and user_role != 'admin':
            raise HTTPException(status_code=403, detail="您没有权限进行二级审批")
        record.status = StatusEnum.SUBMITTED
        record.reviewed_at = None
        record.reviewer_id = None
    elif record.status.value == StatusEnum.SUBMITTED.value:
        # 一级审批退回 → 退回到填报者（状态变为 draft）
        _check_approver_permission(current_user, record, db)
        record.status = StatusEnum.DRAFT
        record.submitted_at = None
        record.reviewer_id = None
    else:
        raise HTTPException(status_code=400, detail="只能退回已提交或一级已审的记录")
    db.commit()
    db.refresh(record)
    return ReportRecordResponse(
        id=record.id,
        task_id=record.task_id,
        submitter_id=record.submitter_id,
        submitter_name=current_user.username,
        month=record.month,
        current_content=record.current_content,
        next_plan=record.next_plan,
        status=record.status.value,
        submitted_at=record.submitted_at,
        reviewed_at=record.reviewed_at,
        reviewer_id=record.reviewer_id,
        reviewer_name=current_user.username,
        reject_reason=record.reject_reason,
        task_name=record.task.name,
        target=record.task.target,
        task_sequence=record.task.sequence,
        task_second_approver_id=record.task.second_approver_id if record.task else None,
        first_reviewer_name=record.first_reviewer_name
    )

@router.get("/export")
async def export_records(
    month: str = Query(..., description="月份 YYYY-MM格式"),
    columns: Optional[str] = Query(None, description="选中的列，逗号分隔"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """导出任务列表Excel"""
    # 获取模板路径
    template_path = Path(__file__).parent.parent.parent / "2026年度集团总部重点工作任务分解表（完整稿）.xlsx"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="模板文件不存在")

    # 解析选中的列
    selected_columns = columns.split(',') if columns else None

    try:
        excel_data = export_excel_from_db(db, str(template_path), month, selected_columns)
        filename = f"任务列表_{month}.xlsx"
        encoded_filename = quote(filename, safe='')
        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
