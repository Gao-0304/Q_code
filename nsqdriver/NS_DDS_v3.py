import copy
from enum import Enum
from math import ceil
from collections import namedtuple
from waveforms import Waveform, wave_eval, WaveVStack
from waveforms.waveform import _zero
from waveforms.math.signal import getFTMatrix, shift
import nsqdriver.nswave as nw

import numpy as np

try:
    import waveforms

    HAS_WAVEFORMS = True
except ImportError as e:
    HAS_WAVEFORMS = False

try:
    from .common import BaseDriver, Quantity, get_coef
except ImportError as e:

    class BaseDriver:

        def __init__(self, addr, timeout, **kw):
            self.addr = addr
            self.timeout = timeout


    class Quantity(object):

        def __init__(self, name: str, value=None, ch: int = 1, unit: str = ''):
            self.name = name
            self.default = dict(value=value, ch=ch, unit=unit)

    # def get_coef(*args):
    #     return '', '', '', ''

DEBUG_PRINT = False


def get_coef(coef_info, sampleRate):
    start, stop = coef_info['start'], coef_info['stop']
    numberOfPoints = int(
        (stop - start) * sampleRate)
    if numberOfPoints % 64 != 0:
        numberOfPoints = numberOfPoints + 64 - numberOfPoints % 64
    t = np.arange(numberOfPoints) / sampleRate + start

    fList = []
    wList = []
    phases = []

    for kw in coef_info['wList']:
        Delta, t0, weight, w, phase = kw['Delta'], kw['t0'], kw['weight'], kw['w'], kw['phase']
        fList.append(Delta)

        if w is not None:
            w = np.zeros(numberOfPoints, dtype=complex)
            w[:len(w)] = w
            w = shift(w, t0 - start)
            phases.append(np.mod(phase + 2 * np.pi * Delta * start, 2 * np.pi))
        else:
            weight = weight
            if isinstance(weight, np.ndarray):
                pass
            else:
                if isinstance(weight, str):
                    fun = wave_eval(weight) >> t0
                elif isinstance(weight, Waveform):
                    fun = weight >> t0
                else:
                    raise TypeError(f'Unsupported type {weight}')
                weight = fun(t)
            phase += 2 * np.pi * Delta * start
            w = getFTMatrix([Delta],
                            numberOfPoints,
                            phaseList=[phase],
                            weight=weight,
                            sampleRate=sampleRate)[:, 0]
            phases.append(np.mod(phase, 2 * np.pi))
        wList.append(w)
    return np.asarray(wList), fList, numberOfPoints, phases, round((stop - t0) * sampleRate), t


def get_demod_envelope(coef_info, demod_map, sampleRate):
    start, stop = coef_info['start'], coef_info['stop']
    t0 = coef_info['t0']
    numberOfPoints = int(
        (stop - start) * sampleRate)
    if numberOfPoints % 64 != 0:
        numberOfPoints = numberOfPoints + 64 - numberOfPoints % 64
    t = np.arange(numberOfPoints) / sampleRate + start
    demod_map_list = demod_map
    weight_sum = np.empty(numberOfPoints)
    for weight in demod_map_list:
        if isinstance(weight, np.ndarray):
            pass
        else:
            if isinstance(weight, str):
                fun = wave_eval(weight)
            elif isinstance(weight, Waveform):
                fun = weight
            else:
                raise TypeError(f'Unsupported type {weight}')
            weight = fun(t)
            weight_sum += weight
    return weight_sum




@nw.kernel
def program_cap(param: nw.Var):
    #
    nw.wait_for_trigger()
    i: nw.Var
    # param: [[100e-9, 1e-6], [200e-9, 1e-6]]
    # nw.wait(150e-9)
    for i in param:
        nw.wait(i[0])
        nw.capture(i[1], 0, 0)


@nw.kernel
def program_da(p: nw.Var):
    i: nw.Var
    e: nw.Var
    nw.init_frame(0, 0)
    nw.wait_for_trigger()
    # nw.reset_frame()
    e = nw.ins_envelope(p[0][1])
    for i in p:
        nw.wait(i[0])
        # e = nw.ins_envelope(i[1])
        nw.play_wave(e, 1, 0, 0)


