"""
数据库初始化脚本
用于创建MySQL数据库和所需表结构
"""

import pymysql
from biz.service.db_config import DB_CONFIG
from biz.utils.config_loader import ConfigLoader


def create_database():
    """创建数据库"""
    # 确保环境变量已加载
    ConfigLoader.load_env_file()
    
    # 创建不带数据库名的连接配置
    config = DB_CONFIG.copy()
    db_name = config.pop('database', 'ai_codereview')
    if config.get('cursorclass') == 'DictCursor':
        config['cursorclass'] = pymysql.cursors.DictCursor
    
    try:
        # 连接MySQL服务器(不指定数据库)
        conn = pymysql.connect(**config)
        with conn.cursor() as cursor:
            # 创建数据库
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"数据库 '{db_name}' 创建成功或已存在")
        conn.close()
    except pymysql.Error as e:
        print(f"创建数据库失败: {e}")
        raise


def init_tables():
    """初始化表结构"""
    from biz.service.review_service import ReviewService
    ReviewService.init_db()
    print("表结构初始化完成")


if __name__ == "__main__":
    print("开始初始化数据库...")
    create_database()
    init_tables()
    print("数据库初始化完成!") 