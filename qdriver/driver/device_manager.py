"""
设备管理层 - 硬件初始化和全局管理
"""
import numpy as np
from nsqdriver import MCIDriver, QSYNCDriver
from nsqdriver.NS_MCI import SHARED_DEVICE_MEM


def initialize_system(device_ip="192.168.1.217", qsync_ip="192.168.1.217",
                     debug=False):
    """
    初始化硬件系统（QSYNC+MCI）

    参数：
    - device_ip: MCI设备IP地址
    - qsync_ip: QSYNC同步设备IP地址
    - debug: 是否使用调试模式

    返回：
    - (device, qsync)：MCI驱动和QSYNC驱动对象
    """
    # 清空共享内存
    SHARED_DEVICE_MEM.clear_ip()

    # 创建驱动对象
    qsync = QSYNCDriver(qsync_ip)
    device = MCIDriver(device_ip, 40)

    # 定义系统参数
    darate = 8e9
    adrate = 4e9

    sysparam = {
        "MixMode": 2,              # 0~fs/2写1， fs/2~fs写2
        "RefClock": "out",
        "DArate_S5-O1": darate,
        "DArate_S3-O1": darate,
        "DArate_S7-O1": darate,
        "ADrate": adrate,
        "CaptureMode": 0,
        "INMixMode": 2,
    }

    qsync_param = {
        "TrigFrom": 0,
        "RefClock": "in",
        "TrigWidth": 25e-6  # 设置TrigWidth等于period的1/4
    }

    # 打开设备
    qsync.open(system_parameter=qsync_param)
    device.open(system_parameter=sysparam)
    qsync.sync_system()

    # 设置接地（S9通道）
    slot = 9
    for i in range(4):
        port_name = f'S{slot}-O{int(i+1)}'
        device.set('CustomALite', [0x01F0_0000+16*4, 0x0], port_name)

    if debug:
        print("系统初始化成功")
        print(f"  MCI设备: {device_ip}")
        print(f"  QSYNC设备: {qsync_ip}")
        print(f"  DA采样率: {darate/1e9} GHz")
        print(f"  AD采样率: {adrate/1e9} GHz")

    return device, qsync, darate, adrate


def reset_device(device, qsync):
    """
    复位设备到安全状态
    """
    try:
        qsync.set("ResetTrig")
    except Exception as e:
        pass

    try:
        for i in range(4):
            device.set("Output", 0, f"S9-O{i+1}")
    except Exception as e:
        pass
