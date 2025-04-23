#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
数据库迁移脚本 - 将push_review_log表中的updated_at字段从BIGINT类型转换为DATETIME类型
"""

import pymysql
import datetime
from pymysql.cursors import DictCursor
from biz.service.review_service import ReviewService


def migrate_push_review_log():
    """将push_review_log表中的updated_at字段从BIGINT类型转换为DATETIME类型"""
    conn = None
    try:
        conn = ReviewService.get_connection()
        
        # 1. 检查是否存在push_review_log表
        with conn.cursor() as cursor:
            cursor.execute("SHOW TABLES LIKE 'push_review_log'")
            if not cursor.fetchone():
                print("push_review_log表不存在，无需迁移")
                return
            
            # 2. 检查updated_at字段类型
            cursor.execute("DESCRIBE push_review_log updated_at")
            field_info = cursor.fetchone()
            if not field_info:
                print("updated_at字段不存在，无需迁移")
                return
                
            field_type = field_info['Type']
            if 'datetime' in field_type.lower():
                print("updated_at字段已经是DATETIME类型，无需迁移")
                return
            
            # 3. 创建临时列
            cursor.execute("ALTER TABLE push_review_log ADD COLUMN updated_at_new DATETIME")
            
            # 4. 迁移数据，将时间戳转换为DATETIME
            cursor.execute("SELECT id, updated_at FROM push_review_log")
            rows = cursor.fetchall()
            
            for row in rows:
                if row['updated_at'] is not None and row['updated_at'] > 0:
                    try:
                        # 将时间戳转换为DATETIME
                        dt = datetime.datetime.fromtimestamp(row['updated_at'])
                        cursor.execute(
                            "UPDATE push_review_log SET updated_at_new = %s WHERE id = %s",
                            (dt, row['id'])
                        )
                    except Exception as e:
                        print(f"转换时间戳失败，ID: {row['id']}, 时间戳: {row['updated_at']}, 错误: {e}")
            
            # 5. 删除原字段并重命名新字段
            cursor.execute("ALTER TABLE push_review_log DROP COLUMN updated_at")
            cursor.execute("ALTER TABLE push_review_log CHANGE updated_at_new updated_at DATETIME")
            
            # 6. 重建索引
            cursor.execute("ALTER TABLE push_review_log ADD INDEX idx_updated_at (updated_at)")
            
            conn.commit()
            print("迁移完成：push_review_log表的updated_at字段已从BIGINT类型转换为DATETIME类型")
            
    except pymysql.Error as e:
        if conn:
            conn.rollback()
        print(f"迁移失败: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    migrate_push_review_log() 