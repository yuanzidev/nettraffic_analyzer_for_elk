#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @Author  : yuanzi
# @Time    : 2026/04/06
# Description: 批量更新 time_period 字段值（off_pk -> 闲时, ev_peak -> 晚高峰）

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from dateutil import parser

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from elasticsearch import Elasticsearch
from concurrent.futures import ThreadPoolExecutor, as_completed
import signal

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('update_time_period_values.log')
    ]
)
logger = logging.getLogger(__name__)


class ProgressTracker:
    """进度跟踪器，支持断点续传"""

    def __init__(self, progress_file='update_time_period_progress.json'):
        self.progress_file = progress_file
        self.progress = self._load_progress()

    def _load_progress(self):
        """加载进度"""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载进度文件失败: {e}")
        return {
            'processed_indices': {},
            'last_search_after': None,
            'total_processed': 0,
            'start_time': None
        }

    def save_progress(self, index, search_after=None, processed_count=0):
        """保存进度"""
        self.progress['processed_indices'][index] = {
            'last_update': datetime.now(timezone.utc).isoformat(),
            'search_after': search_after
        }
        self.progress['total_processed'] += processed_count
        self.progress['last_search_after'] = search_after
        if not self.progress['start_time']:
            self.progress['start_time'] = datetime.now(timezone.utc).isoformat()

        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def get_index_progress(self, index):
        """获取索引的处理进度"""
        return self.progress['processed_indices'].get(index)

    def is_index_completed(self, index):
        """检查索引是否已完成"""
        return self.progress['processed_indices'].get(index, {}).get('completed', False)

    def mark_index_completed(self, index):
        """标记索引已完成"""
        if index not in self.progress['processed_indices']:
            self.progress['processed_indices'][index] = {}
        self.progress['processed_indices'][index]['completed'] = True
        self.progress['processed_indices'][index]['completed_at'] = datetime.now(timezone.utc).isoformat()

        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)


