# NSQ Driver 最小指令集速查表

本文件提供超导量子比特实验所需的最小函数集，包含初始化、驱动脉冲和测量三类操作。

---

## 一、初始化

### 1. 导入与全局变量

```python
import numpy as np
import time
from nsqdriver import MCIDriver, QSYNCDriver
from nsqdriver.NS_MCI import SHARED_DEVICE_MEM
import nsqdriver.nswave as nw

# 清除共享内存中的旧IP记录（每次启动必须执行）
SHARED_DEVICE_MEM.clear_ip()

# 全局采样率（单位 Hz，后续所有函数依赖这些全局变量）
DArate    = 8e9   # DA总采样率
ADrate    = 4e9   # AD采样率
DArate_xy = 8e9   # XY控制通道DA采样率
DArate_rd = 8e9   # 读出通道DA采样率
cycle = round((ADrate * 1e-9) * (DArate * 1e-9) * 0.125)  # 基本时间单元（单位：cycle数）
```

### 2. 打开驱动连接

```python
deviceIP = "192.168.1.217"   # 根据实际接线图修改
qsync_ip = "192.168.1.217"

device = MCIDriver(deviceIP, 40)   # 第二参数为超时秒数
qsync  = QSYNCDriver(qsync_ip)

sysparam = {
    "MixMode": 2,          # 0~fs/2 写1，fs/2~fs 写2
    "RefClock": "out",
    "DArate_S5-O1": DArate,
    "DArate_S3-O1": DArate,
    "DArate_S7-O1": DArate,
    "ADrate": ADrate,
    "CaptureMode": 0,
    "INMixMode": 2,
}
qsync_param = {
    "TrigFrom": 0,
    "RefClock": "in",
    "TrigWidth": 25e-6,    # 建议为 period 的 1/4
}

qsync.open(system_parameter=qsync_param)
device.open(system_parameter=sysparam)
qsync.sync_system()
```

### 3. 初始化读出槽接口（S9 槽）

```python
slot = 9
for i in range(4):
    port_name = f'S{slot}-O{i+1}'
    device.set('CustomALite', [0x01F0_0000 + 16*4, 0x0], port_name)
```

### 4. 安全关闭所有输出（实验前/后执行）

```python
qsync.set("ResetTrig")
for i in range(4):
    device.set("Output", 0, f"S9-O{i+1}")
```

---

## 二、驱动脉冲：`Multigate_sequence_new2`

支持同一通道上连续多个脉冲，每个脉冲可独立设置波形形状、宽度、幅度、相位和频率。

### 函数签名

```python
def Multigate_sequence_new2(ch, waveform_bank, delay, spacing_time=24e-9):
    """
    ch           : 输出通道号（整数，对应 S5-O{ch}）
    waveform_bank: 长度为7的列表，各元素均为等长列表（脉冲数量相同）
                   [0] shape_list   : 波形形状，'Square' 或 'Gauss'
                   [1] pw_list      : 脉冲宽度（秒）
                   [2] ew_list      : 边沿宽度（秒，通常为0）
                   [3] amp_list     : 归一化幅度（0~1）
                   [4] center_list  : 中心时间（秒，当前版本未使用，占位）
                   [5] phase_list   : 相位（度）
                   [6] freq_list    : 载波频率（Hz）
    delay        : 最后一个脉冲结束时刻距 trigger 的时间（秒）
    spacing_time : 相邻脉冲之间的间隔（秒，默认 24ns，不得小于 24ns）
    """
```

### 调用示例

```python
# 两个脉冲：pi/2 脉冲 + pi 脉冲
waveform_bank = [
    ['Square', 'Square'],   # [0] shape_list
    [20e-9,    40e-9],      # [1] pw_list（脉冲宽度）
    [0,        0],          # [2] ew_list（边沿宽度，通常为0）
    [0.8,      0.8],        # [3] amp_list（幅度）
    [0,        0],          # [4] center_list（占位）
    [0,        0],          # [5] phase_list（相位，度）
    [4.5e9,    4.5e9],      # [6] freq_list（载波频率）
]
Multigate_sequence_new2(ch=1, waveform_bank=waveform_bank, delay=150e-6)

# 单个高斯脉冲
waveform_bank_single = [
    ['Gauss'],
    [40e-9],
    [0],
    [1.0],
    [0],
    [90],      # 相位 90°
    [4.5e9],
]
Multigate_sequence_new2(ch=2, waveform_bank=waveform_bank_single, delay=100e-6)
```

