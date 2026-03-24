import socket
import struct
import time
from functools import lru_cache, wraps
from typing import Union, TYPE_CHECKING, Tuple, Iterable

try:
    from .common import BaseDriver, Quantity
except ImportError as e:
    class BaseDriver:
        def __init__(self, addr, timeout, **kw):
            self.addr = addr
            self.timeout = timeout


    class Quantity(object):
        def __init__(self, name: str, value=None, ch: int = 1, unit: str = ''):
            self.name = name
            self.default = dict(value=value, ch=ch, unit=unit)


DEBUG_PRINT = False


def print_debug(*args, **kwargs):
    if DEBUG_PRINT:
        print(*args, **kwargs)


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
    icd_head_mode = 0x51000009
    icd_head_open = 0x5100000A
    CHs = list(range(1, 17))

    quants = [
        Quantity('SAMode', value='manual'),  # set/get, 运行模式manual为手动，根据指令切换开关
        Quantity('Strobe', value=1, ch=1),  # set/get, 选通开关通道，value为开关矩阵in口，ch为out口
    ]

    SystemParameter = {
        'SAMode': 'manual',  # 运行模式manual为手动，根据指令切换开关
        'StrobeList': [1, 9],
    }

    def __init__(self, addr: str = '', timeout: float = 10.0, **kw):
        super().__init__(addr, timeout, **kw)
        self.handle = None
        self.model = 'NS_CST'  # 默认为设备名字
        self.srate = None
        self.gen_trig_num = 0
        self.addr = addr

        self.param = {'SAMode': 'manual'}
        print_debug(f'CST: 实例化成功{addr}')

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
        print_debug(f'CST: set操作被调用{name}')
        if name == 'SAMode':
            data = self.__fmt_cst_mode(
                value
            )
            self._send_command(data, connect_timeout=2)
        elif name == 'Strobe':
            config = self.param['StrobeList']
            if value not in [1, 2]:
                raise ValueError(f'IN通道超界，不应为{value}，需要为1或2')
            config[value-1] = channel
            data = self.__fmt_cst_strobe(
                config
            )
            self._send_command(data, connect_timeout=2)
        elif name == 'UpdateFirmware':
            self.update_firmware(value)

        else:
            self.param[name] = value

    def get(self, name, channel=1, value=0):
        """!
        查询设备属性，获取数据
        @param name:
        @param channel:
        @param value:
        @return:
        """
        print_debug(f'CST: get操作被调用{name}')
        return self.param.get(name, None)

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
        sock.settimeout(timeout)
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
                    print(f'返回指令ID错误')
                    return False
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
    def __fmt_cst_mode(self, mode):
        cmd_pack = (
            0x5F5F5F5F,
            self.icd_head_mode,
            0x00000000,
            20,
            0 if mode == 'manual' else 1
        )

        return struct.pack('=' + 'I' * len(cmd_pack), *cmd_pack)

    @lru_cache(maxsize=32)
    def __fmt_cst_strobe(self, out_ch):
        if out_ch[0] > 8:
            raise ValueError(f'不能将IN1通道选通到OUT9~16')
        if out_ch[1] <= 8:
            raise ValueError(f'不能将IN2通道选通到OUT1~8')
        cmd_pack = (
            0x5F5F5F5F,
            self.icd_head_open,
            0x00000000,
            20,
            (1 << (out_ch[0] - 1)) + (1 << (out_ch[1]-1))
        )

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


if __name__ == '__main__':
    driver = Driver('192.168.1.241')
    driver.open()
    driver.set('Strobe', 1, 3)   # I1选通到OUT3，所有通道编号从1计数
    driver.set('Strobe', 2, 9)   # I2选通到OUT9，OUT9为第二个模块的OUT1
