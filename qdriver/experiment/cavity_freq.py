"""
时序层 - 腔频测量

包含测量腔的频率响应曲线的函数
"""
import numpy as np


def measure_cavity_frequency(xy_drive, readout, freq_list, **kwargs):
    """
    测量腔频特性曲线（S21曲线）

    对频率列表进行扫频，每个频率点执行一次读出测量，
    收集IQ数据并计算幅值和相位。

    参数：
    - xy_drive: XYDrive对象（驱动器）
    - readout: Readout对象（读出器）
    - freq_list: 频率列表 np.ndarray (Hz)
    - **kwargs: 保留用于扩展（如进度条回调等）

    返回：
    - dict: {
        'freq': np.array([...]),      # 扫频列表
        'mag': np.array([...]),       # IQ幅值
        'phase': np.array([...]),     # IQ相位
        'iq_raw': list(...)           # 原始IQ数据列表
      }
    """
    mag_list = []
    phase_list = []
    iq_raw_list = []

    for i, freq in enumerate(freq_list):
        # 更新XY驱动器的频率
        xy_drive.set_frequencies([freq])

        # 执行一次测量
        result = readout.measure()

        # 收集结果
        mag_list.append(result['mag'])
        phase_list.append(result['phase'])
        iq_raw_list.append(result['iq_raw'])

    return {
        'freq': np.array(freq_list),
        'mag': np.array(mag_list),
        'phase': np.array(phase_list),
        'iq_raw': iq_raw_list
    }
