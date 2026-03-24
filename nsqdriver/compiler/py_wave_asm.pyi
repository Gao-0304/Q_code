from typing import Any

import numpy as np


global_config = {
    'play_zero_step': 4e-9,
    'OUTSrate': 8e9,
    'envelope_dtype': np.int16,  # 描述包络每个点的数据类型
    'envelope_step': 64,  # 包络步进粒度，单位为bytes
    'envelope_quant': 16383,  # 包络量化范围
    'envelope_cache': 204800,  # 包络缓存大小，单位bytes
    'envelope_head': np.array([2, 0, 0, 4096, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.int16),   # 包络更新包头
}


def nsw_config(name: str, value: Any) -> None: ...


class AssemblyError(RuntimeError): ...


class GenTagMixin: ...


class NSQCommand: ...


class Assembler: ...
