# @Author  : yuanzi
# @Time    : 2025/11/17 15:31
# Website: https://www.yzgsa.com
# Copyright (c) <yuanzigsa@gmail.com>
import json
import io
import os
import logging
import re
import ip2region.util as util
import ip2region.searcher as xdb

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ip2region', 'data')


class Ip2RegionSearcher:
    _instance = None
    _v4_searcher = None
    _v6_searcher = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._init_searchers()
        return cls._instance

    def _init_searchers(self):
        v4_db_path = os.path.join(DATA_DIR, 'ip2region_v4.xdb')
        v6_db_path = os.path.join(DATA_DIR, 'ip2region_v6.xdb')

        v4_handle = io.open(v4_db_path, "rb")
        v4_header = util.load_header(v4_handle)
        v4_version = util.version_from_header(v4_header)
        v4_vector_index = util.load_vector_index(v4_handle)
        self._v4_searcher = xdb.new_with_vector_index(v4_version, v4_db_path, v4_vector_index)
        v4_handle.close()

        v6_handle = io.open(v6_db_path, "rb")
        v6_header = util.load_header(v6_handle)
        v6_version = util.version_from_header(v6_header)
        v6_vector_index = util.load_vector_index(v6_handle)
        self._v6_searcher = xdb.new_with_vector_index(v6_version, v6_db_path, v6_vector_index)
        v6_handle.close()

    def search(self, ip_str):
        try:
            ip_bytes = util.parse_ip(ip_str)
        except ValueError:
            return ""

        if len(ip_bytes) == 4:
            return self._v4_searcher.search(ip_bytes)
        else:
            return self._v6_searcher.search(ip_bytes)

    def close(self):
        if self._v4_searcher:
            self._v4_searcher.close()
        if self._v6_searcher:
            self._v6_searcher.close()
        Ip2RegionSearcher._instance = None


