# @Author  : yuanzi
# @Time    : 2025/11/17 15:31
# Website: https://www.yzgsa.com
# Copyright (c) <yuanzigsa@gmail.com>
import json
from enum import Enum
import logging
import re
from nettraffic_analyzer.xdbSearcher import XdbSearcher
from nettraffic_analyzer.utils import setup_logger, ipv6_search

logger = logging.getLogger(__name__)


class Isp(Enum):
    CHINA_MOBILE = "中国移动"
    CHINA_UNICOM = "中国联通"
    CHINA_TELECOM = "中国电信"


class Resolver:
    def __init__(self):
        dbPath = "res/china.xdb"
        self.cb = XdbSearcher.loadContentFromFile(dbfile=dbPath)
        try:
            with open("config/config.json", "r") as f:
                config = json.load(f)
        except FileNotFoundError:
            config = {}      
        self.db_host = config.get('db_host', 'localhost')
        self.db_user = config.get('db_user', 'root')
        self.db_password = config.get('db_password', 'mspvAtxchJA2')
        self.db_database = config.get('db_database', 'ipv6')

    @staticmethod
    def resolve_ip_region(original_content, ipv6=False):
        """
        解析 xdb 原始查询内容，返回省份、城市、区县、运营商信息

        :param original_content: 原始查询内容，IPv4 为字符串，IPv6 为列表
        :param ipv6: 是否为 IPv6 查询
        :return: 包含省份、城市、区县、运营商信息的字典
        """
        # 默认返回值
        default_result = {
            'province': '未知',
            'city': '未知',
            'district': '未知',
            'isp': '未知',
        }

        # 处理 IPv6 查询结果
        if ipv6:
            if isinstance(original_content, (list, tuple)) and len(original_content) > 15:
                return {
                    'province': original_content[13] if original_content[13] else "未知",
                    'city': original_content[15] if original_content[15] else "未知",
                    # 'district': '未知',  # IPv6 结果中可能没有区县信息
                    'isp': original_content[6] if original_content[6] else "未知",
                }
            return default_result

        # 处理 IPv4 查询结果
        if isinstance(original_content, str) and original_content.strip():
            parts = original_content.split('|')
            if len(parts) > 9:
                return {
                    'province': parts[7] if parts[7] else "未知",
                    'city': parts[9] if parts[9] else "未知",
                    'district': parts[4] if parts[4] else "未知",
                    'isp': parts[0] if parts[0] else "未知",
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
                # flow_direction = "未知"
                
                # if item.get('port_type') == "up":
                #     flow_direction = "入站" if item.get('direction') == "in" else "出站"
                # elif item.get('port_type') == "down":
                #     flow_direction = "出站" if item.get('direction') == "in" else "入站"
                
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
                # logger.info(f"当前配置：{data}")
            # 构建查找字典
            # host_ip_index_map = {f"{item['host_ip']}_{item['interface']}": item for item in data}
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
    def rewrite_ipinfo(ip, ipinfo, isv4=True):
        if isv4:
            ipinfo['isp'] = "中国联通" if ip and ip.startswith('120.72.50') else ipinfo['isp']

        return ipinfo

    def rewrite_docs(self, docs):
        """
        重写elasticsearch查询结果，添加IP归属地信息
            1. 同运营商省内比例-同网省内
            2. 同运营商出省比例-同网跨省
            3. 去往移动的比例-异网(移动)
            4. 去往联通的比例-异网(联通)
            5. 去往电信的比例-异网(电信)
        """
        # 默认情况下agent_ip和host_ip是一样的，但在三线情况下可能不同，所以以agent_ip为准
        searcher = XdbSearcher(contentBuff=self.cb)
        agent_ip_index_config_map = self.read_config_data()
        sflow_cacti_data_map = self.read_sflow_cacti_data()
        new_docs = []
        # IP信息缓存
        ip_info_cache = {}
        try:
            for doc in docs:
                source = doc['_source']
                host_ip = source['host'].get('ip')
                src_ip = source.get('src_ip')
                dst_ip = source.get('dst_ip')
                ifindex = source.get('source_id_index')
                config = agent_ip_index_config_map.get(f"{host_ip}_{ifindex}",{})
                agent_ip = config.get('agent_ip')
                if not all([src_ip, dst_ip, host_ip, agent_ip]):
                    continue
                if agent_ip not in ip_info_cache:
                    result = searcher.search(agent_ip)
                    ip_info_cache[agent_ip] = self.rewrite_ipinfo(agent_ip, self.resolve_ip_region(result))
                agent_ip_info = ip_info_cache[agent_ip]
    
                # 使用缓存获取IP信息
                is_ipv4 = self.is_ipv4(dst_ip)
                source['ipType'] = "ipv4" if is_ipv4 else "ipv6"
                
                # 获取源IP和目标IP信息
                for ip in (src_ip, dst_ip):
                    if ip not in ip_info_cache:
                        if is_ipv4:
                            result = searcher.search(ip)
                            ip_info_cache[ip] = self.rewrite_ipinfo(ip, self.resolve_ip_region(result))
                        else:
                            result = ipv6_search(ip, self.db_host, self.db_user, self.db_password, self.db_database)
                            ip_info_cache[ip] = self.resolve_ip_region(result, ipv6=True)
                
                src_ip_info = ip_info_cache[src_ip]
                dst_ip_info = ip_info_cache[dst_ip]
                
                # 处理ISP信息
                agent_isp = agent_ip_info.get('isp').replace('中国', '')
                dst_isp = dst_ip_info.get('isp').replace('中国', '')
                agent_province = agent_ip_info.get('province')
                dst_province = dst_ip_info.get('province')

                # 设置流量类型
                if agent_isp != "未知" and dst_isp != "未知" and agent_isp == dst_isp:
                    # 同网情况
                    source['flow_isp_type'] = '同网省内' if agent_province == dst_province else '同网跨省'
                else:
                    # 异网情况，也需要区分省内省外
                    if not dst_isp or dst_isp == "未知":
                        source['flow_isp_type'] = '异网省内(未知)' if agent_province == dst_province else '异网跨省(未知)'
                    else:
                        if agent_province == dst_province:
                            source['flow_isp_type'] = f'异网省内({dst_isp})'
                        else:
                            source['flow_isp_type'] = f'异网跨省({dst_isp})'
                    
                # 获取cacti流量图信息
                cacti_data = sflow_cacti_data_map.get(int(config['relation_cacti_graph_id']),{})
                logger.info(f"cacti_data: {cacti_data}")
                
                # 更新source信息
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

                # if host_ip == "58.19.25.1" and interface == "69":
                #     logger.warning(f"当前配置: {config}")
                #     logger.warning(f"匹配到的的文档: {matching_docs}")
                #     logger.warning(f"更新后的文档: {doc}")
                new_docs.append(doc)
        except Exception as e:
            logger.error(f"rewrite_docs出错: {e}")
        finally:
            searcher.close()
        return new_docs

    def rewrite_docs_v2(self, docs):
        """
        重写elasticsearch查询结果，添加IP归属地信息
        """
        # 默认情况下agent_ip和host_ip是一样的，但在三线情况下可能不同，所以以agent_ip为准
        searcher = XdbSearcher(contentBuff=self.cb)
        host_ip_index_config_map = self.read_config_data_v2()
        new_docs = []
        # IP信息缓存
        ip_info_cache = {}
        try:
            for doc in docs:
                source = doc['_source']
                host_ip = source['host'].get('ip')
                local_ip = source.get('in_dst')
                remote_ip = source.get('in_src')
                config = host_ip_index_config_map.get(f"{host_ip}",{})
                if not all([local_ip, remote_ip, host_ip]):
                    # logger.warning(f"本机IP: {host_ip} 目标IP: {local_ip} 源IP: {remote_ip} Doc: {doc} 配置: {config}")
                    continue
                if local_ip not in ip_info_cache:
                    result = searcher.search(local_ip)
                    ip_info_cache[local_ip] = self.resolve_ip_region(result)
                local_ip_info = ip_info_cache[local_ip]

                # 使用缓存获取IP信息
                is_ipv4 = self.is_ipv4(remote_ip)
                source['ipType'] = "ipv4" if is_ipv4 else "ipv6"
                # 使用缓存获取IP信息
                is_ipv4 = self.is_ipv4(local_ip)
                # 获取源IP和目标IP信息
                for ip in (local_ip, remote_ip):
                    if ip not in ip_info_cache:
                        if is_ipv4:
                            result = searcher.search(ip)
                            ip_info_cache[ip] = self.rewrite_ipinfo(ip, self.resolve_ip_region(result))
                        # else:
                        #     result = ipv6_search(ip)
                        #     ip_info_cache[ip] = self.resolve_ip_region(result, ipv6=True)
                
                local_ip_info = ip_info_cache[local_ip]
                remote_ip_info = ip_info_cache[remote_ip]
                
                # 处理ISP信息
                local_isp = local_ip_info.get('isp').replace('中国', '')
                remote_isp = remote_ip_info.get('isp').replace('中国', '')
                
                # 设置流量类型
                # if local_isp != "未知" and remote_isp != "未知" and local_isp == remote_isp:
                #     source['flow_isp_type'] = '同网省内' if local_ip_info.get('province') == remote_ip_info.get('province') else '同网跨省'
                # else:
                #     source['flow_isp_type'] = '异网(未知)' if not dst_isp else f'异网({dst_isp})'
                
                # 更新source信息
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

                # if host_ip == "58.19.25.1" and interface == "69":
                #     logger.warning(f"当前配置: {config}")
                #     logger.warning(f"匹配到的的文档: {matching_docs}")
                #     logger.warning(f"更新后的文档: {doc}")
                new_docs.append(doc)
        except Exception as e:
            logger.error(f"rewrite_docs出错: {e}")
        finally:
            searcher.close()
        return new_docs
    
    def rewrite_docs_v3(self, docs):
        """
        重写elasticsearch查询结果，添加IP归属地信息
        """
        searcher = XdbSearcher(contentBuff=self.cb)
        host_ip_index_config_map = self.read_config_data_v2()
        new_docs = []
        # IP信息缓存
        ip_info_cache = {}
        try:
            for doc in docs:
                source = doc['_source']
                host_ip = source['host'].get('ip')
                local_ip = source.get('source_ip')
                config = host_ip_index_config_map.get(f"{host_ip}",{})
                if not all([local_ip, host_ip]):
                    # logger.warning(f"本机IP: {host_ip} 目标IP: {local_ip} 源IP: {remote_ip} Doc: {doc} 配置: {config}")
                    continue
                if local_ip not in ip_info_cache:
                    result = searcher.search(local_ip)
                    ip_info_cache[local_ip] = self.resolve_ip_region(result)
                local_ip_info = ip_info_cache[local_ip]

                # 使用缓存获取IP信息
                is_ipv4 = self.is_ipv4(local_ip)
                source['ipType'] = "ipv4" if is_ipv4 else "ipv6"
                # 使用缓存获取IP信息
                is_ipv4 = self.is_ipv4(local_ip)
                # 获取源IP和目标IP信息
                for ip in (local_ip, host_ip):
                    if ip not in ip_info_cache:
                        if is_ipv4:
                            result = searcher.search(ip)
                            ip_info_cache[ip] = self.rewrite_ipinfo(ip, self.resolve_ip_region(result))
                        # else:
                        #     result = ipv6_search(ip)
                        #     ip_info_cache[ip] = self.resolve_ip_region(result, ipv6=True)
                
                local_ip_info = ip_info_cache[local_ip]                
                # 处理ISP信息
                local_isp = local_ip_info.get('isp').replace('中国', '')
                
                # 设置流量类型
                # if local_isp != "未知" and remote_isp != "未知" and local_isp == remote_isp:
                #     source['flow_isp_type'] = '同网省内' if local_ip_info.get('province') == remote_ip_info.get('province') else '同网跨省'
                # else:
                #     source['flow_isp_type'] = '异网(未知)' if not dst_isp else f'异网({dst_isp})'
                
                # 更新source信息
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
        finally:
            searcher.close()
        return new_docs