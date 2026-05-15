#!/bin/bash
# 数据库备份脚本 - 每天晚上执行 (东八区)

BACKUP_DIR="/root/report_project/backup"
DB_PATH="/root/report_project/report.db"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/report.db.bak.${DATE}"

# 创建备份目录
mkdir -p ${BACKUP_DIR}

# 备份数据库
sqlite3 ${DB_PATH} ".backup ${BACKUP_FILE}"

# 只保留最近30天的备份
find ${BACKUP_DIR} -name "report.db.bak.*" -mtime +30 -delete

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup completed: ${BACKUP_FILE}"