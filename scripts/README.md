# 历史数据回填脚本

## backfill_time_period.py

为历史数据添加 `time_period` 字段。

### 功能特点

- **断点续传**: 自动保存处理进度，支持中断后继续
- **高效分页**: 使用 `search_after` 避免深分页问题
- **批量更新**: 使用 Elasticsearch Bulk API 批量更新
- **智能跳过**: 只处理缺少 `time_period` 字段的文档
- **进度显示**: 实时显示处理进度和预估剩余时间
- **安全退出**: 支持 Ctrl+C 安全中断

### 使用方法

```bash
# 基本用法 (处理所有默认索引)
python script/backfill_time_period.py

# 指定索引模式
python script/backfill_time_period.py -i sflow-*

# 处理多个索引模式
python script/backfill_time_period.py -i sflow-* ipbandwidth-*

# 指定 Elasticsearch 地址
python script/backfill_time_period.py --host http://es.example.com:9200

# 调整批次大小 (默认 5000)
python script/backfill_time_period.py --batch-size 10000

# 重置进度重新开始
python script/backfill_time_period.py --reset
```

### 参数说明

| 参数 | 说明 | 默认值 |
|-----|------|--------|
| `-i, --index` | 索引模式 (支持多个) | sflow-*, ipbandwidth-*, ipbw-* |
| `--host` | ES 地址 | http://localhost:9200 |
| `--user` | ES 用户名 | nettraffic_analyzer |
| `--password` | ES 密码 | nettraffic_analyzer |
| `--batch-size` | 每批文档数 | 5000 |
| `--reset` | 重置进度 | - |

### 时段规则

| 节点类型 | 晚高峰 | 闲时 |
|---------|-----------------|---------------|
| 联通 (LT) | 20:00-23:00 | 23:00-20:00 |
| 移动 (YD) | 20:00-22:00 | 22:00-20:00 |
| 其他 | - | 闲时 |

### 进度文件

处理进度保存在 `script/backfill_progress.json`，内容示例：

```json
{
  "processed_indices": {
    "sflow-2026.04.01": {
      "last_update": "2026-04-05T10:30:00+00:00",
      "completed": true,
      "completed_at": "2026-04-05T10:35:00+00:00"
    }
  },
  "total_processed": 150000,
  "start_time": "2026-04-05T10:00:00+00:00"
}
```

### 日志

运行日志保存在 `script/backfill_time_period.log`