class Resolver:
    def __init__(self):
        self.ip2region = Ip2RegionSearcher.get_instance()

    @staticmethod
    def resolve_ip_region(original_content):
        """
        解析 xdb 原始查询内容，返回省份、城市、区县、运营商信息

        :param original_content: xdb 查询返回的字符串，格式为: 国家|省份|城市|ISP|iso-alpha2-code
        :return: 包含省份、城市、区县、运营商信息的字典
        """
        default_result = {
            'province': '未知',
            'city': '未知',
            'district': '未知',
            'isp': '未知',
        }

        if isinstance(original_content, str) and original_content.strip():
            parts = original_content.split('|')
            if len(parts) >= 4:
                return {
                    'province': parts[1] if parts[1] and parts[1] != '0' else "未知",
                    'city': parts[2] if parts[2] and parts[2] != '0' else "未知",
                    'district': '未知',
                    'isp': parts[3] if parts[3] and parts[3] != '0' else "未知",
                }
        return default_result

    @staticmethod
    def is_ipv4(ip):
        ipv4_pattern = re.compile(
            r'^(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(\.(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3}$')
        return bool(ipv4_pattern.match(ip))

    @staticmethod
    def get_flow_detail(ip, interface, agent_ip_index_map):
        """
        获取节点和客户信息以及确定是入站流量还是出站流量
        :param ip: 源IP地址
        :param interface: 源接口
        :param data: 配置数据
        :return: 节点、客户、端口名、流量方向
        """
        try:
            lookup_key = f"{ip}_{interface}"
            if lookup_key in agent_ip_index_map:
                item = agent_ip_index_map[lookup_key]
                return item['node'], item['costumer'], item['switch'], item['flow_direction']
            return "未知", "未知", "未知", "未知"
        except Exception as e:
            logger.error(f"Error in get_flow_detail: {e}")
            return "未知", "未知", "未知", "未知"

    @staticmethod
    def read_sflow_cacti_data():
        try:
            with open('res/sflow_cacti_data.json', 'r') as f:
                data = json.load(f)
            sflow_cacti_data = {int(item['local_graph_id']): item for item in data}
            return sflow_cacti_data
        except Exception as e:
            logger.error(f"Error in sflow_cacti_data: {e}")
            return {}

    @staticmethod
    def read_config_data():
        try:
            with open('res/config_data.json', 'r') as f:
                data = json.load(f)
            agent_ip_index_map = {f"{item['host_ip']}_{item['interface']}": item for item in data}
            return agent_ip_index_map
        except Exception as e:
            logger.error(f"Error in read_config_data: {e}")
            return {}

    @staticmethod
    def read_config_data_v2():
        try:
            with open('res/config_data.json', 'r') as f:
                data = json.load(f)
            host_ip_index_map = {f"{item['host_ip']}": item for item in data}
            return host_ip_index_map
        except Exception as e:
            logger.error(f"Error in read_config_data: {e}")
            return {}

    @staticmethod
    def _get_agent_ip(data, host_ip, interface):
        for item in data:
            if item['host_ip'] == host_ip and item['interface'] == interface:
                return item['agent_ip']

    @staticmethod
    def rewrite_ipinfo(ip, ipinfo):
        ipinfo['isp'] = "中国联通" if ip and ip.startswith('120.72.50') else ipinfo['isp']
        return ipinfo

    def rewrite_docs(self, docs):
        """
        重写elasticsearch查询结果，添加IP归属地信息
        """
        agent_ip_index_config_map = self.read_config_data()
        sflow_cacti_data_map = self.read_sflow_cacti_data()
        new_docs = []
        ip_info_cache = {}
        try:
            for doc in docs:
                source = doc['_source']
                host_ip = source['host'].get('ip')
                src_ip = source.get('src_ip')
                dst_ip = source.get('dst_ip')
                ifindex = source.get('source_id_index')
                config = agent_ip_index_config_map.get(f"{host_ip}_{ifindex}", {})
                agent_ip = config.get('agent_ip')
                if not all([src_ip, dst_ip, host_ip, agent_ip]):
                    continue
                if agent_ip not in ip_info_cache:
                    result = self.ip2region.search(agent_ip)
                    ip_info_cache[agent_ip] = self.rewrite_ipinfo(agent_ip, self.resolve_ip_region(result))
                agent_ip_info = ip_info_cache[agent_ip]

                is_ipv4 = self.is_ipv4(dst_ip)
                source['ipType'] = "ipv4" if is_ipv4 else "ipv6"

                for ip in (src_ip, dst_ip):
                    if ip not in ip_info_cache:
                        result = self.ip2region.search(ip)
                        ip_info_cache[ip] = self.rewrite_ipinfo(ip, self.resolve_ip_region(result))

                src_ip_info = ip_info_cache[src_ip]
                dst_ip_info = ip_info_cache[dst_ip]

                agent_isp = agent_ip_info.get('isp').replace('中国', '')
                dst_isp = dst_ip_info.get('isp').replace('中国', '')
                agent_province = agent_ip_info.get('province')
                dst_province = dst_ip_info.get('province')

                if agent_isp != "未知" and dst_isp != "未知" and agent_isp == dst_isp:
                    source['flow_isp_type'] = '同网省内' if agent_province == dst_province else '同网跨省'
                else:
                    if not dst_isp or dst_isp == "未知":
                        source['flow_isp_type'] = '异网(未知)'
                    else:
                        source['flow_isp_type'] = f'异网({dst_isp})'

                cacti_data = sflow_cacti_data_map.get(int(config['relation_cacti_graph_id']), {})
                logger.info(f"cacti_data: {cacti_data}")

                source.update({
                    'flow_isp_info_src': src_ip_info,
                    'flow_isp_info': dst_ip_info,
                    'node': config['node'],
                    'customer': config['costumer'],
                    'sw_interface': config['switch'],
                    'src_ip_region': f"{src_ip} {src_ip_info.get('province', '')}{src_ip_info.get('city', '')}",
                    'dst_ip_region': f"{dst_ip} {dst_ip_info.get('province', '')}{dst_ip_info.get('city', '')}",
                    'flow_direction': config['flow_direction'],
                    'sum_traffic_in_max': cacti_data.get('traffic_in_max', 0),
                    'sum_traffic_out_max': cacti_data.get('traffic_out_max', 0),
                })

                new_docs.append(doc)
        except Exception as e:
            logger.error(f"rewrite_docs出错: {e}")
        return new_docs

    def rewrite_docs_v2(self, docs):
        """
        重写elasticsearch查询结果，添加IP归属地信息
        """
        host_ip_index_config_map = self.read_config_data_v2()
        new_docs = []
        ip_info_cache = {}
        try:
            for doc in docs:
                source = doc['_source']
                host_ip = source['host'].get('ip')
                local_ip = source.get('in_dst')
                remote_ip = source.get('in_src')
                config = host_ip_index_config_map.get(f"{host_ip}", {})
                if not all([local_ip, remote_ip, host_ip]):
                    continue
                if local_ip not in ip_info_cache:
                    result = self.ip2region.search(local_ip)
                    ip_info_cache[local_ip] = self.resolve_ip_region(result)
                local_ip_info = ip_info_cache[local_ip]

                is_ipv4 = self.is_ipv4(remote_ip)
                source['ipType'] = "ipv4" if is_ipv4 else "ipv6"

                for ip in (local_ip, remote_ip):
                    if ip not in ip_info_cache:
                        result = self.ip2region.search(ip)
                        ip_info_cache[ip] = self.rewrite_ipinfo(ip, self.resolve_ip_region(result))

                local_ip_info = ip_info_cache[local_ip]
                remote_ip_info = ip_info_cache[remote_ip]

                local_isp = local_ip_info.get('isp').replace('中国', '')
                remote_isp = remote_ip_info.get('isp').replace('中国', '')

                source.update({
                    'host_name': config.get('host_name', '未知'),
                    'node': config.get('node', '未知'),
                    'customer': config.get('costumer', '未知'),
                    'interface': config.get('interface', '未知'),
                    'local_ip_info': local_ip_info,
                    'remote_ip_info': remote_ip_info,
                    'local_ip_region': f"{local_ip_info.get('province', '')}{local_ip_info.get('city', '')}",
                    'local_ip_region_full': f"{local_ip} {local_ip_info.get('province', '')}{local_ip_info.get('city', '')}",
                    'remote_ip_region': f"{remote_ip_info.get('province', '')}{remote_ip_info.get('city', '')}",
                    'remote_ip_region_full': f"{remote_ip} {remote_ip_info.get('province', '')}{remote_ip_info.get('city', '')}",
                    'local_ip_isp': local_isp,
                    'remote_ip_isp': remote_isp,
                })

                new_docs.append(doc)
        except Exception as e:
            logger.error(f"rewrite_docs出错: {e}")
        return new_docs

    def rewrite_docs_v3(self, docs):
        """
        重写elasticsearch查询结果，添加IP归属地信息
        """
        host_ip_index_config_map = self.read_config_data_v2()
        new_docs = []
        ip_info_cache = {}
        try:
            for doc in docs:
                source = doc['_source']
                host_ip = source['host'].get('ip')
                local_ip = source.get('source_ip')
                config = host_ip_index_config_map.get(f"{host_ip}", {})
                if not all([local_ip, host_ip]):
                    continue
                if local_ip not in ip_info_cache:
                    result = self.ip2region.search(local_ip)
                    ip_info_cache[local_ip] = self.resolve_ip_region(result)
                local_ip_info = ip_info_cache[local_ip]

                is_ipv4 = self.is_ipv4(local_ip)
                source['ipType'] = "ipv4" if is_ipv4 else "ipv6"

                for ip in (local_ip, host_ip):
                    if ip not in ip_info_cache:
                        result = self.ip2region.search(ip)
                        ip_info_cache[ip] = self.rewrite_ipinfo(ip, self.resolve_ip_region(result))

                local_ip_info = ip_info_cache[local_ip]
                local_isp = local_ip_info.get('isp').replace('中国', '')

                source.update({
                    'host_name': config.get('host_name', '未知'),
                    'node': config.get('node', '未知'),
                    'customer': config.get('costumer', '未知'),
                    'interface': config.get('interface', '未知'),
                    'local_ip_info': local_ip_info,
                    'local_ip_region': f"{local_ip_info.get('province', '')}{local_ip_info.get('city', '')}",
                    'local_ip_region_full': f"{local_ip} {local_ip_info.get('province', '')}{local_ip_info.get('city', '')}",
                    'local_ip_isp': local_isp,
                })

                new_docs.append(doc)
        except Exception as e:
            logger.error(f"rewrite_docs出错: {e}")
        return new_docs