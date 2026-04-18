# @Author  : yuanzi
# @Time    : 2025/11/17 15:31
# Website: https://www.yzgsa.com
# Copyright (c) <yuanzigsa@gmail.com>
import json
import io
import os
import logging
import re
from datetime import datetime, timezone, timedelta
import ip2region.util as util
import ip2region.searcher as xdb

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'ip2region', 'data')
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config')

# 境外 IPv6 国家名 → ISO 3166-1 alpha-2 码兜底映射（world_ipv4.xdb 只覆盖 IPv4）
COUNTRY_NAME_TO_CODE = {
    "中国": "CN", "美国": "US", "日本": "JP", "韩国": "KR", "朝鲜": "KP",
    "德国": "DE", "英国": "GB", "法国": "FR", "俄罗斯": "RU", "新加坡": "SG",
    "香港": "HK", "台湾": "TW", "澳门": "MO", "澳大利亚": "AU", "加拿大": "CA",
    "印度": "IN", "巴西": "BR", "意大利": "IT", "西班牙": "ES", "荷兰": "NL",
    "瑞典": "SE", "瑞士": "CH", "挪威": "NO", "芬兰": "FI", "丹麦": "DK",
    "波兰": "PL", "乌克兰": "UA", "白俄罗斯": "BY", "土耳其": "TR", "伊朗": "IR",
    "以色列": "IL", "沙特阿拉伯": "SA", "阿联酋": "AE", "越南": "VN", "泰国": "TH",
    "马来西亚": "MY", "印度尼西亚": "ID", "菲律宾": "PH", "南非": "ZA", "墨西哥": "MX",
    "阿根廷": "AR", "智利": "CL", "委内瑞拉": "VE", "古巴": "CU", "叙利亚": "SY",
    "新西兰": "NZ", "爱尔兰": "IE", "葡萄牙": "PT", "希腊": "GR", "奥地利": "AT",
    "比利时": "BE", "捷克": "CZ", "匈牙利": "HU",
}


