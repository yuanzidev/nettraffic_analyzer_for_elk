# @Author  : yuanzi
# @Time    : 2024/03/17 14:01
# Website: https://www.yzgsa.com
# Copyright (c) <yuanzigsa@gmail.com>
import json
import logging
from elasticsearch import Elasticsearch, helpers
from datetime import datetime, timedelta, timezone
import time
from dateutil import parser
from nettraffic_analyzer.resolver import Resolver
from concurrent.futures import ThreadPoolExecutor


class Es:
    """
    sflow 数据处理
    """
    def __init__(self, max_workers=30):
        self.logger = logging.getLogger(__name__)
        # 配置 Elasticsearch 客户端
        self.es = Elasticsearch(["http://localhost:9200"], basic_auth=("nettraffic_analyzer", "nettraffic_analyzer"))
        if self.es.ping():
            self.logger.info("成功连接到 Elasticsearch")
        else:
            self.logger.error("无法连接到 Elasticsearch")
            exit(1)
        self.resolver = Resolver()
        self.check_interval = 0.5
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.file_path = "res/last_checked_time.json"



    def get_new_documents(self, es_client, index, timestamp_field, last_time):
        """
        使用 search_after 获取时间戳大于 last_time 的所有新记录
        """
        try:
            all_hits = []
            search_after = None
            batch_size = 10000

            while True:
                query = {
                    "query": {
                        "range": {
                            timestamp_field: {
                                "gt": last_time.isoformat()
                            }
                        }
                    },
                    "sort": [
                        {timestamp_field: "asc"},
                        "_doc"
                    ],
                    "size": batch_size
                }

                # 添加 search_after 参数
                if search_after:
                    query["search_after"] = search_after

                response = es_client.search(index=index, body=query)
                hits = response['hits']['hits']

                if not hits:
                    break

                all_hits.extend(hits)
                
                # 获取最后一个文档的排序值作为下一次查询的 search_after
                search_after = hits[-1]['sort']

                # 可选：添加进度日志
                self.logger.info(f"已获取 {len(all_hits)} 条记录")

            return all_hits

        except Exception as e:
            self.logger.error(f"获取新文档时出错: {e}")
            return []

    def prepare_bulk_update(self, docs):
        """
        根据记录中的字段值，准备 Bulk API 更新操作
        """
        new_docs = self.resolver.rewrite_docs(docs)
        actions = []
        for doc in new_docs:
            source = doc['_source']
            doc_id = doc['_id']
            new_field = {
                "flow_isp_type": source['flow_isp_type'],
                "flow_isp_info": source['flow_isp_info'],
                "flow_isp_info_src": source['flow_isp_info_src'],
                "customer": source['customer'],
                "node": source['node'],
                "ipType": source['ipType'],
                "sw_interface": source['sw_interface'],
                "dst_ip_region": source['dst_ip_region'],
                "src_ip_region": source['src_ip_region'],
                "flow_direction": source['flow_direction'],
                "sum_traffic_in_max": source['sum_traffic_in_max'],
                "sum_traffic_out_max": source['sum_traffic_out_max'],
                "sum_traffic_in_avg": source.get('sum_traffic_in_avg', 0),
                "sum_traffic_out_avg": source.get('sum_traffic_out_avg', 0),
                "time_period": source.get('time_period', '闲时'),
                "src_country": source.get('src_country', '未知'),
                "src_country_code": source.get('src_country_code', 'XX'),
                "dst_country": source.get('dst_country', '未知'),
                "dst_country_code": source.get('dst_country_code', 'XX'),
                "region_type": source.get('region_type', '境内'),
                "hit_sensitive_country": source.get('hit_sensitive_country', False),
            }
            action = {
                "_op_type": "update",
                "_index": doc['_index'],
                "_id": doc_id,
                "doc": new_field
            }
            actions.append(action)
        return actions

    def update_docs(self, docs):
        try:
            start = time.time()

            if docs:
                self.logger.warning(f"找到 {len(docs)} 个新记录，正在处理...")

                # 准备更新操作
                bulk_actions = self.prepare_bulk_update(docs)

                if bulk_actions:
                    # 执行批量更新
                    helpers.bulk(self.es, bulk_actions)
                    self.logger.warning(f"成功更新 {len(bulk_actions)} 个记录。")
                else:
                    self.logger.warning("没有需要更新的记录。")
            else:
                self.logger.warning("没有新记录。")

            self.logger.warning(f"更新完成，耗时：{round(time.time() - start, 2)}s")
        except Exception as e:
            self.logger.error(f"update_docs 运行时发生错误: {e}")

    def save_last_checked_time(self, last_checked_time):
        with open(self.file_path, "w") as f:
            json.dump({"last_checked_time": last_checked_time.isoformat()}, f)

    def load_last_checked_time(self):
        try:
            with open(self.file_path, "r") as f:
                data = json.load(f)
                return parser.isoparse(data["last_checked_time"])
        except FileNotFoundError:
            return datetime.now(timezone.utc) - timedelta(seconds=1)

    def run(self):
        timestamp_field = "@timestamp"
        last_checked_time = self.load_last_checked_time()
        retry_config = {
            'max_retries': 3,
            'initial_delay': 1,  # 初始延迟1秒
            'max_delay': 30,     # 最大延迟30秒
            'backoff_factor': 2  # 指数退避因子
        }

        while True:
            try:
                # 使用 UTC 时间
                index_name = f"sflow-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"
                
                # 使用指数退避的重试机制
                for attempt in range(retry_config['max_retries']):
                    try:
                        # 获取新记录
                        new_docs = self.get_new_documents(
                            es_client=self.es,
                            index=index_name,
                            timestamp_field=timestamp_field,
                            last_time=last_checked_time
                        )

                        if new_docs:
                            # 更新最后一次检查的时间为最新记录的时间
                            latest_time_str = max([doc['_source'][timestamp_field] for doc in new_docs])
                            last_checked_time = parser.isoparse(latest_time_str)
                            # 将最后检查时间写入文件
                            self.save_last_checked_time(last_checked_time)
                            # 提交更新任务到线程池
                            self.executor.submit(self.update_docs, new_docs)
                        else:
                            self.logger.info("没有新的文档需要更新")

                        break  # 成功执行后跳出重试循环

                    except Exception as e:
                        delay = min(
                            retry_config['initial_delay'] * (retry_config['backoff_factor'] ** attempt),
                            retry_config['max_delay']
                        )
                        if attempt < retry_config['max_retries'] - 1:
                            self.logger.warning(f"第 {attempt + 1} 次尝试失败: {e}，{delay} 秒后重试")
                            time.sleep(delay)
                        else:
                            raise

            except Exception as e:
                self.logger.error(f"NettrafficAnalyzer_for_ELK运行发生错误: {e}")

            time.sleep(self.check_interval)

    def shutdown(self):
        self.executor.shutdown(wait=True)


