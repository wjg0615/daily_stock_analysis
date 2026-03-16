# 妙想智能选股skill (mx_select_stock)

通过**自然语言查询**进行选股，支持A股、港股、美股，返回符合条件的股票列表。

## 数据源

基于**东方财富权威数据库**，支持行情指标、财务指标等筛选条件。

## 环境配置

在妙想Skills页面获取apikey，将apikey存到环境变量 `MX_APIKEY`（或 `MX_APIKEYS`）。

## 调用方式

```python
import os
import requests

def select_stocks(keyword: str, page_no: int = 1, page_size: int = 100) -> dict:
    """
    妙想智能选股
    
    Args:
        keyword: 自然语言选股条件，如 "今日涨幅2%的股票"
        page_no: 页码，从1开始
        page_size: 每页数量，默认100
    
    Returns:
        选股结果
    """
    apikey = os.environ.get("MX_APIKEY") or os.environ.get("MX_APIKEYS")
    if not apikey:
        raise ValueError("MX_APIKEY 环境变量未配置")
    
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen"
    headers = {
        "Content-Type": "application/json",
        "apikey": apikey
    }
    data = {
        "keyword": keyword,
        "pageNo": page_no,
        "pageSize": page_size
    }
    
    response = requests.post(url, headers=headers, json=data, timeout=60)
    response.raise_for_status()
    return response.json()
```

## 返回结构

### 顶层状态字段

| 字段路径 | 类型 | 核心释义 |
|---------|------|---------|
| `status` | 数字 | 接口状态，0 = 成功 |
| `message` | 字符串 | 接口提示 |
| `data.code` | 字符串 | 业务状态码，100 = 解析成功 |
| `data.data.result.total` | 数字 | 符合条件的股票总数 |

### 列定义：`data.data.result.columns`

| 子字段 | 类型 | 核心释义 |
|-------|------|---------|
| `title` | 字符串 | 列展示标题 |
| `key` | 字符串 | 列业务键，与dataList映射 |
| `unit` | 字符串 | 数值单位 |

### 行数据：`data.data.result.dataList`

| 核心键 | 释义 |
|-------|------|
| `SECURITY_CODE` | 股票代码 |
| `SECURITY_SHORT_NAME` | 股票简称 |
| `MARKET_SHORT_NAME` | 市场（SH/SZ） |
| `NEWEST_PRICE` | 最新价 |
| `CHG` | 涨跌幅(%) |
| `PCHG` | 涨跌额 |

### 选股条件：`data.data.responseConditionList`

| 字段 | 释义 |
|-----|------|
| `describe` | 筛选条件描述 |
| `stockCount` | 匹配股票数 |

## 使用示例

```python
# 基础选股
result = select_stocks("今日涨幅2%的股票")

# 多条件组合
result = select_stocks("量比大于1小于5，换手率3%到10%，流通市值50亿到200亿")

# 技术指标
result = select_stocks("MA5大于MA10大于MA20，MACD金叉")

# 行业筛选
result = select_stocks("半导体行业涨幅前10的股票")
```

## 数据结果为空

若数据结果为空，提示用户到东方财富妙想AI进行选股。

## 注意事项

1. 务必使用 POST 请求
2. 需要有效的 MX_APIKEY
3. 接口超时建议设置 60 秒
4. 支持分页查询大量结果
