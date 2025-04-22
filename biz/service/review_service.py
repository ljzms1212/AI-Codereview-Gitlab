import pymysql
import pandas as pd
from pymysql.cursors import DictCursor

from biz.entity.review_entity import MergeRequestReviewEntity, PushReviewEntity
from biz.service.db_config import DB_CONFIG


class ReviewService:
    @staticmethod
    def get_connection():
        """获取数据库连接"""
        config = DB_CONFIG.copy()
        if config.get('cursorclass') == 'DictCursor':
            config['cursorclass'] = pymysql.cursors.DictCursor
        return pymysql.connect(**config)

    @staticmethod
    def init_db():
        """初始化数据库及表结构"""
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
                        updated_at BIGINT,
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
            print(f"数据库初始化失败: {e}")
        finally:
            if conn:
                conn.close()

    @staticmethod
    def insert_mr_review_log(entity: MergeRequestReviewEntity):
        """插入合并请求审核日志"""
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
            print(f"插入审核日志失败: {e}")
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_mr_review_logs(authors: list = None, project_names: list = None, updated_at_gte: int = None,
                           updated_at_lte: int = None) -> pd.DataFrame:
        """获取符合条件的合并请求审核日志"""
        try:
            conn = ReviewService.get_connection()
            query = """
                SELECT project_name, author, source_branch, target_branch, updated_at, commit_messages, score, url, review_result
                FROM mr_review_log
                WHERE 1=1
            """
            params = []

            if authors:
                placeholders = ','.join(['%s'] * len(authors))
                query += f" AND author IN ({placeholders})"
                params.extend(authors)

            if project_names:
                placeholders = ','.join(['%s'] * len(project_names))
                query += f" AND project_name IN ({placeholders})"
                params.extend(project_names)

            if updated_at_gte is not None:
                query += " AND updated_at >= %s"
                params.append(updated_at_gte)

            if updated_at_lte is not None:
                query += " AND updated_at <= %s"
                params.append(updated_at_lte)
                
            query += " ORDER BY updated_at DESC"
            
            # 使用pandas读取SQL查询结果
            df = pd.read_sql(query, conn, params=params)
            return df
        except pymysql.Error as e:
            print(f"获取审核日志失败: {e}")
            return pd.DataFrame()
        finally:
            if conn:
                conn.close()

    @staticmethod
    def insert_push_review_log(entity: PushReviewEntity):
        """插入推送审核日志"""
        try:
            conn = ReviewService.get_connection()
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO push_review_log 
                    (project_name, author, branch, updated_at, commit_messages, score, review_result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (
                    entity.project_name, entity.author, entity.branch,
                    entity.updated_at, entity.commit_messages, entity.score,
                    entity.review_result
                ))
                conn.commit()
        except pymysql.Error as e:
            print(f"插入推送审核日志失败: {e}")
        finally:
            if conn:
                conn.close()

    @staticmethod
    def get_push_review_logs(authors: list = None, project_names: list = None, updated_at_gte: int = None,
                             updated_at_lte: int = None) -> pd.DataFrame:
        """获取符合条件的推送审核日志"""
        try:
            conn = ReviewService.get_connection()
            query = """
                SELECT project_name, author, branch, updated_at, commit_messages, score, review_result
                FROM push_review_log
                WHERE 1=1
            """
            params = []

            if authors:
                placeholders = ','.join(['%s'] * len(authors))
                query += f" AND author IN ({placeholders})"
                params.extend(authors)

            if project_names:
                placeholders = ','.join(['%s'] * len(project_names))
                query += f" AND project_name IN ({placeholders})"
                params.extend(project_names)

            if updated_at_gte is not None:
                query += " AND updated_at >= %s"
                params.append(updated_at_gte)

            if updated_at_lte is not None:
                query += " AND updated_at <= %s"
                params.append(updated_at_lte)
                
            query += " ORDER BY updated_at DESC"
            
            # 使用pandas读取SQL查询结果
            df = pd.read_sql(query, conn, params=params)
            return df
        except pymysql.Error as e:
            print(f"获取推送审核日志失败: {e}")
            return pd.DataFrame()
        finally:
            if conn:
                conn.close()


# 初始化数据库
ReviewService.init_db()
