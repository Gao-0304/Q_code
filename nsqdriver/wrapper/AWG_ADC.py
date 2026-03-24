import enum
import abc
import dataclasses
from typing import List, Union, Dict, Iterable, Sized
from functools import wraps

import numpy as np
from ..NS_MCI import Driver as MCIDriver
from ..NS_QSYNC import Driver as QSYNCDriver

MIX_BIT_WIDTH = 32767
SEGMENT_ENABLE = False


@dataclasses.dataclass
class DAChannelData:
    seg_waves: "Sized|Iterable[np.ndarray]" = tuple()
    delays: "Sized|Iterable[float]" = tuple()
    data = np.array([0])
    updated: bool = False

    @property
    def right(self) -> bool:
        return len(self.seg_waves) == len(self.delays)

    def compute_data(self, rate):
        """计算最后可下发给设备的data

        :param rate: DA采样率，单位Hz
        :return:
        """
        if not self.updated:
            return
        # if not self.right:
        #     print(f'警告：波形片段数{len(self.seg_waves)}与波形延迟数{len(self.delays)}不匹配')
        #     return
        data = []
        for seg, delay in zip(self.seg_waves, self.delays):
            seg = seg / MIX_BIT_WIDTH
            data.append(np.zeros((round(float(delay) * rate),)))
            data.append(seg)
        self.data = np.hstack(data)


class ChannelDataPara(DAChannelData):
    def __check_waveform(self, wave):
        if wave.stop is None:
            raise ValueError('waveform.stop为None，应为一确定波形时宽')
        wave.start = 0 if wave.start is None else wave.start

    def compute_data(self, rate):
        import waveforms
        if not self.updated:
            return
        if not self.right:
            print(f'警告：波形片段数{len(self.seg_waves)}与波形延迟数{len(self.delays)}不匹配')
            return
        data = waveforms.zero()
        wave_width = 0
        for seg, delay in zip(self.seg_waves, self.delays):
            seg: waveforms.Waveform
            self.__check_waveform(seg)
            wave_width += delay
            window = waveforms.square(seg.stop - seg.start) >> seg.start
            data += ((window*seg) >> wave_width)
            wave_width += (seg.stop - seg.start)
        self.data = np.array(data)


@dataclasses.dataclass
class ADConfig:
    mixer_table: "np.ndarray" = np.zeros((1, 4096, 12, 2))
    delays: "List[float]" = tuple()
    updated: bool = False
    coff_param: "Union[np.ndarray, List[np.ndarray]]" = (np.zeros((12, 4096), dtype=np.complex64), )
    seg_conf: "List[List[float]]" = tuple()

    @property
    def right(self) -> bool:
        return self.mixer_table.shape[0] == len(self.delays)

    def compute_conf(self, rate):
        """计算最后可下发给设备的采集conf

        :param rate: AD采样率，单位Hz
        :return:
        """
        if not self.updated:
            return
        if not self.right:
            print(f'警告：mixer table片段数{len(self.mixer_table.shape[0])}与波形延迟数{len(self.delays)}不匹配')
            return
        coff_param = []
        seg_conf = []
        delay_count = 0
        seg_length = self.mixer_table.shape[1]/rate
        for idx, (table, delay) in enumerate(zip(self.mixer_table, self.delays)):
            table: "np.ndarray"
            table = table[:, :, 0] + table[:, :, 1]*1j
            coff_param.append(table.T)
            seg_conf.append([seg_length, delay_count])
            delay_count += seg_length+delay if idx != 0 else seg_length
        self.coff_param = coff_param
        self.seg_conf = seg_conf


