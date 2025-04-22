"""
MySQL数据库配置文件
"""

from biz.utils.config_loader import ConfigLoader

# MySQL连接配置
DB_CONFIG = ConfigLoader.get_db_config() 