class TimePeriodValueUpdater:
    """time_period 字段值更新工具"""

    def __init__(self, es_host='http://localhost:9200', es_user='nettraffic_analyzer',
                 es_password='nettraffic_analyzer', batch_size=5000, max_workers=4):
        self.es = Elasticsearch([es_host], basic_auth=(es_user, es_password))
        self.batch_size = batch_size
        self.max_workers = max_workers
        self.stats = {
            'total_fetched': 0,
            'total_updated': 0,
            'total_skipped': 0,
            'total_failed': 0
        }
        self._shutdown = False

        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """处理中断信号"""
        logger.info("收到中断信号，正在安全退出...")
        self._shutdown = True

    def get_new_time_period_value(self, old_value):
        """
        获取新的 time_period 值

        Args:
            old_value: 旧值（off_pk 或 ev_peak）

        Returns:
            str: 新值（"闲时" 或 "晚高峰"）
        """
        value_mapping = {
            'off_pk': '闲时',
            'ev_peak': '晚高峰'
        }
        return value_mapping.get(old_value, old_value)

    def get_indices(self, pattern):
        """获取匹配模式的索引列表"""
        try:
            response = self.es.cat.indices(index=pattern, format='json')
            indices = [item['index'] for item in response]
            # 按索引名排序
            indices.sort()
            return indices
        except Exception as e:
            logger.error(f"获取索引列表失败: {e}")
            return []

    def count_docs_need_update(self, index):
        """统计需要更新的文档数量"""
        try:
            query = {
                "query": {
                    "bool": {
                        "should": [
                            {"term": {"time_period": "off_pk"}},
                            {"term": {"time_period": "ev_peak"}}
                        ]
                    }
                }
            }
            response = self.es.count(index=index, body=query)
            return response['count']
        except Exception as e:
            logger.error(f"统计索引 {index} 需要更新的文档数失败: {e}")
            return 0

    def fetch_docs(self, index, search_after=None):
        """
        获取需要更新 time_period 值的文档
        使用 search_after 实现高效分页
        """
        query = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"time_period": "off_pk"}},
                        {"term": {"time_period": "ev_peak"}}
                    ]
                }
            },
            "sort": [
                {"@timestamp": "asc"},
                "_doc"
            ],
            "size": self.batch_size
        }

        if search_after:
            query["search_after"] = search_after

        try:
            response = self.es.search(index=index, body=query)
            hits = response['hits']['hits']
            return hits
        except Exception as e:
            logger.error(f"查询索引 {index} 失败: {e}")
            return []

    def prepare_bulk_actions(self, docs):
        """准备批量更新操作"""
        actions = []
        for doc in docs:
            source = doc['_source']
            doc_id = doc['_id']
            index = doc['_index']

            old_time_period = source.get('time_period', '')
            new_time_period = self.get_new_time_period_value(old_time_period)

            # 如果值没有变化，跳过
            if old_time_period == new_time_period:
                continue

            action = {
                "_op_type": "update",
                "_index": index,
                "_id": doc_id,
                "doc": {
                    "time_period": new_time_period
                }
            }
            actions.append(action)

        return actions

    def bulk_update(self, actions):
        """批量更新文档"""
        if not actions:
            return 0, 0

        from elasticsearch import helpers

        try:
            success_count = 0
            failed_count = 0

            for success, info in helpers.parallel_bulk(
                self.es,
                actions,
                chunk_size=1000,
                raise_on_error=False,
                raise_on_exception=False
            ):
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    logger.debug(f"更新失败: {info}")

            return success_count, failed_count

        except Exception as e:
            logger.error(f"批量更新失败: {e}")
            return 0, len(actions)

    def process_index(self, index, progress_tracker):
        """
        处理单个索引
        返回 (成功数, 失败数)
        """
        # 检查索引是否已完成
        if progress_tracker.is_index_completed(index):
            logger.info(f"索引 {index} 已完成，跳过")
            return 0, 0

        # 获取上次处理的进度
        index_progress = progress_tracker.get_index_progress(index)
        search_after = index_progress.get('search_after') if index_progress else None

        logger.info(f"开始处理索引: {index}")
        total_index_updated = 0
        total_index_failed = 0

        while not self._shutdown:
            docs = self.fetch_docs(index, search_after)

            if not docs:
                # 没有更多数据
                break

            self.stats['total_fetched'] += len(docs)

            # 准备更新操作
            actions = self.prepare_bulk_actions(docs)

            if not actions:
                # 没有需要更新的文档
                break

            # 执行批量更新
            success, failed = self.bulk_update(actions)

            total_index_updated += success
            total_index_failed += failed
            self.stats['total_updated'] += success
            self.stats['total_failed'] += failed

            # 获取最后一个文档的排序值
            search_after = docs[-1]['sort']

            # 定期保存进度
            if total_index_updated % 10000 == 0:
                progress_tracker.save_progress(index, search_after)

            logger.info(f"索引 {index}: 本批处理 {len(docs)} 条, "
                       f"累计更新 {total_index_updated} 条, "
                       f"失败 {total_index_failed} 条")

        # 标记索引完成
        progress_tracker.mark_index_completed(index)
        logger.info(f"索引 {index} 处理完成, 共更新 {total_index_updated} 条")

        return total_index_updated, total_index_failed

    def run(self, index_patterns, skip_completed=True):
        """
        执行更新任务

        Args:
            index_patterns: 索引模式列表，如 ['sflow-*', 'ipbandwidth-*']
            skip_completed: 是否跳过已完成的索引
        """
        progress_tracker = ProgressTracker()
        start_time = time.time()

        # 收集所有需要处理的索引
        all_indices = []
        for pattern in index_patterns:
            indices = self.get_indices(pattern)
            logger.info(f"模式 {pattern} 匹配到 {len(indices)} 个索引")
            all_indices.extend(indices)

        if not all_indices:
            logger.error("没有找到匹配的索引")
            return

        logger.info(f"共找到 {len(all_indices)} 个索引需要处理")

        # 统计总数
        total_need_update = 0
        for index in all_indices:
            if skip_completed and progress_tracker.is_index_completed(index):
                continue
            count = self.count_docs_need_update(index)
            total_need_update += count
            logger.info(f"索引 {index} 需要更新 {count} 条文档")

        if total_need_update == 0:
            logger.info("没有需要更新的文档")
            return

        logger.info(f"总计需要更新约 {total_need_update} 条文档")

        # 处理每个索引
        for i, index in enumerate(all_indices):
            if self._shutdown:
                logger.info("收到中断信号，停止处理")
                break

            if skip_completed and progress_tracker.is_index_completed(index):
                logger.info(f"跳过已完成的索引: {index}")
                continue

            updated, failed = self.process_index(index, progress_tracker)

            # 显示总体进度
            progress = (i + 1) / len(all_indices) * 100
            elapsed = time.time() - start_time
            avg_time = elapsed / (i + 1)
            remaining = avg_time * (len(all_indices) - i - 1)

            logger.info(f"总体进度: {i + 1}/{len(all_indices)} ({progress:.1f}%), "
                       f"已更新: {self.stats['total_updated']}, "
                       f"失败: {self.stats['total_failed']}, "
                       f"预计剩余时间: {remaining/60:.1f} 分钟")

        # 最终统计
        total_elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info("更新任务完成!")
        logger.info(f"总耗时: {total_elapsed/60:.2f} 分钟")
        logger.info(f"总共获取: {self.stats['total_fetched']} 条")
        logger.info(f"成功更新: {self.stats['total_updated']} 条")
        logger.info(f"更新失败: {self.stats['total_failed']} 条")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='批量更新 time_period 字段值')
    parser.add_argument('--index', '-i', nargs='+',
                       default=['sflow-*', 'ipbandwidth-*', 'ipbw-*'],
                       help='要处理的索引模式 (支持多个)')
    parser.add_argument('--host', default='http://localhost:9200',
                       help='Elasticsearch 地址')
    parser.add_argument('--user', default='nettraffic_analyzer',
                       help='Elasticsearch 用户名')
    parser.add_argument('--password', default='nettraffic_analyzer',
                       help='Elasticsearch 密码')
    parser.add_argument('--batch-size', type=int, default=5000,
                       help='每批处理的文档数量')
    parser.add_argument('--max-workers', type=int, default=4,
                       help='最大并发数')
    parser.add_argument('--reset', action='store_true',
                       help='重置进度，重新开始')

    args = parser.parse_args()

    # 如果需要重置进度
    if args.reset:
        if os.path.exists('update_time_period_progress.json'):
            os.remove('update_time_period_progress.json')
            logger.info("进度已重置")

    # 创建更新工具
    updater = TimePeriodValueUpdater(
        es_host=args.host,
        es_user=args.user,
        es_password=args.password,
        batch_size=args.batch_size,
        max_workers=args.max_workers
    )

    # 执行更新
    updater.run(args.index)


if __name__ == '__main__':
    main()
