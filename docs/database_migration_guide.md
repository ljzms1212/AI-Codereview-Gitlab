# 数据库迁移指南

## push_review_log 表的 updated_at 字段类型迁移

### 背景

将 `push_review_log` 表中的 `updated_at` 字段从 `BIGINT` 类型转换为 `DATETIME` 类型，以便更好地存储和查询时间信息。

### 迁移步骤

1. 备份数据库（重要）

    ```sql
    mysqldump -u [用户名] -p [数据库名] > backup_before_migration.sql
    ```

2. 执行迁移脚本

    ```bash
    python -m biz.scripts.migrate_push_review_log
    ```

3. 验证迁移结果

    ```sql
    DESCRIBE push_review_log;
    SELECT id, updated_at FROM push_review_log LIMIT 10;
    ```

### 迁移内容

迁移脚本会执行以下操作：

1. 检查 `push_review_log` 表是否存在
2. 检查 `updated_at` 字段是否为 `DATETIME` 类型，如果已经是则不做任何操作
3. 创建临时字段 `updated_at_new`
4. 将原 `updated_at` 字段的时间戳值转换为 `DATETIME` 类型并存入临时字段
5. 删除原字段并将临时字段重命名为 `updated_at`
6. 重建索引

### 注意事项

- 迁移过程中可能会短暂锁表，建议在非高峰期进行
- 如果数据量较大，迁移可能需要一定时间
- 如果迁移过程中出现问题，可以使用备份的数据进行恢复

### 相关代码修改

- `biz/service/review_service.py` 文件中已更新表结构定义和相关操作逻辑
- `biz/entity/review_entity.py` 文件中已增加 `timestamp_to_datetime` 方法

如果您在迁移过程中遇到任何问题，请联系系统管理员。 