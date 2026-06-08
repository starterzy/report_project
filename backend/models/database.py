from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, Enum as SQLEnum, event
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import enum

SQLALCHEMY_DATABASE_URL = "sqlite:///./report.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class RoleEnum(enum.Enum):
    FILLER = "filler"      # 填报者
    APPROVER = "approver"  # 审批者
    LEADER = "leader"      # 领导层
    ADMIN = "admin"        # 管理者

class StatusEnum(enum.Enum):
    DRAFT = "draft"        # 草稿
    SUBMITTED = "submitted"  # 已提交
    FIRST_APPROVED = "first_approved"  # 一级已审
    APPROVED = "approved"    # 已审核
    REJECTED = "rejected"   # 已退回

class Department(Base):
    __tablename__ = "departments"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    users = relationship("UserDepartment", back_populates="department")
    task_departments = relationship("TaskDepartment", back_populates="department")
    task_partner_departments = relationship("TaskPartnerDepartment", back_populates="department")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    phone = Column(String(20), unique=True, nullable=True)
    password_hash = Column(String(200), nullable=False)
    roles = Column(SQLEnum(RoleEnum, values_callable=lambda x: [e.value for e in x]), default=RoleEnum.FILLER)
    is_active = Column(Integer, default=1)
    user_departments = relationship("UserDepartment", back_populates="user")
    approver_sequences = relationship("UserApproverSequence", back_populates="user", cascade="all, delete-orphan")
    filler_sequences = relationship("UserFillerSequence", back_populates="user", cascade="all, delete-orphan")
    submitted_records = relationship("ReportRecord", back_populates="submitter", foreign_keys="ReportRecord.submitter_id")
    reviewed_records = relationship("ReportRecord", back_populates="reviewer", foreign_keys="ReportRecord.reviewer_id")

class UserDepartment(Base):
    __tablename__ = "user_departments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    user = relationship("User", back_populates="user_departments")
    department = relationship("Department", back_populates="users")

class UserApproverSequence(Base):
    __tablename__ = "user_approver_sequences"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sequence = Column(Integer, nullable=False)  # 审批者有权限的序号
    user = relationship("User", back_populates="approver_sequences")

class UserFillerSequence(Base):
    __tablename__ = "user_filler_sequences"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sequence = Column(Integer, nullable=False)  # 填报者可填报的序号
    user = relationship("User", back_populates="filler_sequences")

class TaskLeader(Base):
    __tablename__ = "task_leaders"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    leader_name = Column(String(100), nullable=False)
    task = relationship("Task", back_populates="leaders")

class TaskDepartment(Base):
    __tablename__ = "task_departments"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    task = relationship("Task", back_populates="departments")
    department = relationship("Department", back_populates="task_departments")

class TaskPartnerDepartment(Base):
    __tablename__ = "task_partner_departments"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    department_name = Column(String(100))
    task = relationship("Task", back_populates="partner_departments")
    department = relationship("Department", back_populates="task_partner_departments")

class TaskReminderPerson(Base):
    __tablename__ = "task_reminder_persons"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    task = relationship("Task", back_populates="reminder_persons")
    user = relationship("User")

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    sequence = Column(Integer, nullable=False)  # 序号
    name = Column(String(100), nullable=False)     # 重点工作名称
    target = Column(Text, nullable=False)         # 主要目标任务
    deadline = Column(String(50))                  # 完成时间
    year = Column(Integer, default=2026)
    second_approver_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 二级审批人
    measures = relationship("Measure", back_populates="task")
    leaders = relationship("TaskLeader", back_populates="task", cascade="all, delete-orphan")
    departments = relationship("TaskDepartment", back_populates="task", cascade="all, delete-orphan")
    partner_departments = relationship("TaskPartnerDepartment", back_populates="task", cascade="all, delete-orphan")
    report_records = relationship("ReportRecord", back_populates="task", cascade="all, delete-orphan")
    second_approver = relationship("User", foreign_keys=[second_approver_id])
    reminder_persons = relationship("TaskReminderPerson", back_populates="task", cascade="all, delete-orphan")

class Measure(Base):
    __tablename__ = "measures"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    content = Column(Text, nullable=False)        # 年度工作措施
    person_liable = Column(String(100))             # 责任人
    specific_measure = Column(Text)                # 具体举措
    task = relationship("Task", back_populates="measures")

# ReportRecord 现在与 task_id 关联（一个 task 一个月只有一条记录）
class ReportRecord(Base):
    __tablename__ = "report_records"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)  # 改为 task_id
    submitter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    month = Column(String(7), nullable=False)        # 填报月份 YYYY-MM
    current_content = Column(Text)                 # 本月工作内容
    next_plan = Column(Text)                       # 下月工作计划
    task_progress = Column(Text)                   # 整体工作进展
    status = Column(SQLEnum(StatusEnum, values_callable=lambda x: [e.value for e in x]), default=StatusEnum.DRAFT)
    submitted_at = Column(DateTime, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reject_reason = Column(Text, nullable=True)      # 退回原因
    first_reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 一级审批人ID
    first_reviewer_name = Column(String(100), nullable=True)  # 一级审批人姓名
    task = relationship("Task", back_populates="report_records")
    submitter = relationship("User", back_populates="submitted_records", foreign_keys=[submitter_id])
    reviewer = relationship("User", back_populates="reviewed_records", foreign_keys=[reviewer_id])

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
