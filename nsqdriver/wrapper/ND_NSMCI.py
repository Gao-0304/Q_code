import numpy as np
from nsqdriver import MCIDriver, QSYNCDriver


class _XYChannel:
    def __init__(self, mci: "DeviceBase", ch=1):
        self.mci = mci
        self.ch = ch
        self.to_zero = np.zeros((16,))
        self.to_one = np.ones((16,))
        self.en = True
        self.mode = 0
        self.off = 0

    def wave(self, w):
        self.wavex(w, self.ch)

    def wavex(self, w, idx):
        if np.max(np.abs(w)) < 1e-30:
            wr = np.zeros(16)
        else:
            wr = w
        self.mci.mci_driver.set("Waveform", wr, idx)

    def arm(self, k=None):
        self.mci.mci_driver.set('PushWaveCache')

    def trig_del(self, delay):
        ...

    def output_del(self, delay):
        ...

    def __del__(self):
        pass

    def output(self, b):
        self.en = bool(b)
        if not self.en:
            self.mci.mci_driver.set("Waveform", self.to_zero, self.ch)

    def mode(self, m_):
        ...

    def offsetx(self, off, idx):
        self.mci.mci_driver.set('Waveform', off*self.to_one, idx)
        self.off = off

    def offset(self, off):
        self.offsetx(off, self.ch)

    W = {
        "wave": wave,
        "output": output,
        "trig_del": trig_del,
        "output_del": output_del,
        "mode": mode,
        "offset": offset,
    }

    Q = {"arm": arm}


class _ZChannel(_XYChannel):
    pass


class _Probe:
    def __init__(self, mci: "DeviceBase", ch=1):
        self.mci = mci
        self.ch = ch
        self.freqList = []
        self.SGS = None  # single shot temp cache
        self.AVG = None  # average temp cache
        self.depth = 2000
        self._width = 1000
        self.start = 500
        self.demod = 1
        self.averaged_I = np.zeros((16384, ))  # 直播直采，相当于只有I路数据

    def depth(self, depth_):
        self.depth = depth_
        self.mci.mci_driver.set('PointNumber', depth_, self.ch)

    def demodulation_on(self, demod_):
        self.demod = int(demod_)

    def start(self, start_):
        self.start = start_
        self.mci.mci_driver.set('TriggerDelay', start_, self.ch)

    def width(self, width_):
        self._width = width_/4e9
        self.mci.mci_driver.set('PointNumber', width_, self.ch)

    def freqs(self, *freqList_):
        self.freqList = freqList_
        self.mci.mci_driver.set('FreqList', freqList_, self.ch)

    def shot(self, _shot):
        self.mci.mci_driver.set('Shot', _shot)

    def measure(self, k=None):
        self.mci.mci_driver.set('StartCapture')
        if self.demod:
            self.SGS = self.mci.mci_driver.get('IQ', self.ch)
            self.AVG = np.mean(self.SGS, axis=0)
        else:
            self.averaged_I = np.mean(self.mci.mci_driver.get('TraceIQ', self.ch), axis=0)

    def single_shot(self, k=None):
        return self.SGS

    def average(self, k=None):
        return self.AVG

    def trace_I(self, k=None):
        return self.averaged_I

    def trace_Q(self, k=None):
        return self.averaged_I

    def __del__(self):
        pass

    W = {
        "demod": demodulation_on,
        "depth": depth,
        "width": width,
        "start": start,
        "freqs": freqs,
        "shot": shot,
    }

    Q = {
        "measure": measure,
        "A": average,
        "S": single_shot,
        "traceI": trace_I,
        "traceQ": trace_Q
    };


# one box need one class
class DeviceBase:
    def __init__(self):
        self.mci_driver = MCIDriver('127.0.0.1')
        self.qsync_driver = QSYNCDriver('127.0.0.1')


class NS_MCI(DeviceBase):
    def __init__(self, addr, srate=10e9, mixmode=2, ref_clk='in'):
        """!
        此类涉及到系统同步，放到最后实例化
        @param addr: 设备ip
        @param srate: OUT通道采样率
        @param mixmode: 为2时开启OUT通道混合模式，增强第二奈奎斯特区输出
        @param ref_clk: 设备参考信号来源，不接外输出100M时都配置为'in'
        """
        super(NS_MCI, self).__init__()
        self.mci_driver = MCIDriver(addr)
        self.qsync = QSYNCDriver(addr)
        self.srate = srate
        self.mixmode = mixmode
        self.ref_clk = ref_clk
        self.connect()

    def connect(self):
        mci_params = {'DArate': self.srate, 'MixMode': self.mixmode}
        qsync_params = {'RefClock': self.ref_clk}

        self.qsync.open(system_parameter=qsync_params)
        self.mci_driver.open(system_parameter=mci_params)
        self.qsync.sync_system()

        self.mci_driver.set('EnableWaveCache', True)

        for _ch in range(22):
            xy_ch = _ch+1
            setattr(self, f'OUT{xy_ch}', _XYChannel(self, xy_ch))
        for _ch in range(2):
            probe_ch = _ch+1
            setattr(self, f'IN{probe_ch}', _Probe(self, probe_ch))

    def trig_interval(self, interval):
        self.interval = interval
        self.qsync.set('TrigPeriod', int(interval))

    def trig_count(self, count_):
        self.qsync.set('Shot', int(count_))

    def trig(self):
        self.qsync.set('GenerateTrig', self.interval)

    def awg_arm(self):
        self.mci_driver.set('PushWaveCache')

    def __del__(self):
        pass

    W = {
        "trig_interval": trig_interval,
        "trig_count": trig_count,
        "connect": connect,
        "trig": trig,
        "awg_arm": awg_arm,
    }

    Q = {
    }


class NS_Z(DeviceBase):
    def __init__(self, addr, mixmode=2):
        """!
        此类负责控制24 Z OUT通道的设备，采样率固定为2Gsps，mixmode固定为1
        @param addr: 设备ip
        @param mixmode: 为1时关闭OUT通道混合模式
        """
        super(NS_Z, self).__init__()
        self.mci_driver = MCIDriver(addr)
        self.qsync = QSYNCDriver(addr)
        self.srate = 2e9
        self.mixmode = 1
        self.connect()

    def connect(self):
        mci_params = {'DArate': self.srate, 'MixMode': self.mixmode}
        self.mci_driver.open(system_parameter=mci_params)

        self.mci_driver.set('EnableWaveCache', True)

        for _ch in range(24):
            xy_ch = _ch+1
            setattr(self, f'OUT{xy_ch}', _ZChannel(self, xy_ch))

    def awg_arm(self):
        self.mci_driver.set('PushWaveCache')

    W = {
        "connect": connect,
    }

    Q = {
    }
