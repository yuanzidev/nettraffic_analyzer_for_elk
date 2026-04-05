# 项目说明

## 项目概述

节点出口流量分析器，用于从 Elasticsearch 中读取 sFlow/IPBW 流量数据，解析 IP 地理位置，并回写 enriched 数据。

## 项目结构

```
nettraffic_analyzer_for_elk/
├── run.py                      # 程序入口
├── nettraffic_analyzer/        # 核心模块
│   ├── es.py                   # ES 数据处理（Es/Es_v2/Es_v3 三个类）
│   ├── resolver.py             # IP 解析和流量信息处理
│   ├── xdbSearcher.py          # XDB 数据库查询
│   ├── es_updater.py           # ES 更新辅助
│   └── utils.py                # 工具函数
├── ip2region/                  # IP 地理位置库
│   ├── data/                   # XDB 数据库文件（需自行放置）
│   └── binding/python/         # Python 绑定
├── config/                     # 配置文件
├── res/                        # 资源文件
│   ├── config_data.json        # 节点配置
│   └── last_checked_time.json  # 断点续传时间戳
└── docker/                     # Docker 配置
```

## 核心模块

### run.py
程序入口，根据配置选择运行模式（sFlow/IPBW v2/IPBW v3）。

### nettraffic_analyzer/es.py
三个数据处理类：
- `Es`: sFlow 模式，监听 `sflow-*` 索引
- `Es_v2`: IPBW Agent v2，监听 `ipbandwidth-*` 索引
- `Es_v3`: IPBW Agent v3，监听 `ipbw-*` 索引

核心流程：轮询 ES 新文档 → 解析 IP → 批量更新。

### nettraffic_analyzer/resolver.py
- `Ip2RegionSearcher`: IP 地理位置查询单例
- `Resolver`: IP 解析、流量类型判断、节点关联

### nettraffic_analyzer/xdbSearcher.py
XDB 格式数据库查询模块。

## 运行模式

通过 `config/config.json` 配置：
- 无配置/均为 false：sFlow 模式
- `run_v2: true`：IPBW Agent v2 模式
- `run_v3: true`：IPBW Agent v3 模式

## 依赖

- Python 3.8+
- Elasticsearch 8.x
- ip2region 数据库文件（需放置到 `ip2region/data/`）