def _load_sensitive_countries():
    """启动时加载敏感国家 ISO 码列表，文件缺失或格式异常返回空 set，不影响启动。"""
    path = os.path.join(CONFIG_DIR, 'sensitive_countries.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        codes = data.get('sensitive_country_codes', [])
        return set(c.upper() for c in codes if isinstance(c, str))
    except FileNotFoundError:
        logger.warning(f"敏感国家配置文件不存在: {path}，将不标记任何敏感国家")
        return set()
    except Exception as e:
        logger.warning(f"读取敏感国家配置失败: {e}，将不标记任何敏感国家")
        return set()


SENSITIVE_COUNTRY_CODES = _load_sensitive_countries()


class Ip2RegionSearcher:
    _instance = None
    _v4_searcher = None
    _v6_searcher = None
    _world_v4_searcher = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._init_searchers()
        return cls._instance

    def _init_searchers(self):
        v4_db_path = os.path.join(DATA_DIR, 'ip2region_v4.xdb')
        v6_db_path = os.path.join(DATA_DIR, 'ip2region_v6.xdb')
        world_v4_db_path = os.path.join(DATA_DIR, 'world_ipv4.xdb')

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

        # 世界 IPv4 地址库（~80MB），启动预加载；仅用于非中国 IPv4 的详细信息补全
        if os.path.exists(world_v4_db_path):
            world_v4_handle = io.open(world_v4_db_path, "rb")
            world_v4_header = util.load_header(world_v4_handle)
            world_v4_version = util.version_from_header(world_v4_header)
            world_v4_vector_index = util.load_vector_index(world_v4_handle)
            self._world_v4_searcher = xdb.new_with_vector_index(
                world_v4_version, world_v4_db_path, world_v4_vector_index
            )
            world_v4_handle.close()
            logger.info(f"世界 IPv4 XDB 加载成功: {world_v4_db_path}")
        else:
            logger.warning(f"世界 IPv4 XDB 不存在: {world_v4_db_path}，境外 IP 将仅依赖基础库兜底")

    def search(self, ip_str):
        try:
            ip_bytes = util.parse_ip(ip_str)
        except ValueError:
            return ""

        if len(ip_bytes) == 4:
            return self._v4_searcher.search(ip_bytes)
        else:
            return self._v6_searcher.search(ip_bytes)

    def search_world_v4(self, ip_str):
        """查询世界 IPv4 地址库，仅用于已判定为非中国 IPv4 的补充查询。"""
        if self._world_v4_searcher is None:
            return ""
        try:
            ip_bytes = util.parse_ip(ip_str)
        except ValueError:
            return ""
        if len(ip_bytes) != 4:
            return ""
        try:
            return self._world_v4_searcher.search(ip_bytes)
        except Exception as e:
            logger.warning(f"world_ipv4 查询失败 ip={ip_str}: {e}")
            return ""

    def close(self):
        if self._v4_searcher:
            self._v4_searcher.close()
        if self._v6_searcher:
            self._v6_searcher.close()
        if self._world_v4_searcher:
            self._world_v4_searcher.close()
        Ip2RegionSearcher._instance = None


class Resolver:
    def __init__(self):
        self.ip2region = Ip2RegionSearcher.get_instance()

    @staticmethod
    def resolve_ip_region(original_content):
        """
        解析 xdb 原始查询内容，返回国家、省份、城市、区县、运营商信息

        :param original_content: xdb 查询返回的字符串，格式为: 国家|省份|城市|ISP
        :return: 包含国家、省份、城市、区县、运营商信息的字典
        """
        default_result = {
            'country': '未知',
            'province': '未知',
            'city': '未知',
            'district': '未知',
            'isp': '未知',
        }

        if isinstance(original_content, str) and original_content.strip():
            parts = original_content.split('|')
            if len(parts) >= 4:
                return {
                    'country': parts[0] if parts[0] and parts[0] != '0' else "未知",
                    'province': parts[1] if parts[1] and parts[1] != '0' else "未知",
                    'city': parts[2] if parts[2] and parts[2] != '0' else "未知",
                    'district': '未知',
                    'isp': parts[3] if parts[3] and parts[3] != '0' else "未知",
                }
        return default_result

    def resolve_country_info(self, ip):
        """
        综合国家码解析：先走现有中国 XDB，若判定为非中国 IPv4 再走世界 XDB 补全国家名与 ISO 码。
        返回 dict 在 resolve_ip_region 基础上追加 country_code、hit_sensitive_country。
        """
        base = self.resolve_ip_region(self.ip2region.search(ip))
        country = base.get('country', '未知')

        if country == '中国':
            code = 'CN'
        elif self.is_ipv4(ip):
            # 基础库判定非中国 IPv4（含返回"未知"）→ 走世界库补全国家名与 ISO 码
            world_raw = self.ip2region.search_world_v4(ip)
            code = 'XX'
            if world_raw:
                parts = world_raw.split('|')
                if len(parts) >= 6:
                    if parts[1] and parts[1] != '0':
                        country = parts[1]
                    if parts[5] and parts[5] != '0':
                        code = parts[5]
                    # world XDB 的 ISP 字段(parts[6]) 比基础库更准，命中则覆盖
                    if len(parts) >= 7 and parts[6] and parts[6] != '0':
                        base['isp'] = parts[6]
            if code == 'XX' and country != '未知':
                code = COUNTRY_NAME_TO_CODE.get(country, 'XX')
        else:
            # 非中国 IPv6，或未知 IP：用名称映射兜底
            code = COUNTRY_NAME_TO_CODE.get(country, 'XX') if country != '未知' else 'XX'

        base['country'] = country
        base['country_code'] = code
        base['hit_sensitive_country'] = code in SENSITIVE_COUNTRY_CODES
        return base

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

    @staticmethod
    def get_time_period(timestamp_str, node):
        """
        根据时间戳和节点类型判断流量所属时段

        Args:
            timestamp_str: ISO格式时间字符串 (UTC)
            node: 节点名称

        Returns:
            str: '晚高峰' 或 '闲时'
        """
        try:
            # 解析时间戳并转换为UTC+8
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            utc8 = timezone(timedelta(hours=8))
            local_time = dt.astimezone(utc8)
            hour = local_time.hour

            # 判断运营商类型
            node_upper = node.upper() if node else ''
            if 'LT' in node_upper:
                # 联通: 20:00-23:00 为晚高峰
                if 20 <= hour < 23:
                    return '晚高峰'
                else:
                    return '闲时'
            elif 'YD' in node_upper:
                # 移动: 20:00-22:00 为晚高峰
                if 20 <= hour < 22:
                    return '晚高峰'
                else:
                    return '闲时'
            else:
                # 未知节点类型，默认为闲时
                return '闲时'
        except Exception:
            return '闲时'

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
                    ip_info_cache[agent_ip] = self.rewrite_ipinfo(agent_ip, self.resolve_country_info(agent_ip))
                agent_ip_info = ip_info_cache[agent_ip]

                is_ipv4 = self.is_ipv4(dst_ip)
                source['ipType'] = "ipv4" if is_ipv4 else "ipv6"

                for ip in (src_ip, dst_ip):
                    if ip not in ip_info_cache:
                        ip_info_cache[ip] = self.rewrite_ipinfo(ip, self.resolve_country_info(ip))

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

                # 计算流量时段
                timestamp = source.get('@timestamp', '')
                time_period = self.get_time_period(timestamp, config.get('node', ''))

                src_country = src_ip_info.get('country', '未知')
                src_code = src_ip_info.get('country_code', 'XX')
                dst_country = dst_ip_info.get('country', '未知')
                dst_code = dst_ip_info.get('country_code', 'XX')
                region_type = '境外' if (src_code != 'CN' or dst_code != 'CN') else '境内'
                hit_sensitive = src_ip_info.get('hit_sensitive_country', False) or dst_ip_info.get('hit_sensitive_country', False)

                src_region_suffix = src_country if src_code != 'CN' else f"{src_ip_info.get('province', '')}{src_ip_info.get('city', '')}"
                dst_region_suffix = dst_country if dst_code != 'CN' else f"{dst_ip_info.get('province', '')}{dst_ip_info.get('city', '')}"

                source.update({
                    'flow_isp_info_src': src_ip_info,
                    'flow_isp_info': dst_ip_info,
                    'node': config['node'],
                    'customer': config['costumer'],
                    'sw_interface': config['switch'],
                    'src_ip_region': f"{src_ip} {src_region_suffix}",
                    'dst_ip_region': f"{dst_ip} {dst_region_suffix}",
                    'flow_direction': config['flow_direction'],
                    'sum_traffic_in_max': cacti_data.get('traffic_in_max', 0),
                    'sum_traffic_out_max': cacti_data.get('traffic_out_max', 0),
                    'sum_traffic_in_avg': cacti_data.get('traffic_in_avg', 0),
                    'sum_traffic_out_avg': cacti_data.get('traffic_out_avg', 0),
                    'time_period': time_period,
                    'src_country': src_country,
                    'src_country_code': src_code,
                    'dst_country': dst_country,
                    'dst_country_code': dst_code,
                    'region_type': region_type,
                    'hit_sensitive_country': hit_sensitive,
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

                # 计算流量时段
                timestamp = source.get('@timestamp', '')
                time_period = self.get_time_period(timestamp, config.get('node', ''))

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
                    'time_period': time_period,
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

                # 计算流量时段
                timestamp = source.get('@timestamp', '')
                time_period = self.get_time_period(timestamp, config.get('node', ''))

                source.update({
                    'host_name': config.get('host_name', '未知'),
                    'node': config.get('node', '未知'),
                    'customer': config.get('costumer', '未知'),
                    'interface': config.get('interface', '未知'),
                    'local_ip_info': local_ip_info,
                    'local_ip_region': f"{local_ip_info.get('province', '')}{local_ip_info.get('city', '')}",
                    'local_ip_region_full': f"{local_ip} {local_ip_info.get('province', '')}{local_ip_info.get('city', '')}",
                    'local_ip_isp': local_isp,
                    'time_period': time_period,
                })

                new_docs.append(doc)
        except Exception as e:
            logger.error(f"rewrite_docs出错: {e}")
        return new_docs