import datetime
import time
from elasticsearch import Elasticsearch
import subprocess
import logging
from datetime import timezone, timedelta
from logging.handlers import TimedRotatingFileHandler
import os
import requests
import re
import threading
import schedule


# Telegram 告警配置
TELEGRAM_API_URL = "https://alert.runyz.com/api/v1/alerts"
TELEGRAM_API_TOKEN = "ah_2JKqxqInFeO1zEnfGaUbDuhMVmLTYznG"
TELEGRAM_BOT_ID = "1"

# 需要清理的索引前缀列表
INDEX_PREFIXES_TO_CLEAN = [
    "cactlyze",
    "ipbandwidth",
    "ipbw",
    "sflow",
    "sflow_cacti",
    "sms"
]

# 索引保留天数
INDEX_RETENTION_DAYS = 75

# 创建logs目录（如果不存在）
if not os.path.exists('logs'):
    os.makedirs('logs')

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)

# 创建文件处理器，每天轮换一次，保留7天的日志
file_handler = TimedRotatingFileHandler(
    filename='logs/es_check.log',
    when='midnight',
    interval=1,
    backupCount=7,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# 添加处理器到logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)


def connect_elasticsearch():
    """
    连接到Elasticsearch服务器
    :return: Elasticsearch客户端实例
    """
    try:
        es = Elasticsearch(
            ["http://localhost:9200"],
            basic_auth=("nettraffic_analyzer", "nettraffic_analyzer")
        )
        if es.ping():
            logger.info("成功连接到ES")
            return es
        else:
            logger.error("无法连接到ES")
            return None
    except Exception as e:
        logger.error(f"连接ES时发生错误: {str(e)}")
        return None


def check_index_updates(es, index_name):
    """
    检查指定索引在最近一分钟内是否有更新
    :param es: Elasticsearch客户端实例
    :param index_name: 要检查的索引名称
    :return: 布尔值，表示是否有更新
    """
    try:
        now = datetime.datetime.utcnow()
        one_minute_ago = now - datetime.timedelta(minutes=1)

        # 构建查询，使用count API只获取数量
        query = {
            "query": {
                "range": {
                    "@timestamp": {
                        "gte": one_minute_ago.isoformat(),
                        "lte": now.isoformat()
                    }
                }
            }
        }

        # 只获取文档数量
        result = es.count(index=index_name, body=query)

        # 如果有匹配的文档，说明有更新
        return result['count'] > 0
    except Exception as e:
        logger.error(f"检查索引更新时发生错误: {str(e)}")
        return False


def send_telegram_alert(title, content, status="failure"):
    """
    发送 Telegram 告警消息
    :param title: 告警标题
    :param content: 告警内容
    :param status: 告警状态，默认为 failure
    """
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {TELEGRAM_API_TOKEN}'
    }
    data = {
        "title": title,
        "content": content,
        "channel": "telegram",
        "status": status,
        "source": "elk-watcher",
        "bot_id": TELEGRAM_BOT_ID
    }
    try:
        response = requests.post(TELEGRAM_API_URL, json=data, headers=headers)
        if response.status_code == 200:
            logger.info("Telegram 告警发送成功")
        else:
            logger.warning(f"Telegram 告警发送失败，状态码: {response.status_code}，正在重试...")
            # 重试发送告警
            retry_count = 10
            for i in range(retry_count):
                time.sleep(2)
                response = requests.post(TELEGRAM_API_URL, json=data, headers=headers)
                if response.status_code == 200:
                    logger.info(f"Telegram 告警重试第{i+1}次成功")
                    break
            else:
                logger.error("重试发送 Telegram 告警失败")
    except Exception as e:
        logger.error(f"发送 Telegram 告警时发生错误: {str(e)}")


def parse_index_date(index_name, prefix):
    """
    从索引名称中解析日期
    :param index_name: 索引名称，如 cactlyze-2025.09.14
    :param prefix: 索引前缀
    :return: datetime对象，如果解析失败返回None
    """
    try:
        # 匹配格式：prefix-YYYY.MM.DD
        pattern = f"^{re.escape(prefix)}-(\d{{4}})\.(\d{{2}})\.(\d{{2}})$"
        match = re.match(pattern, index_name)

        if match:
            year, month, day = match.groups()
            return datetime.datetime(int(year), int(month), int(day))
        return None
    except Exception as e:
        logger.error(f"解析索引日期时发生错误: {index_name}, {str(e)}")
        return None


