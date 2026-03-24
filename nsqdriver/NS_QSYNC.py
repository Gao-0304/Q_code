import atexit
import socket
import struct
import threading
import time
import pickle
import enum
import copy
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from multiprocessing import shared_memory
from functools import lru_cache, wraps
from typing import Union, TYPE_CHECKING, Tuple, Iterable

try:
    from .common import BaseDriver, Quantity, QInteger
except ImportError as e:
    class BaseDriver:
        def __init__(self, addr, timeout, **kw):
            self.addr = addr
            self.timeout = timeout


    class Quantity(object):
        def __init__(self, name: str, value=None, ch: int = 1, unit: str = ''):
            self.name = name
            self.default = dict(value=value, ch=ch, unit=unit)


    class QInteger:
        def __init__(self, name, value=None, unit='', ch=None,
                     get_cmd='', set_cmd='', ):
            self.name = name

if TYPE_CHECKING:
    from backend.board_parser import MCIBoard
    from concurrent.futures import Future

THREAD_POOL = ThreadPoolExecutor(max_workers=10)
_scanning_lock = threading.Lock()
_scanning_stop_event = threading.Event()
DEVICE_SET = set()

DEBUG_PRINT = False


def print_debug(*args, **kwargs):
    if DEBUG_PRINT:
        print(*args, **kwargs)


@atexit.register
def global_system_exit():
    THREAD_POOL.shutdown(wait=False)
    SHARED_DEVICE_MEM.close()
    try:
        SHARED_DEVICE_MEM.unlink()
    except FileNotFoundError as e:
        pass


def retry(times):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            _times = times - 1
            while not func(*args, **kwargs) and _times > 0:
                _times -= 1
            return _times != 0

        return wrapper

    return decorator