ProbeSegment = namedtuple('ProbeSegment', ['start', 'stop', 'freq', 'demod', 'idx'])

CaptureCmd = namedtuple('CaptureCmd', [
    'start', 'ad_duration', 'delay', 'da_duration', 'freqs', 'delays', 'demod_wave_list', 'idx_list'
])


class DemodulateMode(str, Enum):
    MORE_QUBIT = 'more_qubit'
    COMPLEX_SEQ = 'complex_seq'


class Driver(BaseDriver):
    CHs = list(range(1, 25))
    segment = ('ns', '111|112|113|114|115')
    res_map = []

    quants = [
        Quantity('ReInit', value={}, ch=1),  # set, 设备重新初始化
        Quantity('Instruction', value=None, ch=1),  # set   参数化波形指令队列配置
        # 采集运行参数
        Quantity('Shot', value=1024, ch=1),  # set,运行次数
        Quantity('PointNumber', value=16384, unit='point'),  # set/get,AD采样点数
        Quantity('TriggerDelay', value=0, ch=1, unit='s'),  # set/get,AD采样延时
        Quantity('FrequencyList', value=[], ch=1,
                 unit='Hz'),  # set/get,解调频率列表，list，单位Hz
        Quantity('PhaseList', value=[], ch=1,
                 unit='Hz'),  # set/get,解调频率列表，list，单位Hz
        Quantity('Coefficient', value=None, ch=1),
        Quantity('DemodulationParam', value=None, ch=1),
        Quantity('CaptureMode'),
        Quantity('StartCapture'),  # set,开启采集（执行前复位）
        Quantity('TraceIQ', ch=1),  # get,获取原始时域数据
        # 返回：array(shot, point)
        Quantity('IQ', ch=1),  # get,获取解调后数据,默认复数返回
        # 系统参数，宏定义修改，open时下发
        # 复数返回：array(shot,frequency)
        # 实数返回：array(IQ,shot,frequency)

        # 任意波形发生器
        Quantity('Waveform', value=np.array([]), ch=1),  # set/get,下发原始波形数据
        Quantity('Delay', value=0, ch=1),  # set/get,播放延时
        Quantity('KeepAmp', value=0
                 ),  # set, 电平是否维持在波形最后一个值, 0：波形播放完成后归0，1：保持波形最后一个值，2:保持波形第一个值
        Quantity('Biasing', value=0, ch=1),  # set, 播放延迟
        Quantity('LinSpace', value=[0, 30e-6, 1000],
                 ch=1),  # set/get, np.linspace函数，用于生成timeline
        Quantity('Output', value=True, ch=1),  # set/get,播放通道开关设置
        Quantity('GenWave', value=None,
                 ch=1),  # set/get, 设备接收waveform对象，根据waveform对象直接生成波形
        # set/get, 设备接收IQ分离的waveform对象列表，根据waveform对象列表直接生成波形
        Quantity('GenWaveIQ', value=None, ch=1),
        Quantity('MultiGenWave', value={1: np.ndarray([])}),  # 多通道波形同时下发
        Quantity('EnableWaveCache', value=False),  # 是否开启waveform缓存
        Quantity('PushWaveCache'),  # 使waveform缓存中的波形数据生效
        # 混频相关配置
        Quantity('EnableDAMixer', value=False, ch=1),  # DA通道混频模式开关
        Quantity('MixingWave', ),  # 修改完混频相关参数后，运行混频器
        Quantity('DAIQRate', value=1e9, ch=1),  # 基带信号采样率
        Quantity('DALOFreq', value=100e6, ch=1),  # 中频信号频率
        Quantity('DALOPhase', value=0, ch=1),  # 基带信号相位，弧度制
        Quantity('DASideband', value='lower', ch=1),  # 混频后取的边带
        Quantity('DAWindow', value=None, ch=1),
        # 基带信号升采样率时所使用的窗函数，默认不使用任何窗，
        # 可选：None、boxcar、triang、blackman、hamming、hann、bartlett、flattop、parzen、bohman、blackmanharris、nuttall、
        # barthann、cosine、exponential、tukey、taylor

        # 内触发
        Quantity('GenerateTrig', value=1e7,
                 unit='ns'),  # set/get,触发周期单位ns，触发数量=shot
        Quantity('UpdateFirmware', value='', ch=1),  # qsync固件更新
        Quantity('PipInstall')  # pip install in instance
    ]

    def __init__(self, addr: str = '', timeout: float = 10.0, **kw):
        super().__init__(addr, timeout=timeout, **kw)
        self.handle = None
        self.model = 'NS_MCI'  # 默认为设备名字
        self.srate = 8e9
        self.ad_srate = 4e9
        self.addr = addr
        self.timeout = timeout
        self.chs = set()  # 记录配置过的ch通道
        self.IQ_cache = {}
        self.coef_cache = {}
        self.res_maps = {}
        self.demod_maps = {}
        self.probe_da_wave = {}
        # self.probe_delay = 32e-9
        self.probe_delay = 0
        self.capture_cmds: "dict[int, list[CaptureCmd]]" = {}
        self.capture_cali_param: "dict[int, np.ndarray]" = {}
        self.capture_points: "dict[int, np.ndarray]" = {}
        self.demodulate_mode = DemodulateMode.MORE_QUBIT
        self.demode_calculus: "dict[int, np.ndarray]" = {}

    def open(self, **kw):
        """
        输入IP打开设备，配置默认超时时间为5秒
        打开设备时配置RFSoC采样时钟，采样时钟以参数定义
        """
        from nsqdriver import MCIDriver

        DArate = 8e9
        ADrate = 4e9
        sysparam = {
            "MixMode": 2,
            "RefClock": "out",
            "DArate": DArate,
            "ADrate": ADrate,
            "CaptureMode": 0,
            "INMixMode": 2,  # 4～6 GHz 取 1， 6 ～ 8 GHz 取 2
        }
        sysparam.update(kw.get('system_parameter', {}))

        device = MCIDriver(self.addr, self.timeout)
        device.open(system_parameter=sysparam)
        self.handle = device

    def granularity4ns(self, delay):
        # points_4ns = 16  # self.ad_srate*4e-6
        return delay // 4 * 4

    @staticmethod
    def _delay2_phase(delay, freq):
        return 2 * np.pi * freq * (delay * 1e-9)

    def in_sequence_in_time(self, coef_info: dict) -> list[CaptureCmd]:
        w_list = coef_info.get('wList', [])
        time_segments: "list[ProbeSegment]" = []

        for idx, wave in enumerate(w_list):
            t0 = int(round(wave['t0'] * 1e9))
            weight_expr = wave['weight']

            # 假设 weight 表达式格式为 "square(X) >> Y"，我们提取实际时间宽度
            # duration = float(weight_expr.split('>>')[1].strip())
            _start, _stop, _ = wave_eval(weight_expr).bounds
            _start, _stop = int(round(_start * 1e9)), int(round(_stop * 1e9))

            # 将区间加入列表
            seg = ProbeSegment(t0 + _start, t0 + _stop, wave['Delta'], weight_expr, idx)
            time_segments.append(seg)

        # 按起始时间排序
        time_segments.sort()

        # 结果存储
        non_overlapping_segments: list[CaptureCmd] = []
        current_start, current_end = time_segments[0].start, time_segments[0].stop
        current_cmd = CaptureCmd(0, 0, 0, 0, [time_segments[0].freq], [0.],[time_segments[0].demod],
                                 [time_segments[0].idx])
        pointer = 0
        for seg in time_segments[1:]:
            if seg.start > current_end:
                # 如果不重叠，保存当前段并移动到下一段
                if pointer == 0:
                    current_cmd = current_cmd._replace(start=current_start)
                else:
                    current_cmd = current_cmd._replace(start=current_start - self.probe_delay)
                current_cmd = current_cmd._replace(ad_duration=current_end - current_start)
                current_cmd = current_cmd._replace(delay=self.probe_delay)
                current_cmd = current_cmd._replace(da_duration=current_end - current_start)
                current_cmd = current_cmd._replace(demod_wave_list=[time_segments[0].demod])
                non_overlapping_segments.append(current_cmd)

                current_cmd = CaptureCmd(0, 0, 0, 0, [seg.freq], [0.], [seg.demod], [seg.idx])
                pointer = current_end
                current_start, current_end = seg.start, seg.stop
            else:
                # 如果有重叠，扩展当前段
                current_end = max(current_end, seg.stop)
                current_cmd.idx_list.append(seg.idx)
                current_cmd.freqs.append(seg.freq)
                current_cmd.demod_wave_list.append(seg.demod)
                # 由delay换算解缠绕相位
                current_cmd.delays.append(seg.start - current_start)
        else:
            # 添加最后一个段
            current_cmd = current_cmd._replace(start=current_start - self.probe_delay)
            current_cmd = current_cmd._replace(ad_duration=current_end - current_start)
            current_cmd = current_cmd._replace(delay=self.probe_delay)
            current_cmd = current_cmd._replace(da_duration=current_end - current_start)
            non_overlapping_segments.append(current_cmd)
        return non_overlapping_segments

    def generate_in_program(self, coef_info, ch):
        freq_map = []
        demod_wave_map = []
        seq_param = []

        self.capture_cmds[ch] = seq = self.in_sequence_in_time(coef_info)

        for segment in seq:
            demod_wave_map.extend(segment.demod_wave_list)
            demod_wave_map = list(set(demod_wave_map))
            freq_map.extend(segment.freqs)
            freq_map = list(set(freq_map))

        _t_end = 0
        res_map = [[]]*len(coef_info['wList'])
        phase_map = [0]*len(coef_info['wList'])
        points_map = [0]*len(coef_info['wList'])
        for cap_num, segment in enumerate(seq):
            _align_start = self.granularity4ns(segment.start)  # 向前取整
            _start_diff = segment.start - _align_start
            _align_end = ceil((segment.start+segment.ad_duration)/4)*4  #向上取整
            seq_param.append([
                (_align_start-_t_end)*1e-9,
                (_align_end-_align_start)*1e-9,
                segment.delay*1e-9,
                (_align_end-_align_start)*1e-9,
            ])
            _t_end = _align_end
            for idx, delay, freq, demod_wave in zip(segment.idx_list, segment.delays, segment.freqs,
                                        segment.demod_wave_list):
                res_map[idx] = [freq_map.index(freq), cap_num]
                phase_map[idx] = self._delay2_phase(delay + _start_diff, freq)  # 向前取整的缩进加上起始时间的差值来计算相位
                points_map[idx] = segment.ad_duration * 1e-9 * self.ad_srate

        self.res_maps[ch] = res_map
        self.capture_cali_param[ch] = np.exp(-1j * np.array(phase_map)).reshape((-1, 1))
        self.capture_points[ch] = np.array(points_map).reshape((-1, 1))
        return program_cap(seq_param), freq_map, demod_wave_map

    def out_sequence_in_time(self, wave_list: list):
        last_start = wave_list[0][0]
        last_stop = wave_list[0][1]
        temp_w = [wave_list[0][2]]
        _res = []

        for idx, (start, stop, seg) in enumerate(wave_list[1:]):
            if start > last_stop:
                _res.append([last_start, last_stop, np.hstack(temp_w)])
                last_start = start
                last_stop = stop
                temp_w.clear()
                temp_w.append(seg)
            else:
                last_stop = max(last_stop, stop)
                temp_w.append(seg)
        else:
            _res.append([last_start, last_stop, np.hstack(temp_w)])
        return _res

    def gen_wave_frag(self, x, wave: "Waveform"):
        range_list = np.searchsorted(x, wave.bounds)
        # ret = np.zeros_like(x)
        ret = []
        start, stop = 0, 0
        for i, stop in enumerate(range_list):
            if start < stop and wave.seq[i] != _zero:
                _w = copy.deepcopy(wave)
                _w.start = start / self.srate
                _w.stop = stop / self.srate
                part = _w.sample(self.srate)
                part = part if part is None else part[:(stop-start)]
                ret.append((start, stop, part))
            start = stop
        else:
            if not ret:
                ret.append((0, 128, np.zeros((128,))))
        return ret

    def generate_out_program(self, _wave, ch):
        align_points = 32  # 4ns*8e9
        if isinstance(_wave, WaveVStack):
            _wave = _wave.simplify()
        if len(_wave.seq) == 1 and _wave.seq[0] == _zero:
            wave_list = [(0, 128, np.zeros((128,)))]
        else:
            _wave.stop = _wave.bounds[-2]
            wave_list = self.gen_wave_frag(
                np.linspace(_wave.start, _wave.stop, int((_wave.stop - _wave.start) * self.srate)), _wave)
        # print(f'generate_out_program: {_wave.start=}, {_wave.stop=}, {wave_list=}, {ch=}')
        _t_end = 0
        para = []
        wave = self.out_sequence_in_time(wave_list)

        for i in wave:
            wait = (i[0] - _t_end)
            align_wait = wait // align_points * align_points
            zero_num = wait - align_wait
            align_end = ceil(i[1] / align_points) * align_points
            align_wave = [np.zeros(zero_num), i[2], np.zeros([align_end - i[1]])]
            para.append([align_wait / self.srate, np.hstack(align_wave)])
            _t_end = align_end
        return program_da(para)

    def get_coef_res(self, iq_res, ch):
        res = []
        for (freq_num, cap_num) in self.res_maps[ch]:
            res.append(iq_res[freq_num][cap_num::len(self.capture_cmds[ch])])
        # 采样点归一化
        res = np.array(res) / self.demode_calculus[ch]
        # 校准相位
        res *= self.capture_cali_param[ch]

        return res

    def close(self, **kw):
        """
        关闭设备
        """
        if getattr(self, 'handle', None) is not None:
            self.handle.close()
            self.handle = None

    def set(self, *args, **kwargs):
        return self.handle.set(*args, **kwargs)

    def get(self, *args, **kwargs):

        return self.handle.get(*args, **kwargs)

    def write(self, name: str, value, **kw):
        channel = kw.get('ch', 1)
        # print(f'NS_DDS_v3 write: {name=}, {channel=}')
        if name in {'Coefficient'}:
            coef_info = value
            self.chs.add(channel)
            kernel, freq_map, demod_wave_map = self.generate_in_program(coef_info, channel)
            self.handle.set("ProgramIN", kernel, channel)
            demode_wave = get_demod_envelope(coef_info, demod_wave_map, sampleRate=8e9)
            self.demode_calculus[channel] = np.sum(demode_wave)
            self.handle.set("DemodulationParam", demode_wave, channel)
            self.handle.set('TimeWidth', 2e-6, channel)

            self.handle.set("FreqList", freq_map, channel)
            self.coef_cache.update({channel: coef_info})
        elif name in {
            'CaptureMode', 'SystemSync', 'ResetTrig', 'TrigPeriod',
            'TrigFrom'
        }:
            pass
        elif name in {
            'GenWave', 'Waveform'
        } and isinstance(value, Waveform):
            kernel_da = self.generate_out_program(value, channel)
            self.handle.set("ProgramOUT", kernel_da, channel)
        else:
            if name in {"Shot"}:
                self.shots = value
            return self.handle.set(name, value, channel)

    def read(self, name: str, **kw):
        channel = kw.get('ch', 1)
        if name in {"IQ"}:
            iq_res = self.handle.get(
                "IQ", channel, round(self.shots * len(self.capture_cmds[channel]))
            )

            result = self.get_coef_res(iq_res, channel).T
            if len(self.chs) != 0 and channel in self.chs:
                self.chs.remove(channel)
            # self.IQ_cache.update({channel: result})
            if len(self.chs) == 0:
                self.write("TerminateUpload", 1)  # 实验的开始必须加此句话
        else:
            result = self.handle.get(name, channel)
        return result


