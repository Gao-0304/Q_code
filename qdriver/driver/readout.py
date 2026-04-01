"""
设备管理层 - 读出器类
"""
import numpy as np
import time
import nsqdriver.nswave as nw


@nw.kernel
def _program_rd(delay: nw.Var, in_delay: nw.Var, sample_length: nw.Var):
    """nswave内核：读出程序"""
    nw.wait_for_trigger()
    nw.wait(delay + in_delay + 4.096e-6 - sample_length)
    nw.capture(sample_length, 0, 0)
    return nw.Kernel()


@nw.kernel
def _program_xy_onepulse(freq: nw.Var, amp: nw.Var, width: nw.Var, delay: nw.Var):
    """nswave内核：单脉冲XY驱动"""
    srate: nw.Var = 8e9
    time_line: np.ndarray = np.linspace(0, width, int(width * srate), endpoint=False)
    wave: np.ndarray = amp * np.cos(2 * np.pi * time_line * freq)
    frame_0: nw.Frame = nw.init_frame(0, 0.5*np.pi)
    envelope_0: nw.Envelope = nw.ins_envelope(wave)
    nw.wait_for_trigger()
    nw.reset_frame()
    nw.wait(delay)
    nw.play_wave(envelope_0, 1, 0, 0)
    return nw.Kernel()


class Readout:
    """
    读出器类
    存储读出通道的时序参数和控制参数

    - 时序参数：delay, in_delay, sample_length（可变）
    - 近似固定参数：shots, period, 输出参数等
    - 校准接口：预留singleshot精细化校准
    """

    def __init__(self, device, qsync, input_channel, output_channel, adrate):
        """
        初始化读出器

        参数：
        - device: MCIDriver对象
        - qsync: QSYNCDriver对象
        - input_channel: 输入通道，如 "S9-I1"
        - output_channel: 输出通道，如 "S9-O1"
        - adrate: AD采样率 (Hz)，如 4e9
        """
        self.device = device
        self.qsync = qsync
        self.input_channel = input_channel
        self.output_channel = output_channel
        self.adrate = adrate

        # 时序参数（可变）
        self.delay = None
        self.in_delay = None
        self.sample_length = None

        # 近似固定参数
        self.shots = 1024 * 10
        self.period = 200e-6

        # 读出波形参数
        self.rd_freq = None
        self.rd_amp = None

        # 校准参数（预留）
        self.singleshot_calib = {}

    def configure(self, delay, in_delay, sample_length, shots=None, period=None):
        """
        全定义：设置时序参数和重复次数

        参数：
        - delay: 主延迟 (秒)
        - in_delay: 输入延迟 (秒)
        - sample_length: 采集长度 (秒)
        - shots: 重复次数，默认保持现有值
        - period: Trigger周期 (秒)，默认保持现有值
        """
        self.delay = delay
        self.in_delay = in_delay
        self.sample_length = sample_length

        if shots is not None:
            self.shots = shots
        if period is not None:
            self.period = period

        self._upload_config()

    def set_frequency(self, freq):
        """快速修改：只改变读出频率"""
        self.rd_freq = freq
        self._update_freq()

    def set_amplitude(self, amp):
        """快速修改：只改变读出幅度"""
        self.rd_amp = amp
        self._update_amp()

    def set_shots(self, shots):
        """快速修改：只改变重复次数"""
        self.shots = shots

    def set_period(self, period):
        """快速修改：只改变Trigger周期"""
        self.period = period

    def calibrate_singleshot(self, freq_fine_calib=None, length_fine_calib=None):
        """
        预留接口：singleshot测量的精细化校准

        参数：
        - freq_fine_calib: 读出频率微调值
        - length_fine_calib: 采集长度微调值
        """
        if freq_fine_calib is not None:
            self.singleshot_calib['freq'] = freq_fine_calib
        if length_fine_calib is not None:
            self.singleshot_calib['length'] = length_fine_calib

    def _upload_config(self):
        """
        内部方法：根据当前参数上传读出配置
        迁移自原s21measure1freq函数的前半部分
        """
        # 上传读出程序
        self.device.set('ProgramIN',
                       _program_rd(delay=self.delay, in_delay=self.in_delay,
                                   sample_length=self.sample_length),
                       self.input_channel)

        # 配置点数和频率
        self.device.set('PointNumber', 4*4096, self.input_channel)

        # 读出频率列表（8个频率通道）
        if self.rd_freq is not None:
            freq_list = [self.rd_freq] * 8
        else:
            freq_list = [1e9] * 8  # 默认频率

        for ch in ['S9-I1', 'S9-I2', 'S9-I3', 'S9-I4']:
            self.device.set('FreqList', freq_list, ch)

        # 上传输出程序（单脉冲XY）
        if self.rd_amp is None:
            self.rd_amp = 0.9

        self.device.set('ProgramOUT',
                       _program_xy_onepulse(freq=self.rd_freq or 1e9,
                                           amp=self.rd_amp,
                                           width=4.096e-6,
                                           delay=self.delay),
                       self.output_channel)

    def _update_freq(self):
        """内部方法：快速更新频率"""
        freq_list = [self.rd_freq] * 8
        for ch in ['S9-I1', 'S9-I2', 'S9-I3', 'S9-I4']:
            self.device.set('FreqList', freq_list, ch)

    def _update_amp(self):
        """内部方法：快速更新幅度"""
        # 需要重新上传输出程序
        self.device.set('ProgramOUT',
                       _program_xy_onepulse(freq=self.rd_freq or 1e9,
                                           amp=self.rd_amp,
                                           width=4.096e-6,
                                           delay=self.delay),
                       self.output_channel)

    def measure(self):
        """
        执行一次测量

        返回：
        - dict: {
            'mag': float,      # IQ幅值
            'phase': float,    # IQ相位
            'iq_raw': array    # 原始IQ数据
          }
        """
        # 设置Shot数和触发
        self.qsync.set('Shot', self.shots)
        self.device.set('Shot', self.shots)
        self.device.set("TerminateUpload")
        self.device.set('StartCapture')
        time.sleep(0.1)

        # 生成触发信号
        self.qsync.set('GenerateTrig', self.period)

        # 读取IQ数据
        data = self.device.get('IQ', self.input_channel, self.shots)
        data = np.array(data)

        # 取平均值
        data_mean = np.mean(data, axis=1)

        # 计算幅值和相位
        mag = np.abs(data_mean[0])
        phase = np.angle(data_mean[0])

        return {
            'mag': mag,
            'phase': phase,
            'iq_raw': data
        }
