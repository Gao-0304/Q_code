"""
设备管理层 - XY驱动器类
"""
import numpy as np


class XYDrive:
    """
    XY微波驱动器类
    存储7元组波形参数 + 固定硬件信息，支持全定义和快速修改

    7元组来自waveform_bank:
    [0]: shape_list     - 脉冲形状（如'Square'）
    [1]: pw_list        - 脉冲宽度列表
    [2]: ew_list        - 包络宽度列表
    [3]: amp_list       - 幅度列表
    [4]: center_list    - 中心位置列表
    [5]: phase_list     - 相位列表
    [6]: freq_list      - 频率列表
    """

    def __init__(self, device, qsync, channel, darate):
        """
        初始化XY驱动器

        参数：
        - device: MCIDriver对象
        - qsync: QSYNCDriver对象
        - channel: 输出通道，如 "S5-O1"
        - darate: DA采样率 (Hz)，如 8e9
        """
        self.device = device
        self.qsync = qsync
        self.channel = channel
        self.darate = darate

        # 7元组波形参数
        self.shape_list = []
        self.pw_list = []
        self.ew_list = []
        self.amp_list = []
        self.center_list = []
        self.phase_list = []
        self.freq_list = []

        # 时序参数
        self.delay = None
        self.spacing_time = 24e-9

    def configure(self, shape_list, pw_list, ew_list, amp_list,
                  center_list, phase_list, freq_list, delay, spacing_time=24e-9):
        """
        全定义：一次性设置所有7元组参数和时序

        参数：
        - shape_list: 脉冲形状列表，如 ['Square']
        - pw_list: 脉冲宽度列表 (秒)
        - ew_list: 包络宽度列表 (秒)
        - amp_list: 幅度列表 (0-1)
        - center_list: 中心位置列表
        - phase_list: 相位列表 (度)
        - freq_list: 频率列表 (Hz)
        - delay: 脉冲前置延迟 (秒)
        - spacing_time: 多脉冲间隔 (秒)，默认24ns
        """
        self.shape_list = shape_list
        self.pw_list = pw_list
        self.ew_list = ew_list
        self.amp_list = amp_list
        self.center_list = center_list
        self.phase_list = phase_list
        self.freq_list = freq_list
        self.delay = delay
        self.spacing_time = spacing_time

        self._upload_waveform()

    def set_amplitudes(self, amp_list):
        """快速修改：只改变幅度"""
        self.amp_list = amp_list
        self._update_quick()

    def set_frequencies(self, freq_list):
        """快速修改：只改变频率"""
        self.freq_list = freq_list
        self._update_quick()

    def set_pulse_widths(self, pw_list):
        """快速修改：只改变脉冲长度"""
        self.pw_list = pw_list
        self._update_quick()

    def set_phases(self, phase_list):
        """快速修改：只改变相位"""
        self.phase_list = phase_list
        self._update_quick()

    def zero(self):
        """置零：停止输出"""
        self.device.set("Output", 0, self.channel)

    def _upload_waveform(self):
        """
        内部方法：上传完整波形和程序
        迁移自原Multigate_sequence_new函数
        """
        # 提取参数简化
        ch = int(self.channel.split("-O")[1])
        delay = self.delay
        spacing_time = self.spacing_time

        shape = self.shape_list[0]
        pw_list = self.pw_list
        ew_list = self.ew_list
        freq_list = self.freq_list
        phase_list = self.phase_list
        amp_list = self.amp_list

        darate_xy = self.darate
        # 计算cycle（与原代码保持一致）
        adrate = 4e9  # 固定值
        cycle = round((adrate * 1e-9) * (darate_xy * 1e-9) * 0.125)

        # 计算新的脉冲宽度（按cycle对齐）
        pw_list_new = [
            round(cycle * np.ceil(round((pw_one)*1e9*10)/10/cycle)) * 1e-9
            for pw_one in pw_list
        ]

        # 计算整个序列长度
        sequence_length = (
            sum(pw_list_new) + 2*sum(ew_list) + (len(self.shape_list)-1)*spacing_time
        )
        delay_adjusted = delay - sequence_length

        wait_cycle0 = round(delay_adjusted * 1e9 / cycle)

        # 构建pw字典
        pw_dict = {}
        for pw_one in pw_list:
            pw_one_mod = str(round(pw_one*darate_xy % (darate_xy*1e-9*cycle)))
            if (pw_one_mod not in pw_dict) or (pw_one > pw_dict[pw_one_mod]):
                pw_dict[pw_one_mod] = pw_one

        # 生成包络
        envelope = np.array([])
        start_slice_dict = {}

        for key in pw_dict:
            pw = pw_dict[key]
            if shape == 'Square':
                w = round(pw * darate_xy)
                pw_cycle = round(np.ceil(round((pw)*1e9*10)/10/cycle))
                if pw_cycle < 8:
                    pw_cycle = 8
                e = round((pw_cycle*cycle*1e-9-pw)*darate_xy)
                if e:
                    env = np.concatenate((np.zeros(e), np.ones(w)))
                else:
                    env = np.ones(w)

            start_slice = round(len(envelope)//32)
            start_slice_dict[key] = start_slice
            envelope = np.concatenate((envelope, env))

        wave = envelope
        wave = np.hstack(1 * (wave,))

        # 设置输出和包络
        self.qsync.set("ResetTrig")
        self.device.set("Output", 1, self.channel)
        self.device.set("Envelope", wave, self.channel)

        # 生成汇编程序
        xyfreq = freq_list[0]
        fs = darate_xy
        freq = round(xyfreq * (2**32) / fs)

        phi = 0
        program = f"""
    nop
    fmsi 0b1 {freq} {phi} # 设置frame1的频率和相位
    nop
    nop
    nop
    nop
    nop
    wtg
    nop
    nop
    nop
    nop
    nop
    witi {wait_cycle0}
    """

        # 为每个脉冲生成指令
        for i in range(len(phase_list)):
            phi = phase_list[i] % 360
            phi = round(phi * (2**16) / 360 / 32)

            pw = pw_list[i]
            play_cycle = round(np.ceil(round((pw)*1e9*10)/10/cycle))
            if play_cycle < 8:
                play_cycle = 8

            spacing_cycle = np.ceil(round((spacing_time)*1e9*10)/10/cycle)
            wait_cycle = round(play_cycle + spacing_cycle - 2 - 2 - 3)

            amp_dig = round(amp_list[i] * 32767)
            pw_now_mod = str(round(pw*darate_xy % (darate_xy*1e-9*cycle)))
            start_slice = start_slice_dict[pw_now_mod]

            program += f"""nop
    nop
    nop
    plyi 0 {start_slice} {play_cycle} {amp_dig} 0 0 {phi}
    witi {wait_cycle}
    """

        program += f"""nop
    nop
    nop
    jali $0 # 跳转回开始
    nop
    nop
    nop
    """

        # 上传程序
        self.device.set("Assemble", program, self.channel)

    def _update_quick(self):
        """
        内部方法：快速更新（仅改变参数，不需要重新编译包络和程序）
        """
        # 对于频率/幅度等参数变化，可能只需要更新某些寄存器
        # 目前保留为占位符，具体实现需要根据设备API调整
        self._upload_waveform()  # 暂时仍然重新上传（可后续优化）
