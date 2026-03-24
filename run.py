# @Author  : yuanzi
# @Time    : 2024/11/17 10:12
# Website: https://www.yzgsa.com
# Copyright (c) <yuanzigsa@gmail.com>

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ip2region', 'binding', 'python'))

import json
from nettraffic_analyzer.es import Es, Es_v2, Es_v3
from nettraffic_analyzer.utils import *


if __name__ == "__main__":
    logger = setup_logger()
    logger.warning(banner)
    try:
        with open("config/config.json", "r") as f:
            config = json.load(f)
    except FileNotFoundError:
        config = {}        
    if config.get("run_v2"):
        # 使用ipbw_agent解析
        es = Es_v2()
    elif config.get("run_v3"):
        # 使用ipbw_agent解析
        es = Es_v3()
    else:
        # 使用sflow解析
        es = Es()
    logger.warning(f"开始运行，版本: {es.__class__.__name__}")
    es.run()
