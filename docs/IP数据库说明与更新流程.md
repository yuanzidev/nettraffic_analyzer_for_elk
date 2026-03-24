# IP 数据库说明与全盘更新流程

> 整理时间：2026-03-13

---

## 一、IPv4 数据库

### 存储形式

- **类型**：XDB 二进制文件
- **代码引用路径**：`res/china.xdb`
- **实际文件**：`res/dizhihui_ipv4_china_mainland_city_level.xdb`
- **加载方式**：程序启动时通过 `xdbSearcher.py` 整体加载到内存（`loadContentFromFile`），查询时做内存二分搜索

> **注意**：代码引用的文件名（`china.xdb`）与磁盘上实际文件名（`dizhihui_ipv4_china_mainland_city_level.xdb`）不一致，需确认是否存在软链接或是代码引用错误。

### 查询结果格式

返回以 `|` 分隔的字符串，代码通过位置索引取值：

| 索引 | 字段含义 | 代码 key |
|------|----------|----------|
| `[0]` | 运营商 | `isp` |
| `[4]` | 区县 | `district` |
| `[7]` | 省份 | `province` |
| `[9]` | 城市 | `city` |

示例：`中国移动|...|...|...|海淀区|...|...|北京市|...|北京|...`

---

## 二、IPv6 数据库

### 存储形式

- **类型**：MySQL 关系型数据库
- **数据库名**：`ipv6`（可通过 `config/config.json` 中的 `db_database` 字段配置）
- **表名**：`ipv6_china_mainland`
- **查询方式**：通过 `INET6_ATON()` 对 `ip_dig_min_bin` / `ip_dig_max_bin` 做二进制 IP 段范围查询

```sql
SELECT *
FROM ipv6_china_mainland
WHERE
    ip_dig_min_bin <= INET6_ATON(%s)
    AND ip_dig_max_bin >= INET6_ATON(%s)
ORDER BY ip_dig_min_bin DESC
LIMIT 1;
```

### 表字段说明

代码通过 `SELECT *` 返回的 tuple 按位置索引取值，关键列如下：

| 索引 | 列名 | 字段含义 | 代码 key |
|------|------|----------|----------|
| WHERE | `ip_dig_min_bin` | IP 段起始（二进制） | — |
| WHERE | `ip_dig_max_bin` | IP 段结束（二进制） | — |
| `[6]` | 运营商列 | ISP 名称 | `isp` |
| `[13]` | 省份列 | 省份 | `province` |
| `[15]` | 城市列 | 城市 | `city` |

> **注意**：IPv6 数据无区县（`district`）字段，代码中已注释说明。

---

## 三、全盘更新流程

### 3.1 IPv4 更新（XDB 文件替换）

XDB 为只读二进制文件，全盘更新即**文件替换**，无需操作数据库。

```bash
# 1. 停止程序
# 2. 备份旧文件
cp res/china.xdb res/china.xdb.bak

# 3. 将新 xdb 文件放入 res/ 目录并命名为 china.xdb
cp /path/to/new.xdb res/china.xdb

# 4. 验证：抽查几个 IP，确认字段位置一致
#    parts[0]=ISP  parts[4]=区县  parts[7]=省份  parts[9]=城市

# 5. 重启程序
```

### 3.2 IPv6 更新（MySQL 表全量替换）

推荐使用"先导入临时表、验证后原子切换"的方式，避免中途失败导致数据为空。

```bash
# 第一步：备份旧表
mysqldump -u root -p ipv6 ipv6_china_mainland > ipv6_backup_$(date +%Y%m%d).sql
```

```sql
-- 第二步：创建临时表（与正式表结构相同）
CREATE TABLE ipv6_china_mainland_new LIKE ipv6_china_mainland;

-- 导入新数据（根据实际数据源选择方式）
-- 方式一：从 SQL 文件导入
SOURCE /path/to/new_data.sql;
-- 方式二：从 CSV 导入
LOAD DATA INFILE '/path/to/new_data.csv'
    INTO TABLE ipv6_china_mainland_new
    ...;

-- 第三步：验证临时表数据
SELECT COUNT(*) FROM ipv6_china_mainland_new;
SELECT * FROM ipv6_china_mainland_new LIMIT 5;
-- 重点核查：ip_dig_min_bin/ip_dig_max_bin 是否正确，索引 [6][13][15] 对应字段是否符合预期

-- 第四步：原子切换（停止程序写入后执行）
RENAME TABLE
    ipv6_china_mainland     TO ipv6_china_mainland_old,
    ipv6_china_mainland_new TO ipv6_china_mainland;

-- 第五步：验证正式表查询正常后删除旧表
DROP TABLE ipv6_china_mainland_old;
```

---

## 四、更新前必须核查的事项

| # | 检查项 | 说明 |
|---|--------|------|
| 1 | IPv4 XDB 文件名一致性 | 确认代码引用的 `res/china.xdb` 与实际文件名是否匹配 |
| 2 | 新 XDB 字段位置是否不变 | 代码用硬编码索引 `[0][4][7][9]`，字段顺序改变会导致取值错误 |
| 3 | 新 IPv6 数据列顺序是否不变 | 代码用硬编码索引 `[6][13][15]`，列顺序改变同样会导致取值错误 |
| 4 | `ip_dig_min_bin` / `ip_dig_max_bin` 类型 | 需与 `INET6_ATON()` 返回类型匹配（VARBINARY） |
| 5 | 切换期间程序是否暂停写入 | `RENAME TABLE` 是原子操作，但建议在维护窗口执行 |