def cleanup_old_indices(es, dry_run=False):
    """
    清理超过指定天数的旧索引
    :param es: Elasticsearch客户端实例
    :param dry_run: 如果为True，只打印将要删除的索引，不实际删除
    :return: (删除的索引列表, 失败的索引列表)
    """
    if not es:
        logger.error("ES连接不可用，无法执行清理")
        return [], []

    deleted_indices = []
    failed_indices = []
    current_date = datetime.datetime.now()
    cutoff_date = current_date - timedelta(days=INDEX_RETENTION_DAYS)

    logger.info(f"开始清理索引，将删除 {cutoff_date.strftime('%Y-%m-%d')} 之前创建的索引")

    try:
        # 获取所有索引
        all_indices = es.indices.get_alias(index="*")

        for index_name in all_indices:
            # 检查每个前缀
            for prefix in INDEX_PREFIXES_TO_CLEAN:
                if index_name.startswith(prefix + "-"):
                    # 解析索引日期
                    index_date = parse_index_date(index_name, prefix)

                    if index_date and index_date < cutoff_date:
                        if dry_run:
                            logger.info(f"[DRY RUN] 将删除索引: {index_name} (创建日期: {index_date.strftime('%Y-%m-%d')})")
                            deleted_indices.append(index_name)
                        else:
                            try:
                                # 删除索引
                                es.indices.delete(index=index_name)
                                logger.info(f"成功删除索引: {index_name} (创建日期: {index_date.strftime('%Y-%m-%d')})")
                                deleted_indices.append(index_name)
                            except Exception as e:
                                logger.error(f"删除索引 {index_name} 失败: {str(e)}")
                                failed_indices.append(index_name)
                    break  # 已匹配到前缀，不需要继续检查其他前缀

        if not deleted_indices and not failed_indices:
            logger.info("没有找到需要清理的索引")
        else:
            logger.info(f"清理完成，删除了 {len(deleted_indices)} 个索引，失败 {len(failed_indices)} 个")

        return deleted_indices, failed_indices

    except Exception as e:
        logger.error(f"清理索引时发生错误: {str(e)}")
        return deleted_indices, failed_indices


def send_cleanup_notification(deleted_indices, failed_indices):
    """
    发送索引清理结果的 Telegram 通知（仅在失败时发送）
    :param deleted_indices: 成功删除的索引列表
    :param failed_indices: 删除失败的索引列表
    """
    # 只在有失败的索引时才发送告警
    if not failed_indices:
        return

    current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 构建消息内容
    content = f"清理时间: {current_time}\n"
    content += f"清理策略: 删除 {INDEX_RETENTION_DAYS} 天前的索引\n"
    content += f"清理前缀: {', '.join(INDEX_PREFIXES_TO_CLEAN)}\n\n"

    content += f"❌ 删除失败 {len(failed_indices)} 个索引\n"
    for idx in failed_indices:
        content += f"- {idx}\n"
    content += "\n"

    if deleted_indices:
        content += f"✅ 成功删除 {len(deleted_indices)} 个索引\n\n"

    content += f"主机IP: 220.202.54.74"

    # 发送 Telegram 告警
    send_telegram_alert("ELK索引清理失败", content, "failure")


def scheduled_cleanup():
    """
    定时清理任务
    """
    logger.info("执行定时索引清理任务")
    es = connect_elasticsearch()
    if es:
        deleted_indices, failed_indices = cleanup_old_indices(es)
        send_cleanup_notification(deleted_indices, failed_indices)
    else:
        logger.error("无法连接ES，索引清理任务失败")
        send_telegram_alert(
            "ELK索引清理失败",
            f"无法连接到Elasticsearch，索引清理任务执行失败。\n主机IP: 220.202.54.74\n时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "failure"
        )


def run_schedule():
    """
    运行定时任务调度器
    """
    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分钟检查一次是否有任务需要执行


def initial_cleanup():
    """
    启动时执行的初始清理
    """
    logger.info("程序启动，执行初始索引清理")
    es = connect_elasticsearch()
    if es:
        deleted_indices, failed_indices = cleanup_old_indices(es)
        send_cleanup_notification(deleted_indices, failed_indices)
    else:
        logger.error("启动时无法连接ES，跳过初始清理")


def monitor_index_updates(es):
    """
    监控索引更新的主循环
    """
    while True:
        index_name = f"sflow-{datetime.datetime.now(timezone.utc).strftime('%Y.%m.%d')}"
        try:
            if not check_index_updates(es, index_name):
                logger.warning(f"索引 {index_name} 在最近一分钟内没有更新")
                send_telegram_alert(
                    "世捷通新ELK监控告警",
                    f"索引 {index_name} 在最近一分钟内没有更新\n主机IP: 220.202.54.74",
                    "failure"
                )
            else:
                logger.info(f"索引 {index_name} 正常更新中")

            # 等待一分钟
            time.sleep(60)
        except Exception as e:
            logger.error(f"监控过程中发生错误: {str(e)}")
            time.sleep(60)  # 发生错误时也等待一分钟后继续


def main():
    """
    主函数，启动监控和清理任务
    """
    logger.info("==================== 程序启动 ====================")

    # 连接ES
    es = connect_elasticsearch()
    if not es:
        logger.error("无法启动程序，ES连接失败")
        return

    # 执行启动时的初始清理
    initial_cleanup()

    # 设置每天早上6点执行清理任务
    schedule.every().day.at("06:00").do(scheduled_cleanup)
    logger.info("已设置定时任务：每天 06:00 执行索引清理")

    # 启动定时任务线程
    schedule_thread = threading.Thread(target=run_schedule, daemon=True)
    schedule_thread.start()
    logger.info("定时任务调度器已启动")

    # 启动索引监控
    logger.info("开始监控索引更新状态")
    monitor_index_updates(es)


if __name__ == "__main__":
    main()