class _BaseDriver(abc.ABC):
    class DARunMode(enum.IntEnum):
        TRIGGER_MODE = 1
        """触发模式"""
        CONTINUOUS_MODE = 2
        """连续模式"""

    class ADRunMode(enum.IntEnum):
        ALGORITHMIC_MODE = 1
        """算法采集模式"""
        TRACE_MODE = 2
        """时域采集模式"""

    mode_map = {}

    def __init__(self, *args):
        self.driver: "MCIDriver" = MCIDriver()
        self.sys_param = {
            'MixMode': 2,  # Mix模式，1：第一奈奎斯特去； 2：第二奈奎斯特区
            'PLLFreq': 100e6,  # 参考时钟频率, 单位为Hz
            'RefClock': 'out',  # 参考时钟选择： ‘out’：外参考时钟；‘in’：内参考时钟
            'ADrate': 4e9,  # AD采样率，单位Hz
            'DArate': 6e9,  # DA采样率，单位Hz
            'KeepAmp': 0,  # DA波形发射完毕后，保持最后一个值
            'Delay': 0,  # 配置DA的原生Delay
            'SegmentSampling': []  # 配置分段采样
        }
        self.connected = False

        self.run_mode = None
        self.run_count = 1024

    def connect(self, address, *args) -> bool:
        """连接设备

        :param address: 设备ip
        :param args:
        :return:
        """
        if self.connected and self.driver.addr != address:
            raise ValueError(f'系统已连接到{self.driver.addr}')
        self.driver = MCIDriver(address)
        self.driver.open()
        return self.init_system(*args)

    def disconnect(self, address, *args):
        if self.connected and self.driver.addr != address:
            raise ValueError(f'系统已连接到{self.driver.addr}，不可与{address}断开连接')
        self.connected = False

    @staticmethod
    def with_connected(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            self: "_BaseDriver" = args[0]
            if not self.connected:
                raise RuntimeError(f'系统未连接，不可调用{self.__class__.__name__}.{func.__name__}')
            return func(*args, **kwargs)

        return wrapper

    def update_sys_parm(self, _input):
        if len(_input) > 0 and isinstance(_input[0], dict):
            self.sys_param.update(_input[0])

    def init_system(self, *args) -> bool:
        self.update_sys_parm(args)
        self.connected = self.driver.init_device(system_parameter=self.sys_param)
        return self.connected

    def setRunMode(self, mode):
        """设置运行模式

        :param mode:
        :return:
        """
        self.run_mode = self.mode_map.get(mode, 1)

    # @with_connected
    def setCount(self, N):
        self.driver.set('Shot', N)
        self.run_count = N

    @abc.abstractmethod
    def start(self, channels):
        ...

    def stop(self, channels):  # 停止channels里面指定的通道的运行
        ...


class DAC(_BaseDriver):
    with_connected = _BaseDriver.with_connected
    mode_map = {
        2: _BaseDriver.DARunMode.CONTINUOUS_MODE,
        1: _BaseDriver.DARunMode.TRIGGER_MODE
    }

    def __init__(self, *args):
        super(DAC, self).__init__(*args)
        self.run_mode = self.DARunMode.TRIGGER_MODE
        self.run_wave_points = 0
        self.run_da_seg_cache: "Dict[int, DAChannelData]" = {}

    def initDAC(self):
        self.init_system()
        self.driver.set('EnableWaveCache', True)

    @with_connected
    def write_wave(self, waves, channeli):
        """
        给其中一个通道写波形，waves:[wave0,wave1,wave2,...]
        其中wave0,wave1,...为能直接写入fpga的int数组或uint数组，这里可以写一段或多段波形，
        触发模式下，仪器接收一个触发信号后，每段波形依次运行，波形之间的延迟可以通过setTriggerDelays函数设置
        注意，对于每一个触发信号，waves里的波形都会被运行

        :param waves: List[np.array]  int16
        :param channeli: int
        :return:
        """
        da_data = self.run_da_seg_cache.get(channeli, DAChannelData())
        da_data.seg_waves = waves
        da_data.updated = True
        self.run_da_seg_cache[channeli] = da_data
        # self._upload_wave([channeli])

    @with_connected
    def setTriggerDelays(self, delays, channeli):
        """
        设置trigger和发出波形之间的delays,只用于trig的运行模式，接收到trig后会前后相继的运行写入的[wave0,wave1,wave2,...]
        delays=[delay0,delay1,delay2,....]一一对应于[wave0,wave1,wave2,...]
        delay0为trig信号和wave0的起始时刻之间的延迟，delay1为wave0的末尾时刻和wave1的起始时刻之间的延迟，依次类推

        :param delays: List[float]
        :param channeli:
        :return:
        """
        da_data = self.run_da_seg_cache.get(channeli, DAChannelData())
        da_data.delays = delays
        da_data.updated = True
        self.run_da_seg_cache[channeli] = da_data
        self._upload_wave([channeli])

    @with_connected
    def write_param_waveform(self, wave, channeli):
        """发送要求wave为waveforms的Waveform对象

        :param wave:
        :param channeli:
        :return:
        """
        self.driver.set('GenWave', wave, channeli)

    @with_connected
    def start(self, channels):
        """当前后台仅能支持配置过波形的所有通道一起播放，后续支持

        :param channels:
        :return:
        """
        # 生效缓存的数据。支持ping-pang模式
        self.driver.set('PushWaveCache')
        if self.run_mode is self.DARunMode.CONTINUOUS_MODE:
            period = self.run_wave_points / self.sys_param['DArate']
            self.driver.set('GenerateTrig', period)

    def _upload_wave(self, channels=None):
        """按需计算要下发的data，并将缓存中“updated”的数据更新到设备中

        :param channels:
        :return:
        """
        channels = self.run_da_seg_cache.keys() if channels is None else channels
        rate = self.sys_param['DArate']
        for chnl in channels:
            if chnl not in self.run_da_seg_cache:
                continue
            da_data = self.run_da_seg_cache[chnl]
            da_data.compute_data(rate)
            if not da_data.updated:
                continue
            self.driver.set('Waveform', da_data.data, chnl)
            da_data.updated = False


class ADC(_BaseDriver):
    with_connected = _BaseDriver.with_connected
    mode_map = {
        1: _BaseDriver.ADRunMode.TRACE_MODE,
        2: _BaseDriver.ADRunMode.ALGORITHMIC_MODE
    }

    def __init__(self, *args):
        super(ADC, self).__init__(*args)
        self.run_mode = self.ADRunMode.ALGORITHMIC_MODE
        self.chnl_id = 0 if len(args) == 0 else args[0]
        self.run_ad_chnl_conf: "Dict[int, ADConfig]" = {}

    def initADC(self):
        """连接ADC后进行初始化

        :return:
        """
        self.init_system()

    @with_connected
    def write_mixerTable(self, mixData, channeli=None):
        """算法采集模式下，事先把要用于算法采集模式的权重数据写入ADC

        :param mixData: 如果ADC可以采集Y段波形，M为解模频点数，每段波形要在M个频率点做解模，时域波形一共L个点，
                        那mixData的shape为:(Y,L,M,2),类型为int数组 或uint数组  np.array  int16
        :param channeli:
        :return:
        """
        channeli = self.chnl_id if channeli is None else channeli
        ad_conf = self.run_ad_chnl_conf.get(channeli, ADConfig())
        ad_conf.mixer_table = mixData
        ad_conf.updated = True
        self.run_ad_chnl_conf[channeli] = ad_conf

    @with_connected
    def setTriggerDelays(self, delays, channeli=None):
        """设置trigger和采集波形之间的delays,接收到trig后会前后相继的采集waveDatas=[waveData0,waveData1,waveData2,...]
            delays = [delay0,delay1,delay2,....]一一对应于[waveData0,waveData1,waveData2,...]
            delay0为trig信号和waveData0的起始时刻之间的延迟，delay1为waveData0的末尾时刻和waveData1的起始时刻之间的延迟，依次类推

        :param delays: List[float]
        :param channeli:
        :return:
        """
        channeli = self.chnl_id if channeli is None else channeli
        ad_conf = self.run_ad_chnl_conf.get(channeli, ADConfig())
        ad_conf.delays = delays
        ad_conf.updated = True
        self.run_ad_chnl_conf[channeli] = ad_conf

    @with_connected
    def collectWaveData(self, channeli=None):
        """采集波形数据，waveDatas=[waveData0,waveData1,waveData2,...]，waveData? 为int数组，每接收一个trig，采集一次waveDatas
            时域采集模式下,waveData0为第一段时域波形数据,shape为（N,L）,N为采集波形的次数，算法采集模式下，waveData0为解模后的数据，shape为（N，M）
            ！注意该命令应该能在波形运行的过程中能采集，如果计划要采集N次，不能AWG的波形运行N次之后才采集，而是AWG边运行边采集，以加快速度

        :return:
        """
        try:
            channeli = self.chnl_id if channeli is None else channeli
            if channeli not in self.run_ad_chnl_conf:
                raise ValueError(f'未配置通道{channeli}的相关采集信息')
            ad_conf = self.run_ad_chnl_conf[channeli]
            seg_num = len(ad_conf.seg_conf)
            if self.run_mode is self.ADRunMode.TRACE_MODE:
                data = self.driver.get('TraceIQ', channeli)
                seg_length = data.shape[1]//seg_num
                data = [data[:, i:i+seg_length] for i in range(seg_num)]
            else:
                data = self.driver.get('IQ', channeli)
                print(data)
                if SEGMENT_ENABLE:
                    data = [data[i] for i in range(seg_num)]
            return data
        except Exception as e:
            print(e)

    def clearBuf(self):
        """清理ADC缓存的命令，假设上次运行报错，ADC能清理掉上次报错前所采集到的波形数据

        :return:
        """
        self.driver.write('ResetCollect', None)

    @with_connected
    def start(self, channels):
        """启动ADC的运行

        :param channels: QMAC有4个ad通道编号为 [1, 2, 3, 4]
        :return:
        """
        self._upload_collect_conf(channels)
        self.driver.set('StartCapture')

    def _upload_collect_conf(self, channels=None):
        """按需计算要下发的data，并将缓存中“updated”的数据更新到设备中

        :param channels:
        :return:
        """
        channels = self.run_ad_chnl_conf.keys() if channels is None else channels
        rate = self.sys_param['ADrate']
        for chnl in channels:
            if chnl not in self.run_ad_chnl_conf:
                continue
            ad_conf = self.run_ad_chnl_conf[chnl]
            ad_conf.compute_conf(rate)
            if not ad_conf.updated:
                continue
            self.driver.set('TriggerDelay', float(ad_conf.delays[0]), int(chnl))
            if SEGMENT_ENABLE:
                self.driver.set('SegmentSampling', ad_conf.seg_conf, int(chnl))
                self.driver.set('DemodulationParam', ad_conf.coff_param, int(chnl))
            else:
                self.driver.set('SegmentSampling', [], int(chnl))
                self.driver.set('DemodulationParam', ad_conf.coff_param[0], int(chnl))
            ad_conf.updated = False

class Trig(_BaseDriver):
    class RunMode(enum.IntEnum):
        INSIDE_MODE = 1
        """内部触发模式"""
        EXTERNAL_MODE = 2
        """外部触发模式"""

    mode_map = {
        1: RunMode.INSIDE_MODE,
        2: RunMode.EXTERNAL_MODE
    }
    with_connected = _BaseDriver.with_connected

    def __init__(self, *args):
        super(Trig, self).__init__(*args)
        self.sys_param = {
            'RefClock': 'in',  # 参考时钟选择： ‘out’：外参考时钟；‘in’：内参考时钟
            'TrigFrom': 0,  # Trig来源： 0：内部产生；1：外部输入
            'TrigPeriod': 200e-6,
            'DiscoveryMode': QSYNCDriver.ScannMode.local,  # QC/QR等被同步设备的发现方式，见DiscoveryMode说明
        }
        self.run_mode = self.RunMode.INSIDE_MODE
        self.driver: "QSYNCDriver" = QSYNCDriver()

    def connect(self, address, *args):
        self.driver = QSYNCDriver(address)
        self.update_sys_parm(args)
        self.driver.open(system_parameter=self.sys_param)
        self.connected = True

    @with_connected
    def initTrig(self):
        self.driver.set('ResetTrig')
        self.driver.sync_system()

    @with_connected
    def setClock(self, **kws):
        """设置时钟运行相关参数,比如外部或内部时钟，时钟频率等等

        :param kws: 参考信号 RefClock，TrigFrom
        :return:
        """
        self.update_sys_parm((kws, ))
        self.driver.open(system_parameter=self.sys_param)

    def checkStatus(self):  # 查看相关状态，比如时钟是多少MHz，是外部接入还是内部产生，trig信号的间隔，宽度，每个通道发出trig信号的延迟
        print(self.sys_param)

    @with_connected
    def setTrigOffset(self, time, channel):  # 设置通道channel的trigger信号的延迟
        self.driver.set('TrigOffset', time)

    @with_connected
    def setIntervalTime(self, time):  # 设置触发
        """
        :param time: 秒
        """
        self.driver.set('TrigPeriod', time)

    def setIntervalShape(self, width, amplitude):  # 设置触发信号宽度和高度
        self.driver.set('TrigWidth', width)

    def start(self, channels):  # 启动trig信号的运行
        if self.run_mode is self.RunMode.INSIDE_MODE:
            self.driver.set('GenerateTrig')

    def stop(self, channels):  # 停止trig信号的运行
        if self.run_mode is self.RunMode.INSIDE_MODE:
            self.driver.set('ResetTrig')


trig = Trig


if __name__ == '__main__':
    from waveforms import *

    sample_rate = 6e9
    width = 20e-9
    time_line = np.linspace(0, width*10, int(width * 10 * sample_rate))
    waves = {
        'poly': poly([1, -1 / 2, 1 / 6, -1 / 12]),
        'cos': cos(2 * pi * 5.2e9),
        'sin': sin(2 * pi * 5.2e9),
        'gaussian': gaussian(width) >> (width * 2),
        'sinc': sinc(6e8),
        'square': square(width) >> (width * 2),
        'cosPulse': cosPulse(width) >> (width * 2),
        'chirp_linear': chirp(1e9, 1.5e9, width * 10, type='linear'),
        'chirp_exponential': chirp(1e9, 1.5e9, width * 10, type='exponential'),
        'chirp_hyperbolic': chirp(1e9, 1.5e9, width * 10, type='hyperbolic'),
        'cos*gaussian': cos(2 * pi * 5.2e9) * gaussian(width) >> (width * 2),
        'cos*cosPulse': cos(2 * pi * 5.2e9) * cosPulse(width) >> (width * 2),
        'gaussian_with_window': (gaussian(10) >> width * 2) + square(width, edge=5, type='linear') * cos(
            2 * pi * 5.2e9),
    }

    ip = '192.168.1.141'
    trig = Trig()
    adc = ADC()
    dac = DAC()

    trig.connect(ip, {'RefClock': 'in'})
    adc.connect(ip)
    dac.connect(ip)
    adc.initADC()
    dac.initDAC()
    trig.initTrig()

    dac.write_wave([MIX_BIT_WIDTH*waves['cos*gaussian'](time_line), MIX_BIT_WIDTH*waves['chirp_linear'](time_line)], 1)
    dac.setTriggerDelays([100e-9, 200e-9], 1)
    dac.setCount(1024)
    dac.start([1])

    adc.setCount(1024)
    adc.write_mixerTable(np.ones((1, 16384, 1, 2)), 1)
    adc.setTriggerDelays([0], 1)
    adc.start([1])

    trig.setIntervalTime(200e-6)
    trig.setCount(1024)
    trig.start([])

    data = adc.collectWaveData(1)
