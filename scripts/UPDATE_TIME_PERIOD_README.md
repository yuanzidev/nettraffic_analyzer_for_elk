# time_period 字段值批量更新脚本

## update_time_period_values.py

批量更新 Elasticsearch 索引中的 `time_period` 字段值，将旧值（off_pk、ev_peak）替换为新值（"闲时"、"晚高峰"）。

## 功能特点

- **断点续传**: 自动保存处理进度，支持中断后继续
- **高效分页**: 使用 `search_after` 避免深分页问题
- **批量更新**: 使用 Elasticsearch Bulk API 批量更新
- **智能过滤**: 只处理包含旧值的文档
- **进度显示**: 实时显示处理进度和预估剩余时间
- **安全退出**: 支持 Ctrl+C 安全中断

## 使用方法

```bash
# 基本用法 (处理所有默认索引)
python scripts/update_time_period_values.py

# 指定索引模式
python scripts/update_time_period_values.py -i sflow-*

# 处理多个索引模式
python scripts/update_time_period_values.py -i sflow-* ipbandwidth-*

# 指定 Elasticsearch 地址
python scripts/update_time_period_values.py --host http://es.example.com:9200

# 调整批次大小 (默认 5000)
python scripts/update_time_period_values.py --batch-size 10000

# 重置进度重新开始
python scripts/update_time_period_values.py --reset
```

## 参数说明

| 参数 | 说明 | 默认值 |
|-----|------|--------|
| `-i, --index` | 索引模式 (支持多个) | sflow-*, ipbandwidth-*, ipbw-* |
| `--host` | ES 地址 | http://localhost:9200 |
| `--user` | ES 用户名 | nettraffic_analyzer |
| `--password` | ES 密码 | nettraffic_analyzer |
| `--batch-size` | 每批文档数 | 5000 |
| `--reset` | 重置进度 | - |

## 更新规则

| 旧值 | 新值 |
|-----|------|
| off_pk | 闲时 |
| ev_peak | 晚高峰 |

## 进度文件

处理进度保存在 `scripts/update_time_period_progress.json`，内容示例：

```json
{
  "processed_indices": {
    "sflow-2026.04.01": {
      "last_update": "2026-04-06T10:30:00+00:00",
      "completed": true,
      "completed_at": "2026-04-06T10:35:00+00:00"
    }
  },
  "total_processed": 150000,
  "start_time": "2026-04-06T10:00:00+00:00"
}
```

## 日志

运行日志保存在 `scripts/update_time_period_values.log`

## 注意事项

1. 该脚本只更新包含旧值（off_pk 或 ev_peak）的文档
2. 如果文档已经是新值，会自动跳过
3. 建议在业务低峰期执行，避免影响 ES 性能
4. 执行前建议先备份重要索引数据
