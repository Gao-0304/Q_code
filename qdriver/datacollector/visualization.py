"""
数据管理层 - 数据可视化

用于绘制测量结果的图表
"""
import numpy as np
import matplotlib.pyplot as plt


def plot_cavity_resonance(cavity_result, cavity_params=None, figsize=(10, 8)):
    """
    绘制腔频共振曲线

    参数：
    - cavity_result: 来自 measure_cavity_frequency 的返回字典
    - cavity_params: 来自 ExperimentContext.get_cavity_params() 的腔参数（可选）
    - figsize: 图表大小

    返回：
    - fig: matplotlib Figure 对象
    """
    freq_array = cavity_result['freq'] / 1e9  # 转换为 GHz
    mag_array = cavity_result['mag']
    phase_array = cavity_result['phase']

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize)

    # 幅值曲线
    ax1.scatter(freq_array, 20*np.log10(mag_array), label='S21 Magnitude', s=30)
    ax1.set_xlabel('Frequency (GHz)', fontsize=11)
    ax1.set_ylabel('Magnitude (dB)', fontsize=11)
    ax1.set_title('Cavity Resonance - Magnitude', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)

    # 添加腔频标线
    if cavity_params is not None and cavity_params['freq'] is not None:
        cavity_freq_ghz = cavity_params['freq'] / 1e9
        ax1.axvline(cavity_freq_ghz, color='r', linestyle='--', linewidth=2,
                   label=f"Cavity Freq = {cavity_freq_ghz:.6f} GHz")
        ax1.legend(fontsize=10)

    # 相位曲线
    ax2.scatter(freq_array, np.rad2deg(phase_array), label='S21 Phase', s=30)
    if cavity_params is not None and cavity_params['freq'] is not None:
        cavity_freq_ghz = cavity_params['freq'] / 1e9
        ax2.axvline(cavity_freq_ghz, color='r', linestyle='--', linewidth=2)
    ax2.set_xlabel('Frequency (GHz)', fontsize=11)
    ax2.set_ylabel('Phase (deg)', fontsize=11)
    ax2.set_title('Cavity Resonance - Phase', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.legend(fontsize=10)

    plt.tight_layout()
    return fig


def plot_raw_iq(iq_data, title="Raw IQ Data", figsize=(8, 6)):
    """
    绘制原始IQ数据

    参数：
    - iq_data: 原始IQ数据数组 (shots, frequencies)
    - title: 图表标题
    - figsize: 图表大小

    返回：
    - fig: matplotlib Figure 对象
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)

    # IQ平面散点图
    i_values = iq_data[:, 0].real
    q_values = iq_data[:, 0].imag

    ax1.scatter(i_values, q_values, alpha=0.5, s=20)
    ax1.set_xlabel('I', fontsize=11)
    ax1.set_ylabel('Q', fontsize=11)
    ax1.set_title(f'{title} - IQ Plane', fontsize=12, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.axis('equal')

    # 幅值分布直方图
    mag_values = np.abs(iq_data[:, 0])
    ax2.hist(mag_values, bins=50, alpha=0.7, edgecolor='black')
    ax2.set_xlabel('Magnitude', fontsize=11)
    ax2.set_ylabel('Count', fontsize=11)
    ax2.set_title(f'{title} - Magnitude Distribution', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    return fig
