# IP2Region 使用指南

## 数据库文件

- `data/ip2region_v4.xdb` - IPv4 数据库
- `data/ip2region_v6.xdb` - IPv6 数据库

## 返回格式

```
国家|省份|城市|ISP|国家代码
```

示例：`中国|广东省|深圳市|中国电信|CN`

---

## Go 语言使用

### 方式一：命令行工具

```bash
cd binding/golang
go build -o ip2region_searcher

# 交互式查询（支持 IPv4 和 IPv6）
./ip2region_searcher search

# 指定数据库路径
./ip2region_searcher search --v4-db=../../data/ip2region_v4.xdb --v6-db=../../data/ip2region_v6.xdb
```

### 方式二：代码集成

```go
package main

import (
    "fmt"
    "github.com/lionsoul2014/ip2region/binding/golang/service"
)

func main() {
    // 创建配置（缓存策略: NoCache, VIndexCache, BufferCache）
    v4Config, _ := service.NewV4Config(service.VIndexCache, "data/ip2region_v4.xdb", 10)
    v6Config, _ := service.NewV6Config(service.VIndexCache, "data/ip2region_v6.xdb", 10)
    
    // 创建查询服务
    ip2region, _ := service.NewIp2Region(v4Config, v6Config)
    defer ip2region.Close()
    
    // 查询 IP
    region, _ := ip2region.SearchByStr("113.57.121.9")
    fmt.Println(region)
    // 输出: 中国|湖北省|武汉市|中国联通|CN
    
    region, _ = ip2region.SearchByStr("2001:250::1")
    fmt.Println(region)
    // 输出: 中国|北京市|北京市|中国教育网|CN
}
```

### 缓存策略说明

| 策略 | 内存占用 | 查询速度 | 说明 |
|------|----------|----------|------|
| `NoCache` | 无 | 较慢 | 每次查询都读取文件 |
| `VIndexCache` | ~512KB | 快 | 缓存向量索引（推荐） |
| `BufferCache` | ~数据库大小 | 最快 | 缓存整个数据库到内存 |

---

## Python 使用

### 安装

```bash
cd binding/python
pip install .
```

### 方式一：命令行工具

```bash
# 查询 IPv4
python search_test.py --db=../../data/ip2region_v4.xdb

# 查询 IPv6
python search_test.py --db=../../data/ip2region_v6.xdb

# 指定缓存策略
python search_test.py --db=../../data/ip2region_v4.xdb --cache-policy=vectorIndex
```

### 方式二：代码集成

```python
import io
import ip2region.util as util
import ip2region.searcher as xdb

def create_searcher(db_path):
    handle = io.open(db_path, "rb")
    header = util.load_header(handle)
    version = util.version_from_header(header)
    v_index = util.load_vector_index(handle)
    searcher = xdb.new_with_vector_index(version, db_path, v_index)
    handle.close()
    return searcher

# 查询 IPv4
searcher = create_searcher("data/ip2region_v4.xdb")
ip_bytes = util.parse_ip("113.57.121.9")
print(searcher.search(ip_bytes))
# 输出: 中国|湖北省|武汉市|中国联通|CN
searcher.close()

# 查询 IPv6
searcher = create_searcher("data/ip2region_v6.xdb")
ip_bytes = util.parse_ip("2001:250::1")
print(searcher.search(ip_bytes))
# 输出: 中国|北京市|北京市|中国教育网|CN
searcher.close()
```

### 缓存策略说明

| 策略 | 内存占用 | 查询速度 |
|------|----------|----------|
| `file` | 无 | 较慢 |
| `vectorIndex` | ~512KB | 快（推荐） |
| `content` | ~数据库大小 | 最快 |

---

## 查询示例

| IP | 结果 |
|----|------|
| `113.57.121.9` | `中国\|湖北省\|武汉市\|中国联通\|CN` |
| `1.0.1.1` | `中国\|福建省\|福州市\|中国电信\|CN` |
| `2001:250::1` | `中国\|北京市\|北京市\|中国教育网\|CN` |
| `240e:3b7:3273:51d0::1` | `中国\|广东省\|深圳市\|中国电信\|CN` |