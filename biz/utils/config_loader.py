"""
配置加载器
用于从环境变量文件加载配置信息
"""

import os
from pathlib import Path
from dotenv import load_dotenv


class ConfigLoader:
    """配置加载器类"""
    
    ENV_FILENAME = ".env"  # 环境变量文件名

    @staticmethod
    def load_env_file(env_file_path=None):
        """
        加载环境变量文件
        如果没有指定路径，默认加载项目根目录下的conf/.env文件
        """
        if env_file_path is None:
            # 获取当前文件所在的目录
            current_dir = Path(__file__).resolve().parent
            # 获取项目根目录
            project_root = current_dir.parent.parent
            # 默认的环境变量文件路径
            env_file_path = project_root / "conf" / ConfigLoader.ENV_FILENAME

        # 加载环境变量文件
        if os.path.exists(env_file_path):
            load_dotenv(env_file_path)
            return True
        return False

    @staticmethod
    def get_db_config():
        """获取数据库配置"""
        # 确保环境变量已加载
        ConfigLoader.load_env_file()
        
        # 从环境变量中获取数据库配置
        db_config = {
            'host': os.environ.get('MYSQL_HOST', 'localhost'),
            'port': int(os.environ.get('MYSQL_PORT', 3306)),
            'user': os.environ.get('MYSQL_USER', 'root'),
            'password': os.environ.get('MYSQL_PASSWORD', 'password'),
            'database': os.environ.get('MYSQL_DATABASE', 'ai_codereview'),
            'charset': os.environ.get('MYSQL_CHARSET', 'utf8mb4'),
            'cursorclass': 'DictCursor'
        }
        return db_config 