class Driver(BaseDriver):
    class ScannMode(enum.IntEnum):
        """!
        @detail QC/QR等被同步设备的发现方式，'local': 本地共享内存扫描， 'remote': 网络udp扫描
        """
        local = 0
        """local: 本地共享内存扫描

        - NS_MCI中的Driver每实例化一次，就会在SharedMemory中记录一次自己的ip
        - 系统进行同步时，会对SharedMemory中记录的QC/QR设备ip进行同步
        - 只有程序整体退出的时候才会清空这片缓存
        """
        remote = 1
        """remote: 网络udp扫描

        - import 本文件后，会建立一个独立线程间断广播UDP包，扫描局域网内的QC/QR设备，记录被扫描到的设备ip
        - 系统进行同步时，会对扫描到的QC/QR设备ip进行同步
        - 注意：这种方式比较粗暴，会影响局域网内正在运行的设备
        """
        alone = 2
        """alone: 单机运行模式

        - QC/QR设备单独运行时使用本模式，默认使用QC/QR设备板内的QSYNC做设备内的系统同步
        - 系统进行同步时，会判断QSYNC Driver的ip是否为QC/QR设备的ip
        """

    _scanning_lock = _scanning_lock
    _device_set = DEVICE_SET
    segment = ('ns', '111|112|113|114|115')

    icd_head_reset = 0x41000002
    icd_head_status = 0x4100000E
    icd_head_cmd_2 = 0x31000015
    icd_head_cmd_3 = 0x410000B1
    icd_head_cmd_4 = 0x31000013
    icd_head_cmd_5 = 0x410000B2
    icd_head_cmd_6 = 0x3100001A
    icd_head_cmd_7 = 0x410000B3
    CHs = list(range(1, 17))

    quants = [
        QInteger('TRIG'),
        Quantity('SystemSync', value=None, ch=1),  # set/get,运行次数
        Quantity('GenerateTrig', value=None, unit='s'),  # set/get,触发周期单位s，触发数量=shot
        Quantity('ResetTrig', value=None),
        Quantity('Shot', value=1024, ch=1),  # set/get, 运行次数
        Quantity('TrigPeriod', value=200e-6, ch=1),  # set/get, 触发周期
        Quantity('TrigWidth', value=800e-9, ch=1),  # set/get, 触发周期
        Quantity('TrigDelay', value=0, ch=1),  # set/get, 触发周期
        Quantity('TrigDelayList', value=0, ch=1),  # set/get, 触发周期
        Quantity('TrigFrom', value=0, ch=1),  # Trig来源： 0：内部产生；1：外部输入
        Quantity('RefClock', value='out', ch=1),  # 参考时钟选择： ‘out’：外参考时钟；‘in’：内参考时钟
        Quantity('DiscoveryMode', value=ScannMode.local, ch=1),  # QC/QR等被同步设备的发现方式，见DiscoveryMode说明
        Quantity('UpdateFirmware', value='', ch=1),  # qsync固件更新
        Quantity('GeneratePrtTrig', value=None, unit='s'),  # 生成subprt trig
        Quantity('SubDelayCount', value=0, ch=1),
        Quantity('TrigWidth', value=0, ch=1),
    ]

    SystemParameter = {
        'RefClock': 'out',  # 参考时钟选择： ‘out’：外参考时钟；‘in’：内参考时钟
        'TrigFrom': 0,  # Trig来源： 0：内部产生；1：外部输入
        'TrigPeriod': 200e-6,  # 触发信号重复周期
        'TrigWidth': 800e-9,  # 触发信号高电平宽度 单位s
        'TrigDelay': 0,  # 触发信号相对开启通知的延迟
        'Shot': 1024,
        'DiscoveryMode': ScannMode.local,  # QC/QR等被同步设备的发现方式，见DiscoveryMode说明
    }

    def __init__(self, addr: str = '', timeout: float = 10.0, **kw):
        super().__init__(addr, timeout, **kw)
        self.handle = None
        self.model = 'NS_QSYNC'  # 默认为设备名字
        self.srate = None
        self.gen_trig_num = 0
        self.addr = addr

        self.param = {'Shot': 1024, 'TrigPeriod': 200e-6, 'MixMode': 2}
        self.subprtparam = [
            [[0x5F5F5F5F,
              0x41000001,
              0x00000000,
              4 * (17 * 100 + 17 * 4 + 5),  # 指令长度 ，uint32个数*4
              0, ]],
            [[0, 0, 800, 0] for _ in range(17)],
            [[0 for _ in range(100)] for _ in range(17)],
        ]
        print_debug(f'QSYNC: 实例化成功{addr}')

    @property
    def device_set(self):
        mode = self.param.get('DiscoveryMode', self.ScannMode.local)
        if mode is self.ScannMode.local:
            return set(SHARED_DEVICE_MEM.ip)
        elif mode is self.ScannMode.alone:
            if self.addr in SHARED_DEVICE_MEM.ip:
                return {self.addr}
            else:
                raise RuntimeError('qsync处于alone模式下，只能控制QC/QR内的qsync，请确认对应QC/QR设备是否已经open成功')
        elif mode is self.ScannMode.remote:
            return self._device_set.copy()
        else:
            return set()

    def open(self, **kw):
        """!
        输入IP打开设备，配置默认超时时间为5秒
        打开设备时配置RFSoC采样时钟，采样时钟以参数定义
        @param kw:
        @return:
        """
        # 配置系统初始值
        system_parameter = kw.get('system_parameter', {})
        values = self.SystemParameter.copy()
        values.update(system_parameter)
        for name, value in values.items():
            if value is not None:
                self.set(name, value, 1)

        # self.sync_system()
        status = self.get('Status')
        print(f'*********QSYNC{self.addr}开启成功*********\n'
              f'core_temp: {status[0]}℃\n'
              f'10M_locked: {status[1] if len(status) > 1 else "nan"}')
        print(f'qsync {self.addr} opened successfully')

    def close(self, **kw):
        """
        关闭设备
        """
        # self.handle.release_dma()
        # self.handle.close()
        ...

    def write(self, name: str, value, **kw):
        channel = kw.get('ch', 1)
        return self.set(name, value, channel)

    def read(self, name: str, **kw):
        channel = kw.get('ch', 1)
        result = self.get(name, channel)
        return result

    def set(self, name, value=None, channel=1):
        """!
        设置设备属性
        @param name:
        @param value:
        @param channel:
        @return:
        """
        print_debug(f'QSYNC: set操作被调用{name}')
        self.subprt(name, value, channel)
        if name in {'SystemSync', 'ReInit'}:
            self.sync_system()
        elif name == 'TRIG':
            value = self.param['TrigPeriod']
            data = self.__fmt_qsync_start(
                self.param['TrigFrom'], value, self.param['Shot'],
                self.param['TrigWidth'], self.param['TrigDelay']
            )
            self._send_command(data, connect_timeout=2)
            self.gen_trig_num += 1
        elif name == 'GenerateTrig':
            value = self.param['TrigPeriod'] if value is None else value
            data = self.__fmt_qsync_start(
                self.param['TrigFrom'], value, self.param['Shot'],
                self.param['TrigWidth'], self.param['TrigDelay']
            )
            self._send_command(data, connect_timeout=2)
            self.gen_trig_num += 1
        elif name == 'ResetTrig':
            self.subprtparam = [
                [[0x5F5F5F5F,
                  0x41000001,
                  0x00000000,
                  4 * (17 * 100 + 17 * 4 + 5),  # 指令长度 ，uint32个数*4
                  0, ]],
                [[0, 0, 800, 0] for _ in range(17)],
                [[0 for _ in range(100)] for _ in range(17)],
            ]
            data = self.__fmt_qsync_common(self.icd_head_reset)
            self._send_command(data)
        elif name == 'RefClock':
            self.change_ref(value)
        elif name == 'UpdateFirmware':
            self.update_firmware(value)
        elif name == 'SetMask':
            if not isinstance(value, list):
                print(f'SetMask set value {value} is not a list')
                return
            data = self.__fmt_qsync_mask(*value)
            self._send_command(data)

        elif name == "GeneratePrtTrig":
            data = self.__fmt_qsync_prt(self.subprtparam)
            self._send_command(data)
        else:
            self.param[name] = value

    def subprt(self, name, value, ch=1):
        """
        subprt参数过滤
        Args:
            name: _description_
            value: _description_
            ch: _description_
        """
        if name == "Shot":
            self.subprtparam[1][ch - 1][1] = round(value) & 0xFFFFFFFF
        elif name == "TrigPeriod":
            self.subprtparam[1][ch - 1][0] = round(value * 1e9) & 0xFFFFFFFF
        elif name == "TrigWidth":
            self.subprtparam[1][ch - 1][2] = round(value * 1e9) & 0xFFFFFFFF
        # elif name == "TrigDelay":
        #     self.subprtparam[1][ch-1][3] = round(value * 1e9) & 0xFFFFFFFF
        elif name == "SubDelayCount":
            self.subprtparam[1][ch - 1][3] = round(value) & 0xFFFFFFFF
        elif name == "TrigDelayList":
            self.subprtparam[2][ch - 1] = [round(i * 1e9) & 0xFFFFFFFF for i in value]
            self.subprtparam[2][ch - 1].extend([0] * (100 - len(self.subprtparam[2][ch - 1])))  # 长度为100

    def get(self, name, channel=1, value=0):
        """!
        查询设备属性，获取数据
        @param name:
        @param channel:
        @param value:
        @return:
        """
        print_debug(f'QSYNC: get操作被调用{name}')
        if name == 'Status':
            cmd_data = self.__fmt_qsync_common(self.icd_head_status)
            data = DeviceCmdHandle.send_command(cmd_data, addr=self.addr, return_fdk=True)
            data = struct.unpack('I' * (len(data) // 4), data)
            return data
        return self.param.get(name, None)

    def sync_system(self):
        """
        全系统同步流程

        :return:
        """
        if Driver._scanning_lock.acquire(timeout=10):
            Driver._scanning_lock.release()
        if len(self.device_set) == 0:
            return

        data = self.__fmt_qsync_common(self.icd_head_reset)
        self._send_command(data)

        result = True
        if self.param.get('DiscoveryMode', self.ScannMode.local) != self.ScannMode.alone:
            data = self.__fmt_qsync_common(self.icd_head_reset)
            result &= self._sendto_fake_qsync(data)
            data = self.__fmt_qsync_ref_from('out')
            result &= self._sendto_fake_qsync(data)
        result &= self._sendto_device(self.icd_head_cmd_2)
        result &= self._sendto_qsync(self.icd_head_cmd_3)
        result &= self._sendto_device(self.icd_head_cmd_4)
        result &= self._sendto_qsync(self.icd_head_cmd_5)
        result &= self._sendto_device(self.icd_head_cmd_6, 30)
        result &= self._sendto_qsync(self.icd_head_cmd_7)

        print(f'System synchronization {"succeeded" if result else "FAILED"}')

    def change_ref(self, value='out'):
        self.param['RefClock'] = value
        self.set('ResetTrig')
        data = self.__fmt_qsync_ref_from(value)
        self._send_command(data)

    def _sendto_device(self, cmd_head, timeout=2):
        """!
        将指令发送给设备
        @param cmd_head:
        @param timeout:
        @return:
        """
        cmd_data = self.__fmt_qsync_common(cmd_head)
        devices = list(self.device_set)
        futures = [
            THREAD_POOL.submit(DeviceCmdHandle.send_command, cmd_data, 0, addr, 5000, True, False, timeout)
            for addr in devices
        ]
        wait_futures(futures)
        result = all(future.result() for future in futures)
        for idx, future in enumerate(futures):
            if not future.result():
                print(f'device: {devices[idx]}系统同步过程 {hex(cmd_head)} 执行失败')
        return result

    def _sendto_fake_qsync(self, cmd_data, timeout=2):
        devices = list(self.device_set)
        futures = [
            THREAD_POOL.submit(self._send_command, cmd_data, 0, addr, 5001, True, False, timeout)
            for addr in devices if addr != self.addr
        ]
        wait_futures(futures)
        result = all(future.result() for future in futures)
        for idx, future in enumerate(futures):
            if not future.result():
                print(f'device: {devices[idx]}系统同步过程 {cmd_data[4:12]} 执行失败')
        return result

    def _sendto_qsync(self, cmd_head: int):
        """!
        将指令发送给qsync

        @param cmd_head:
        @return:
        """
        cmd_data = self.__fmt_qsync_common(cmd_head)
        if not self._send_command(cmd_data, connect_timeout=2):
            print(f'qsync: 系统同步过程 {hex(cmd_head)} 执行失败')
            return False
        return True

    def update_firmware(self, file_path, boards=None):
        """!
        固件更新

        @param file_path: 固件路径
        @param boards:
        @return:
        """
        import os
        if not os.path.exists(file_path):
            raise ValueError(f'文件路径: {file_path} 不存在')
        with open(file_path, 'rb') as fp:
            cmd_data = self.__fmt_update_firmware(fp.read())
        if not self._send_command(cmd_data):
            print(f'qsync: 固件更新 执行失败')

    def _connect(self, addr=None, port=5001, timeout=None):
        """!
        获取到指定ip的tcp连接

        @param addr:
        @param port:
        @return:
        """
        timeout = self.timeout if timeout is None else timeout
        addr = self.addr if addr is None else addr
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout+1)
        sock.connect((addr, port))
        return sock

    @retry(3)
    def _send_command(self, data: Union[str, bytes], wait=0, addr=None, port=5001,
                      check_feedback=True, return_fdk=False, connect_timeout=10):
        """!
        发送指定内容到后端

        @param data: 指令内容
        @param wait: 指令发送完成后，等待一段时间再接收反馈，阻塞式等待
        @param addr: 后端IP
        @param port: 后端端口
        @param check_feedback: 是否解析反馈
        @param connect_timeout:
        @return:
        """
        command_bak = data
        try:
            sock = self._connect(addr=addr, port=port, timeout=connect_timeout)
        except Exception as e:
            print(f'device: {addr}无法连接 {e}')
            return False

        try:
            sock.sendall(memoryview(data))

            time.sleep(wait)
            _feedback = sock.recv(20)
            if check_feedback:
                if not _feedback.startswith(b'\xcf\xcf\xcf\xcf'):
                    print('返回指令包头错误')
                    return False
                if command_bak[4:8] != _feedback[4:8]:
                    print('返回指令ID错误')
                    return False
                # print(_feedback)
                _feedback = struct.unpack('=IIIII', _feedback)
                if _feedback[4] != 0:
                    print('指令成功下发，但执行失败')
                    return False
        except Exception as e:
            print(f'device: {addr}指令{command_bak[:4]}发送失败 {e}')
            return False
        finally:
            sock.close()
        return True

    @lru_cache(maxsize=32)
    def __fmt_qsync_common(self, head):
        cmd_pack = (
            0x5F5F5F5F,
            head,
            0x00000000,
            16,
        )

        return struct.pack('=' + 'I' * len(cmd_pack), *cmd_pack)

    @lru_cache(maxsize=16)
    def __fmt_qsync_ref_from(self, _from):
        if _from == 'in':
            _from = 0
        elif _from == 'out':
            _from = 1
        else:
            _from = 0
        cmd_pack = (
            0x5F5F5F5F,
            0x4100000F,
            0x00000000,
            20,
            _from
        )

        return struct.pack('=' + 'I' * len(cmd_pack), *cmd_pack)

    @lru_cache(maxsize=32)
    def __fmt_qsync_mask(self, *mask):
        cmd_pack = (
            0x5F5F5F5F,
            0x51000001,
            0x00000000,
            80,
            *mask
        )

        return struct.pack('=' + 'I' * len(cmd_pack), *cmd_pack)

    @lru_cache(maxsize=32)
    def __fmt_qsync_start(self, src, period, shots, width, delay):
        cmd_pack = (
            0x5F5F5F5F,
            0x41000001,
            0x00000000,
            36,
            int(src),
            int(period * 1e9) & 0xFFFFFFFF,
            int(shots),
            int(width * 1e9) & 0xFFFFFFFF,
            int(delay * 1e9) & 0xFFFFFFFF
        )

        return struct.pack('=' + 'I' * len(cmd_pack), *cmd_pack)

    # @lru_cache(maxsize=8)
    def __fmt_qsync_prt(self, para):
        cmd_pack = []
        for i in para:
            for ii in i:
                for iii in ii:
                    cmd_pack.append(iii)
        return struct.pack('=' + 'I' * len(cmd_pack), *cmd_pack)

    @staticmethod
    def __fmt_update_firmware(file_data):
        cmd_pack = (
            0x5F5F5F5F,
            0x31000006,
            0x00000000,
            16 + len(file_data),
        )
        return struct.pack('=' + 'I' * len(cmd_pack), *cmd_pack) + file_data

    # DG645兼容
    def Trigger_singleshot(self):
        self.set('GenerateTrig')

    def Convention_init(self, rate=5000, **kwds):
        self.set('ResetTrig')
        self.set('Shot', 0xFFFFFFFF)
        self.set('TrigPeriod', 1 / rate)
        self.set('GenerateTrig')

    def BurstMode_init(self, count=2048, delay=200e-6, period=200e-6, source=0, **kwds):
        self.set('ResetTrig')
        self.set('Shot', count)
        self.set('TrigPeriod', period)
        self.set('TrigDelay', delay)
        self.set('TrigFrom', source)

    def startGun(self):
        self.Trigger_singleshot()


def do_scanning():
    """
    扫描板卡

    :return:
    """
    while True:
        dest = ('<broadcast>', 5003)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        addrs = socket.getaddrinfo(socket.gethostname(), None)
        addr = [addr[4][0] for addr in addrs if addr[4][0].startswith('192.168.1.')]
        _bind = False
        _port = 15000
        with _scanning_lock:
            while not _bind:
                try:
                    s.bind((addr[0], _port))
                    _bind = True
                except Exception as e:
                    _port += 1
                    if _port >= 30000:
                        raise e
            s.sendto(b"____\x20\x00\x002\x00\x00\x00\x00\x14\x00\x00\x00\x00\x00\x00\x00", dest)
            s.settimeout(3)

            try:
                while True:
                    (feedback, _addr) = s.recvfrom(20)
                    if feedback:
                        DEVICE_SET.add(_addr[0])
            except Exception as e:
                s.close()
        time.sleep(5)


class DeviceCmdHandle:
    """!
    @brief 封装与QC/QR设备间的交互
    """
    error_map = {b'\x1a\x00\x001': {1: '指令Resync执行失败',
                                    2: 'REFCLK not Detected',
                                    3: 'Clock Maybe unstable, DAC Settings Error',
                                    4: 'Clock Maybe unstable, ADC Settings Error, '
                                       'Please check if the amplifier is too large',
                                    5: 'SYSREF(External TRIG) not Detected, MTS failed / Sample Rate not Support',
                                    7: 'ADC Calibration Failed'}
                 }

    @staticmethod
    def packing_result(boards: Iterable["MCIBoard"],
                       futures: Iterable["Future"],
                       cmd_data: memoryview,
                       head: bytes) -> Tuple[bytes, list]:
        res = []
        errors = []
        for board, future in zip(boards, futures):
            if board.has_cmd_link and board.has_stream_link:
                _id = (board.sig_fpga_pci_port & 0xFF) << 24
                _res = struct.unpack('IIIII', future.result())[-1] & 0xFFFFFF
                if _res:
                    errors.append(f'指令{cmd_data[4:8].tobytes()}向{board.cs_target}转发失败\n')
                res.append(_id + _res)
        return b''.join((head, cmd_data[4:12], struct.pack('=I' + 'I' * len(res), 16 + len(res) * 4, *res))), errors

    @staticmethod
    def packing_fake_result(boards: Iterable["MCIBoard"], cmd_data: memoryview, head: bytes) -> bytes:
        res = []
        for board in boards:
            if board.has_cmd_link and board.has_stream_link:
                _id = (board.ds_id & 0xFF) << 24
                res.append(_id + 0)
        return b''.join((head, cmd_data[4:12], struct.pack('=I' + 'I' * len(res), 16 + len(res) * 4, *res)))

    @classmethod
    def unpacking_result(cls, _feedback, _res, command_bak, addr):
        cmd_id = command_bak[4:8]
        if not _feedback.startswith(b'\xcf\xcf\xcf\xcf'):
            print(f'设备{addr}-指令{cmd_id}-返回指令包头错误')
            return False
        if cmd_id != _feedback[4:8]:
            print(f'设备{addr}-指令{cmd_id}-返回指令ID错误{_feedback[4:8]}')
            return False
        if len(_res) % 4 != 0:
            print(f'设备{addr}-指令{cmd_id}-返回结果{_res}长度错误')
            return False
        command_status = True
        results = struct.unpack('I' * (len(_res) // 4), _res)
        for result in results:
            board_id = (result & 0xFF000000) >> 24
            board_res = result & 0xFFFFFF
            error_map = cls.error_map.get(command_bak[4:8], {})
            if board_res:
                print(f'设备{addr}-板卡{board_id}-指令{cmd_id}-{error_map.get(board_res, "执行失败")}')
                command_status &= False
        return command_status

    @classmethod
    def send_command(cls, data: Union[str, bytes], wait=0, addr=None, port=5001,
                     check_feedback=True, return_fdk=False, connect_timeout=None):
        """!
        发送指定内容到后端

        @param data: 指令内容
        @param wait: 指令发送完成后，等待一段时间再接收反馈，阻塞式等待
        @param addr: 后端IP
        @param port: 后端端口
        @param check_feedback:
        @param return_fdk:
        @param connect_timeout:
        @return:
        """
        command_bak = data
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(connect_timeout)
            sock.connect((addr, port))
        except Exception as e:
            print(e)
            return False

        try:
            sock.sendall(memoryview(data))

            time.sleep(wait)
            _feedback = sock.recv(16)
            if check_feedback:
                _res = sock.recv(struct.unpack('I', _feedback[12:16])[0] - 16)
                if return_fdk:
                    return _res
                else:
                    return cls.unpacking_result(_feedback, _res, command_bak, addr)
        except Exception as e:
            print(e)
            return False
        finally:
            sock.close()
        return True


class InfoSharedList:
    memory_name = 'NS_DEVICE_MEMORY'
    memory_size = 1024 ** 2
    head_size = 32  # memory中前head_size的长度为头部预留信息

    def __init__(self):
        try:
            self._memory = shared_memory.SharedMemory(name=self.memory_name, create=True, size=self.memory_size)
        except FileExistsError:
            self._memory = shared_memory.SharedMemory(name=self.memory_name, create=False, size=self.memory_size)

    def clear_ip(self):
        _exit_pkl = pickle.dumps(self.ip)
        self._memory.buf[self.head_size:len(_exit_pkl) + self.head_size] = b'\x00' * len(_exit_pkl)

    @property
    def ip(self):
        try:
            return pickle.loads(self._memory.buf[self.head_size:])
        except pickle.UnpicklingError:
            return []

    @ip.setter
    def ip(self, value):
        ips = self.ip
        ips.append(value)
        ips = list(set(ips))
        _pkl = pickle.dumps(ips)
        self._memory.buf[self.head_size:len(_pkl) + self.head_size] = _pkl

    def close(self):
        self._memory.close()

    def unlink(self):
        try:
            self._memory.unlink()
        except FileNotFoundError as e:
            pass


# threading.Thread(target=do_scanning, daemon=True, name='qsync_scanning_device').start()
SHARED_DEVICE_MEM = InfoSharedList()

if __name__ == '__main__':
    ins = Driver('127.0.0.1')

    count = 1024
    period = 400e-6
    delay = 0
    source = 0

    # ins.set('ResetTrig')

    for ch in [1, 2, 3, 4, 5, 6, 7]:
        ins.set('Shot', count, channel=ch)
        ins.set('TrigPeriod', period, channel=ch)
        ins.set('TrigDelay', delay, channel=ch)
        ins.set('TrigFrom', source, channel=ch)

    for ch in [8]:
        ins.set('Shot', count, channel=ch)
        ins.set('TrigWidth', 1600e-9, channel=ch)
        ins.set('TrigPeriod', period, channel=ch)
        ins.set('SubTriggerCount', 4, channel=ch)
        ins.set('TrigDelayList', [1600e-9 * i for i in range(4)])
        ins.set('TrigFrom', source, channel=ch)

    for i in range(1):
        # ins.set('GenerateTrig')
        ins.set('GeneratePrtTrig')
        import time

        time.sleep(1)