class Es_v2(Es):
    """
    ipbw agent数据处理
    """
    def __init__(self, max_workers=30):
        super().__init__(max_workers)
        self.es = Elasticsearch(["http://localhost:9200"], basic_auth=("nettraffic_analyzer", "nettraffic_analyzer"))

    def prepare_bulk_update(self, docs):
        """
        根据记录中的字段值，准备 Bulk API 更新操作
        """
        new_docs = self.resolver.rewrite_docs_v2(docs)
        actions = []
        for doc in new_docs:
            source = doc['_source']
            doc_id = doc['_id']
            
            new_field = {
                "host_name": source['host_name'],
                "node": source['node'],
                "customer": source['customer'],
                "interface": source['interface'],
                "local_ip_region": source['local_ip_region'],
                "remote_ip_region": source['remote_ip_region'],
                "local_ip_isp": source['local_ip_isp'],
                "remote_ip_isp": source['remote_ip_isp'],
                "local_ip_region_full": source['local_ip_region_full'],
                "remote_ip_region_full": source['remote_ip_region_full'],
                "local_ip_info": source['local_ip_info'],
                "remote_ip_info": source['remote_ip_info'],
                "time_period": source.get('time_period', '闲时'),
            }
            action = {
                "_op_type": "update",
                "_index": doc['_index'],
                "_id": doc_id,
                "doc": new_field
            }
            actions.append(action)
        return actions

    def run(self):
        timestamp_field = "@timestamp"
        last_checked_time = self.load_last_checked_time()
        retry_config = {
            'max_retries': 3,
            'initial_delay': 1,  # 初始延迟1秒
            'max_delay': 30,     # 最大延迟30秒
            'backoff_factor': 2  # 指数退避因子
        }

        while True:
            try:
                # 使用 UTC 时间
                index_name = f"ipbandwidth-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"
                
                # 使用指数退避的重试机制
                for attempt in range(retry_config['max_retries']):
                    try:
                        # 获取新记录
                        new_docs = self.get_new_documents(
                            es_client=self.es,
                            index=index_name,
                            timestamp_field=timestamp_field,
                            last_time=last_checked_time
                        )

                        if new_docs:
                            # 更新最后一次检查的时间为最新记录的时间
                            latest_time_str = max([doc['_source'][timestamp_field] for doc in new_docs])
                            last_checked_time = parser.isoparse(latest_time_str)
                            # 将最后检查时间写入文件
                            self.save_last_checked_time(last_checked_time)
                            # 提交更新任务到线程池
                            self.executor.submit(self.update_docs, new_docs)
                            self.logger.warning(f"找到 {len(new_docs)} 个新记录，正在处理...")
                        else:
                            self.logger.info("没有新的文档需要更新")

                        break  # 成功执行后跳出重试循环

                    except Exception as e:
                        delay = min(
                            retry_config['initial_delay'] * (retry_config['backoff_factor'] ** attempt),
                            retry_config['max_delay']
                        )
                        if attempt < retry_config['max_retries'] - 1:
                            self.logger.warning(f"第 {attempt + 1} 次尝试失败: {e}，{delay} 秒后重试")
                            time.sleep(delay)
                        else:
                            raise

            except Exception as e:
                self.logger.error(f"NettrafficAnalyzer_for_ELK运行发生错误: {e}")

            time.sleep(self.check_interval)



