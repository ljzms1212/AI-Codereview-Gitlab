import pymysql
import pandas as pd
from pymysql.cursors import DictCursor
from sqlalchemy import create_engine, text
import datetime
import os
from dotenv import load_dotenv

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.service.db_config import DB_CONFIG
from biz.utils.log import logger

# 加载环境变量
load_dotenv("conf/.env")

# 获取配置
SAVE_REVIEW_TO_DB = os.getenv('SAVE_REVIEW_TO_DB', 'false').lower() == 'true'

class ReviewService:
    @staticmethod
    def get_connection():
        """获取数据库连接"""
        config = DB_CONFIG.copy()
        if config.get('cursorclass') == 'DictCursor':
            config['cursorclass'] = pymysql.cursors.DictCursor
        return pymysql.connect(**config)
    
    @staticmethod
    def get_sqlalchemy_engine():
        """获取SQLAlchemy引擎"""
        config = DB_CONFIG.copy()
        if 'cursorclass' in config:
            del config['cursorclass']
        
        connection_string = (
            f"mysql+pymysql://{config['user']}:{config['password']}@"
            f"{config['host']}:{config['port']}/{config['database']}?charset={config['charset']}"
        )
        return create_engine(connection_string)

    @staticmethod
    def init_db():
        """初始化数据库及表结构"""
        if not SAVE_REVIEW_TO_DB:
            logger.info("SAVE_REVIEW_TO_DB=false, 跳过数据库初始化")
            return
            
        try:
            conn = ReviewService.get_connection()
            with conn.cursor() as cursor:
                # 创建MR审核日志表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mr_review_log (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        project_name VARCHAR(255),
                        author VARCHAR(100),
                        source_branch VARCHAR(255),
                        target_branch VARCHAR(255),
                        updated_at BIGINT,
                        commit_messages TEXT,
                        score INT,
                        url VARCHAR(255),
                        review_result TEXT,
                        INDEX idx_author (author),
                        INDEX idx_project (project_name),
                        INDEX idx_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                
                # 创建Push审核日志表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS push_review_log (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        project_name VARCHAR(255),
                        author VARCHAR(100),
                        branch VARCHAR(255),
                        updated_at DATETIME,
                        commit_messages TEXT,
                        score INT,
                        review_result TEXT,
                        INDEX idx_author (author),
                        INDEX idx_project (project_name),
                        INDEX idx_updated_at (updated_at)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                ''')
                conn.commit()
        except pymysql.Error as e:
            logger.error(f"数据库初始化失败: {e}")
        finally:
            if conn:
                conn.close()

    @staticmethod
    def insert_mr_review_log(entity: MergeRequestReviewEntity):
        """插入合并请求审核日志"""
        if not SAVE_REVIEW_TO_DB:
            logger.info("SAVE_REVIEW_TO_DB=false, 跳过保存 MR 评审结果")
            return
            
        try:
            conn = ReviewService.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO mr_review_log 
                    (project_name, author, source_branch, target_branch, updated_at, commit_messages, score, url, review_result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    entity.project_name, entity.author, entity.source_branch,
                    entity.target_branch, entity.updated_at, entity.commit_messages, 
                    entity.score, entity.url, entity.review_result
                ))
                conn.commit()
        except pymysql.Error as e:
            logger.error(f"插入审核日志失败: {e}")
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_mr_review_logs(authors: list = None, project_names: list = None, updated_at_gte: int = None,
                           updated_at_lte: int = None) -> pd.DataFrame:
        """获取符合条件的合并请求审核日志"""
        try:
            engine = ReviewService.get_sqlalchemy_engine()
            query = """
                SELECT project_name, author, source_branch, target_branch, updated_at, commit_messages, score, url, review_result
                FROM mr_review_log
                WHERE 1=1
            """
            params = {}
            param_index = 0

            if authors:
                placeholders = ','.join([f':author{i}' for i in range(len(authors))])
                query += f" AND author IN ({placeholders})"
                for i, author in enumerate(authors):
                    params[f'author{i}'] = author

            if project_names:
                placeholders = ','.join([f':project{i}' for i in range(len(project_names))])
                query += f" AND project_name IN ({placeholders})"
                for i, project in enumerate(project_names):
                    params[f'project{i}'] = project

            if updated_at_gte is not None:
                query += " AND updated_at >= :updated_at_gte"
                params['updated_at_gte'] = updated_at_gte

            if updated_at_lte is not None:
                query += " AND updated_at <= :updated_at_lte"
                params['updated_at_lte'] = updated_at_lte
                
            query += " ORDER BY updated_at DESC"
            
            # 使用pandas读取SQL查询结果，使用SQLAlchemy引擎
            df = pd.read_sql(text(query), engine, params=params)
            
            # 确保score列为数值类型
            if 'score' in df.columns and not df.empty:
                df['score'] = pd.to_numeric(df['score'], errors='coerce')
                
            return df
        except Exception as e:
            print(f"获取审核日志失败: {e}")
            return pd.DataFrame()

    @staticmethod
    def insert_push_review_log(entity: PushReviewEntity):
        """插入推送审核日志"""
        if not SAVE_REVIEW_TO_DB:
            logger.info("SAVE_REVIEW_TO_DB=false, 跳过保存 Push 评审结果")
            return
            
        try:
            conn = ReviewService.get_connection()
            with conn.cursor() as cursor:
                # 将时间戳转换为datetime对象
                updated_at_datetime = datetime.datetime.fromtimestamp(entity.updated_at)
                cursor.execute('''
                    INSERT INTO push_review_log 
                    (project_name, author, branch, updated_at, commit_messages, score, review_result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (
                    entity.project_name, entity.author, entity.branch,
                    updated_at_datetime, entity.commit_messages, entity.score,
                    entity.review_result
                ))
                conn.commit()
        except pymysql.Error as e:
            logger.error(f"插入推送审核日志失败: {e}")
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_push_review_logs(authors: list = None, project_names: list = None, updated_at_gte: int = None,
                             updated_at_lte: int = None) -> pd.DataFrame:
        """获取符合条件的推送审核日志"""
        try:
            engine = ReviewService.get_sqlalchemy_engine()
            query = """
                SELECT id, project_name, author, branch, updated_at, commit_messages, score, review_result
                FROM push_review_log
                WHERE 1=1
            """
            params = {}

            if authors:
                placeholders = ','.join([f':author{i}' for i in range(len(authors))])
                query += f" AND author IN ({placeholders})"
                for i, author in enumerate(authors):
                    params[f'author{i}'] = author

            if project_names:
                placeholders = ','.join([f':project{i}' for i in range(len(project_names))])
                query += f" AND project_name IN ({placeholders})"
                for i, project in enumerate(project_names):
                    params[f'project{i}'] = project

            if updated_at_gte is not None:
                # 将时间戳转换为datetime对象
                updated_at_gte_datetime = datetime.datetime.fromtimestamp(updated_at_gte)
                query += " AND updated_at >= :updated_at_gte"
                params['updated_at_gte'] = updated_at_gte_datetime

            if updated_at_lte is not None:
                # 将时间戳转换为datetime对象
                updated_at_lte_datetime = datetime.datetime.fromtimestamp(updated_at_lte)
                query += " AND updated_at <= :updated_at_lte"
                params['updated_at_lte'] = updated_at_lte_datetime
                
            query += " ORDER BY updated_at DESC"
            
            # 使用pandas读取SQL查询结果，使用SQLAlchemy引擎和text()函数
            df = pd.read_sql(text(query), engine, params=params)
            
            # 确保score列为数值类型
            if 'score' in df.columns and not df.empty:
                df['score'] = pd.to_numeric(df['score'], errors='coerce')
                
            # 添加格式化后的时间列
            if 'updated_at' in df.columns and not df.empty:
                df['updated_at_format'] = df['updated_at'].apply(
                    lambda dt: dt.strftime('%Y-%m-%d %H:%M:%S') if isinstance(dt, datetime.datetime) else str(dt)
                )
                
            return df
        except Exception as e:
            print(f"获取推送审核日志失败: {e}")
            return pd.DataFrame()

    @staticmethod
    def get_push_review_result_by_id(review_id: int) -> dict:
        """根据ID获取Push评审结果"""
        try:
            conn = ReviewService.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    SELECT id, project_name, author, branch, updated_at, commit_messages, score, review_result
                    FROM push_review_log
                    WHERE id = %s
                ''', (review_id,))
                result = cursor.fetchone()
                
                if result:
                    # 保存原始的日期时间字符串
                    original_updated_at = result['updated_at']
                    
                    # 处理datetime类型，转为标准格式字符串
                    if isinstance(result['updated_at'], datetime.datetime):
                        result['updated_at'] = result['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
                    
                    # 添加格式化后的时间字段
                    result['updated_at_format'] = result['updated_at']
                        
                    return result
                return None
        except pymysql.Error as e:
            print(f"获取评审结果失败: {e}")
            return None
        finally:
            if conn:
                conn.close()


# 初始化数据库
ReviewService.init_db()