### 注意事项

- 依赖全局变量 `device`、`qsync`、`DArate_xy`、`DArate`、`ADrate`、`cycle`
- 函数内部自动调用 `qsync.set("ResetTrig")` 和 `qsync.set("Shot", 0xFFFFFFFF)`（连续触发模式）
- 若需单次触发，调用后手动执行 `qsync.set("GenerateTrig", period)`

---

## 三、测量：`s21measure1freq`

单频率 IQ 解调测量，返回平均幅度值。

### 依赖的 kernel 函数（需提前定义）

```python
import nsqdriver.nswave as nw

@nw.kernel
def program_rd(delay: nw.Var, in_delay: nw.Var, sample_length: nw.Var):
    """读出采集程序：等待触发 → 延时 → 采集"""
    nw.wait_for_trigger()
    nw.wait(delay + in_delay + 4.096e-6 - sample_length)
    nw.capture(sample_length, 0, 0)
    return nw.Kernel()

@nw.kernel
def program_xy_onepulse(freq: nw.Var, amp: nw.Var, width: nw.Var, delay: nw.Var):
    """读出激励程序：等待触发 → 延时 → 播放余弦波"""
    srate: nw.Var = 8e9
    time_line: np.ndarray = np.linspace(0, width, int(width * srate), endpoint=False)
    wave: np.ndarray = amp * np.cos(2 * np.pi * time_line * freq)
    frame_0: nw.Frame = nw.init_frame(0, 0.5 * np.pi)
    envelope_0: nw.Envelope = nw.ins_envelope(wave)
    nw.wait_for_trigger()
    nw.reset_frame()
    nw.wait(delay)
    nw.play_wave(envelope_0, 1, 0, 0)
    return nw.Kernel()
```

### 函数签名

```python
def s21measure1freq(I_ch, O_ch, freq, wave_amp, delay, in_delay, sample_length,
                    period=200e-6, shots=1024*10):
    """
    I_ch         : 采集通道号（整数，对应 S9-I{I_ch}）
    O_ch         : 输出通道号（整数，对应 S9-O{O_ch}）
    freq         : 读出频率，同时作为解调频率（Hz）
    wave_amp     : 读出脉冲幅度（0~1）
    delay        : 读出脉冲距 trigger 的延时（秒）
    in_delay     : 采集窗口相对于读出脉冲末尾的额外延时（秒）
    sample_length: 采集时长（秒）
    period       : 重复周期（秒，默认 200μs）
    shots        : 平均次数（默认 10240）
    返回值       : float，IQ 幅度均值
    """
```

### 调用示例

```python
# 基本 S21 测量
result = s21measure1freq(
    I_ch=1, O_ch=1,
    freq=5.997e9,
    wave_amp=0.5,
    delay=1.25e-6,
    in_delay=200e-9,
    sample_length=2e-6,
    period=200e-6,
    shots=10240,
)
print(f"IQ 幅度: {result:.6f}")

# 扫频示例
freqs = np.linspace(5.9e9, 6.1e9, 101)
amps  = [s21measure1freq(1, 1, f, 0.5, 1.25e-6, 200e-9, 2e-6) for f in freqs]
```

### 注意事项

- 依赖全局变量 `device`、`qsync`、`cycle`
- 读出槽固定为 `S9`，XY 控制槽固定为 `S9`（读出激励）
- `sample_length` 不得超过 `2.048e-6`（硬件限制）
- 函数内部自动设置所有 4 个 I 通道的 `FreqList`（广播解调频率）

---

## 四、典型实验流程

```python
# 1. 初始化（每次重启后执行一次）
SHARED_DEVICE_MEM.clear_ip()
device = MCIDriver("192.168.1.217", 40)
qsync  = QSYNCDriver("192.168.1.217")
qsync.open(system_parameter=qsync_param)
device.open(system_parameter=sysparam)
qsync.sync_system()

# 2. 定义驱动脉冲（XY 控制，S5 槽）
Multigate_sequence_new2(ch=1, waveform_bank=waveform_bank, delay=150e-6)

# 3. 测量（读出，S9 槽）
result = s21measure1freq(I_ch=1, O_ch=1, freq=5.997e9, wave_amp=0.5,
                         delay=150e-6, in_delay=200e-9, sample_length=2e-6)

# 4. 实验结束后关闭输出
qsync.set("ResetTrig")
for i in range(4):
    device.set("Output", 0, f"S9-O{i+1}")
```
