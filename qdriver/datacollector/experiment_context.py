"""
数据管理层 - 实验上下文

维护实验中间结果和特征参数
"""
import numpy as np


class ExperimentContext:
    """
    实验上下文类

    管理实验中间结果和提取的特征参数，供时序层调用。
    包括：腔频、品质因数、最后一次扫描的数据等。
    """

    def __init__(self):
        """初始化上下文"""
        self.cavity_freq = None         # 测得的腔频 (Hz)
        self.cavity_q = None            # 腔品质因数
        self.cavity_linewidth = None    # 腔线宽 (Hz)

        self.last_scan_data = None      # 最后一次扫频的原始数据 (dict)
        self.last_scan_params = None    # 最后一次扫频的参数 (dict)

    def update_from_cavity_scan(self, freq_array, mag_array, phase_array=None):
        """
        从腔频扫描数据中提取中间结果

        参数：
        - freq_array: 频率数组 np.ndarray
        - mag_array: 幅值数组 np.ndarray
        - phase_array: 相位数组 np.ndarray (可选)
        """
        # 找到最大响应点作为腔频
        idx_max = np.argmax(mag_array)
        self.cavity_freq = freq_array[idx_max]

        # 计算品质因数（简单估计）
        # 找到半高宽（-3dB点）
        mag_max = mag_array[idx_max]
        mag_half = mag_max / np.sqrt(2)

        # 找半高宽处的频率
        left_idx = np.where(mag_array[:idx_max] > mag_half)[0]
        right_idx = np.where(mag_array[idx_max:] > mag_half)[0]

        if len(left_idx) > 0 and len(right_idx) > 0:
            f_left = freq_array[left_idx[0]]
            f_right = freq_array[idx_max + right_idx[-1]]
            self.cavity_linewidth = f_right - f_left
            self.cavity_q = self.cavity_freq / self.cavity_linewidth
        else:
            self.cavity_linewidth = None
            self.cavity_q = None

        # 存储原始数据
        self.last_scan_data = {
            'freq': freq_array,
            'mag': mag_array,
            'phase': phase_array
        }

        self.last_scan_params = {
            'cavity_freq': self.cavity_freq,
            'cavity_q': self.cavity_q,
            'cavity_linewidth': self.cavity_linewidth
        }

    def get_cavity_params(self):
        """获取腔的所有参数"""
        return {
            'freq': self.cavity_freq,
            'q': self.cavity_q,
            'linewidth': self.cavity_linewidth
        }

    def reset(self):
        """重置所有中间结果"""
        self.cavity_freq = None
        self.cavity_q = None
        self.cavity_linewidth = None
        self.last_scan_data = None
        self.last_scan_params = None
