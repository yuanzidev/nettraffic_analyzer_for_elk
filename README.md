# 节点出口流量分析器

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Elasticsearch](https://img.shields.io/badge/Elasticsearch-8.x-green)](https://www.elastic.co/)

一个用于分析网络节点出口流量的工具，支持 sFlow 和 IPBW Agent 数据采集与分析，帮助网络管理员实时监控和分析网络流量情况。

## 核心功能

### 数据采集支持
- **sFlow 数据处理**：支持标准 sFlow 协议数据采集和分析
- **IPBW Agent 支持**：支持 IPBW Agent v2 和 v3 两种数据格式

### IP 地理位置解析
- 支持 IPv4 和 IPv6 双栈地址解析
- 基于 ip2region 数据库，提供准确的地理位置信息
- 解析信息包括：国家、省份、城市、运营商等

### 流量分析能力
- **流量方向识别**：自动识别入站/出站流量方向
- **运营商判断**：智能判断同网/异网流量，省内/跨省流量
- **节点关联**：自动关联流量所属节点、客户和接口信息
- **流量统计**：支持流量峰值统计和趋势分析

### 性能优化特性
- 多线程并发处理（默认 30 线程）
- 断点续传机制（记录最后处理时间戳）
- 指数退避重试机制（最多 3 次重试）
- IP 信息缓存优化，减少重复查询

## 项目结构

```
nettraffic_analyzer_for_elk/
├── config/                     # 配置文件目录
│   └── sflow.conf              # sFlow 配置文件
├── nettraffic_analyzer/        # 核心代码模块
│   ├── __init__.py             # 模块初始化
│   ├── es.py                   # Elasticsearch 数据处理核心
│   ├── resolver.py             # IP 解析和流量信息处理
│   ├── xdbSearcher.py          # XDB 数据库查询模块
│   ├── es_updater.py           # ES 更新辅助模块
│   └── utils.py                # 工具函数模块
├── ip2region/                  # IP 地理位置数据库
│   ├── data/                   # XDB 数据库文件
│   │   ├── ip2region_v4.xdb    # IPv4 地址库
│   │   └── ip2region_v6.xdb    # IPv6 地址库
│   └── binding/python/         # Python 绑定库
├── docker/                     # Docker 配置
│   └── docker-compose-es-kibana-logstash.yaml
├── es_watcher/                 # ES 监控模块
│   └── es_watcher.py           # Elasticsearch 监控脚本
├── docs/                       # 项目文档
├── res/                        # 资源文件
│   ├── config_data.json        # 节点配置数据
│   ├── sflow_cacti_data.json   # Cacti 监控数据
│   └── last_checked_time.json  # 最后处理时间戳
├── run.py                      # 程序主入口
├── requirements.txt            # Python 依赖
└── README.md                  # 项目说明文档
```

## 核心模块说明

### es.py - 数据处理核心
- `Es`: sFlow 数据处理类，监听 `sflow-*` 索引
- `Es_v2`: IPBW Agent v2 数据处理类，监听 `ipbandwidth-*` 索引
- `Es_v3`: IPBW Agent v3 数据处理类，监听 `ipbw-*` 索引

主要功能：
- 使用 `search_after` 实时获取新文档
- 批量更新文档，添加地理位置和元数据信息
- 支持断点续传，记录最后处理时间戳

### resolver.py - IP 解析模块
- `Ip2RegionSearcher`: IP 地理位置查询单例类
- `Resolver`: IP 解析和流量信息处理类

主要功能：
- 解析 IP 地址的地理位置信息
- 判断流量运营商类型（同网/异网、省内/跨省）
- 关联节点、客户、接口等元数据信息

## 安装部署

### 环境要求
- Python 3.8+
- Elasticsearch 8.x
- ip2region 数据库文件

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd nettraffic_analyzer_for_elk
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **准备 IP 数据库**

将 ip2region 数据库文件放置到 `ip2region/data/` 目录：
- `ip2region_v4.xdb` - IPv4 地址库
- `ip2region_v6.xdb` - IPv6 地址库

4. **配置资源文件**

编辑 `res/config_data.json`，配置节点信息：
```json
[
  {
    "host_ip": "192.168.1.1",
    "interface": "eth0",
    "node": "节点名称",
    "costumer": "客户名称",
    "switch": "交换机接口",
    "agent_ip": "代理IP",
    "flow_direction": "入站/出站"
  }
]
```

5. **配置 Elasticsearch 连接**

在 `nettraffic_analyzer/es.py` 中修改 ES 连接配置：
```python
self.es = Elasticsearch(
    ["http://localhost:9200"],
    basic_auth=("username", "password")
)
```

## 使用方法

### 启动程序
```bash
python run.py
```

### 选择运行模式

在 `config/config.json` 中配置运行模式：
```json
{
  "run_v2": false,  // 使用 IPBW Agent v2 模式
  "run_v3": false   // 使用 IPBW Agent v3 模式
}
```

- 不配置或均为 `false`：使用 sFlow 模式（默认）
- `run_v2: true`：使用 IPBW Agent v2 模式
- `run_v3: true`：使用 IPBW Agent v3 模式

### 数据处理流程

1. 程序启动后，从 Elasticsearch 读取最后处理时间戳
2. 使用 `search_after` 查询该时间戳之后的所有新文档
3. 对每条文档进行以下处理：
   - 解析源 IP 和目的 IP 的地理位置
   - 判断流量类型和运营商
   - 关联节点、客户等元数据
4. 批量更新 Elasticsearch 文档
5. 保存最新时间戳，等待下一轮处理

## 添加的文档字段

处理后的文档会添加以下字段：

### sFlow 模式字段
| 字段名 | 说明 |
|--------|------|
| `flow_isp_type` | 流量类型（同网省内/同网跨省/异网省内/异网跨省）|
| `flow_isp_info` | 目的 IP 运营商信息 |
| `flow_isp_info_src` | 源 IP 运营商信息 |
| `customer` | 客户名称 |
| `node` | 节点名称 |
| `ipType` | IP 类型（ipv4/ipv6）|
| `sw_interface` | 交换机接口 |
| `dst_ip_region` | 目的 IP 地区信息 |
| `src_ip_region` | 源 IP 地区信息 |
| `flow_direction` | 流量方向 |
| `sum_traffic_in_max` | 入站流量峰值 |
| `sum_traffic_out_max` | 出站流量峰值 |
| `sum_traffic_in_avg` | 入站流量平均值 |
| `sum_traffic_out_avg` | 出站流量平均值 |
| `time_period` | 流量时段（晚高峰/闲时）|

### IPBW Agent 模式字段
| 字段名 | 说明 |
|--------|------|
| `host_name` | 主机名 |
| `node` | 节点名称 |
| `customer` | 客户名称 |
| `interface` | 接口名称 |
| `local_ip_region` | 本地 IP 地区 |
| `remote_ip_region` | 远程 IP 地区 |
| `local_ip_isp` | 本地 IP 运营商 |
| `remote_ip_isp` | 远程 IP 运营商 |
| `ipType` | IP 类型 |
| `time_period` | 流量时段（晚高峰/闲时）|

### time_period 字段说明

`time_period` 字段用于标识流量所属的时段，根据时间戳和节点类型自动判断：

| 节点类型 | 晚高峰 | 闲时 |
|---------|-----------------|---------------|
| 联通 (LT) | 20:00-23:00 | 23:00-20:00 |
| 移动 (YD) | 20:00-22:00 | 22:00-20:00 |
| 其他 | - | 闲时 |

## 性能特性

- **并发处理**：默认 30 线程并发，可根据需要调整
- **批量更新**：使用 Elasticsearch Bulk API 提高更新效率
- **智能缓存**：IP 信息缓存，避免重复查询
- **容错机制**：指数退避重试，网络波动时自动恢复
- **断点续传**：记录处理进度，重启后自动继续

## 技术栈

- **语言**：Python 3.8+
- **数据库**：Elasticsearch 8.x
- **IP 库**：ip2region（支持 IPv4/IPv6）
- **并发**：ThreadPoolExecutor
- **日志**：logging 模块

## 许可证

Copyright (c) yuanzi

## 联系方式

- Author: yuanzi
- Website: https://www.yzgsa.com
- Email: yuanzigsa@gmail.com