class Es_v3(Es):
    """
    ipbw agent数据处理
    """
    def __init__(self, max_workers=30):
        super().__init__(max_workers)
        self.es = Elasticsearch(["http://localhost:9200"], basic_auth=("nettraffic_analyzer", "nettraffic_analyzer"))

    def prepare_bulk_update(self, docs):
        """
        根据记录中的字段值，准备 Bulk API 更新操作
        """
        new_docs = self.resolver.rewrite_docs_v3(docs)
        actions = []
        for doc in new_docs:
            source = doc['_source']
            doc_id = doc['_id']
            
            new_field = {
                "host_name": source['host_name'],
                "node": source['node'],
                "customer": source['customer'],
                "interface": source['interface'],
                "local_ip_region": source['local_ip_region'],
                "local_ip_info": source['local_ip_info'],
                "time_period": source.get('time_period', '闲时'),
            }
            action = {
                "_op_type": "update",
                "_index": doc['_index'],
                "_id": doc_id,
                "doc": new_field
            }
            actions.append(action)
        return actions

    def run(self):
        timestamp_field = "event_timestamp"
        last_checked_time = self.load_last_checked_time()
        retry_config = {
            'max_retries': 3,
            'initial_delay': 1,  # 初始延迟1秒
            'max_delay': 30,     # 最大延迟30秒
            'backoff_factor': 2  # 指数退避因子
        }

        while True:
            try:
                # 使用 UTC 时间
                index_name = f"ipbw-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"
                
                # 使用指数退避的重试机制
                for attempt in range(retry_config['max_retries']):
                    try:
                        # 获取新记录
                        new_docs = self.get_new_documents(
                            es_client=self.es,
                            index=index_name,
                            timestamp_field=timestamp_field,
                            last_time=last_checked_time
                        )

                        if new_docs:
                            # 更新最后一次检查的时间为最新记录的时间
                            latest_time_str = max([doc['_source'][timestamp_field] for doc in new_docs])
                            last_checked_time = parser.isoparse(latest_time_str)
                            # 将最后检查时间写入文件
                            self.save_last_checked_time(last_checked_time)
                            # 提交更新任务到线程池
                            self.executor.submit(self.update_docs, new_docs)
                            self.logger.warning(f"找到 {len(new_docs)} 个新记录，正在处理...")
                        else:
                            self.logger.info("没有新的文档需要更新")

                        break  # 成功执行后跳出重试循环

                    except Exception as e:
                        delay = min(
                            retry_config['initial_delay'] * (retry_config['backoff_factor'] ** attempt),
                            retry_config['max_delay']
                        )
                        if attempt < retry_config['max_retries'] - 1:
                            self.logger.warning(f"第 {attempt + 1} 次尝试失败: {e}，{delay} 秒后重试")
                            time.sleep(delay)
                        else:
                            raise

            except Exception as e:
                self.logger.error(f"NettrafficAnalyzer_for_ELK运行发生错误: {e}")

            time.sleep(self.check_interval)