if __name__ == '__main__':
    co = {'start': 0.0, 'stop': 10e-06, 'wList': [
        {'Delta': 6796613333.333333, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 1.5e-08, 'phi': 2.4311851282940524, 'threshold': 9.645718574523926},
        {'Delta': 6965129999.666667, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 2.345e-06, 'phi': 2.1739656328752264, 'threshold': 20.36802101135254},
        {'Delta': 6866353333.333333, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 2.345e-06, 'phi': 1.851749364542847, 'threshold': 21.65827751159668},
        {'Delta': 6796613333.333333, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 5.175e-06, 'phi': 2.4311851282940524, 'threshold': 9.645718574523926},
        {'Delta': 6965129999.666667, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 5.175e-06, 'phi': 2.1739656328752264, 'threshold': 20.36802101135254},
        {'Delta': 6866353333.333333, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 5.175e-06, 'phi': 1.851749364542847, 'threshold': 21.65827751159668},
        {'Delta': 6796613333.333333, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 7.805e-06, 'phi': 2.4311851282940524, 'threshold': 9.645718574523926},
        {'Delta': 6796613333.333333, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 8.805e-06, 'phi': 2.4311851282940524, 'threshold': 9.645718574523926},
        {'Delta': 6965129999.666667, 'phase': -0.0, 'weight': 'square(8e-07) >> 4e-07', 'window': (0, 1024), 'w': None,
         't0': 9.005e-06, 'phi': 2.4311851282940524, 'threshold': 9.645718574523926}
    ]}
    import matplotlib.pyplot as plt
    from nsqdriver import QSYNCDriver
    import time
    import waveforms as wf
    from nsqdriver.NS_MCI import SHARED_DEVICE_MEM

    SHARED_DEVICE_MEM.clear_ip()
    _d = Driver('192.168.0.43', 300)
    qsync = QSYNCDriver("192.168.0.43")
    _d = Driver('192.168.0.228', 30)
    _q = QSYNCDriver('192.168.0.228')
    time.sleep(5)
    _wave = wf.zero()
    for _w in co['wList']:
        t0 = _w['t0']
        _wave += (wf.wave_eval(_w['weight']) * wf.cos(2 * np.pi * _w['Delta'])) >> t0
    # _wave = _wave << 50e-9
    _wave.start = 0
    _wave.stop = 60e-6

    _wave(np.linspace(0, 20e-6, int(20e-6 * 8e9)), frag=True)

    wave = _wave.sample(8e9) / 3
    _wave

    for ch in range(3, 4):
        _d.write('GenWave', _wave, ch=ch)
        _d.write('Coefficient', co, ch=ch)
    # res = _d.generate_para(co, 1)
    _d.write("Coefficient", co, ch=2)
    ch = 2
    # wave = wf.cos(2*wf.pi*0.15e9)
    # wave.start = 0
    # wave.stop = 1e-6

    _wave = waveforms.zero()
    for _w in co['wList']:
        t0 = _w['t0']
        _wave += (waveforms.wave_eval(_w['weight']) * waveforms.cos(2 * np.pi * _w['Delta'])) >> t0
    # _wave = _wave << 50e-9
    _wave.start = 0
    _wave.stop = co["stop"]
    plt.plot(_wave.sample(8e9))
    plt.show()
    _d.write("GenWave", _wave, ch=2)
    _d.set('CaptureMode', 1)
    shots = 1024
    qsync.set('Shot', shots)
    _d.write('Shot', shots)
    _d.set('StartCapture')
    qsync.set('GenerateTrig', 400e-6)
    time.sleep(400e-6 * shots + 0.5)
    data = _d.get('TraceIQ', ch)
    data = np.array(data)
    print(data.shape)
    data = data.reshape((shots, -1))
    # qsync.set("Shot", 0xFFFFFFFF)
    # qsync.set("GenerateTrig", 500e-6)
    plt.figure()
    plt.plot(data.mean(axis=0)[:])
    plt.show()
    _d.set('CaptureMode', 0)
    _d.write("Coefficient", co, ch=2)
    _d.write("GenWave", _wave, ch=2)
    _d.set('StartCapture')
    qsync.set('GenerateTrig', 40e-6)
    data = _d.read("IQ", ch=2)
    print(20 * np.log10(np.abs(data.mean(axis=0))))
    pass
