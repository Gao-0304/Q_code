"""
数据管理层 - QCoDeS接口

与QCoDeS框架集成，处理数据存储和检索
"""
import numpy as np
from qcodes.dataset import Measurement


def save_cavity_scan(cavity_result, exp, meas, station=None):
    """
    将腔频扫描结果保存到QCoDeS数据库

    参数：
    - cavity_result: 来自measure_cavity_frequency的返回字典
    - exp: QCoDeS Experiment对象
    - meas: QCoDeS Measurement对象
    - station: QCoDeS Station对象 (可选)

    返回：
    - dataset: QCoDeS Dataset对象
    """
    freq_array = cavity_result['freq']
    mag_array = cavity_result['mag']
    phase_array = cavity_result['phase']

    # 如果station为空，从exp中获取
    if station is None:
        station = meas.station

    # 如果Measurement未初始化，手动注册参数
    try:
        if len(meas.parameters) == 0:
            raise ValueError("Measurement not initialized")
    except:
        # 需要从station的仪器中获取参数
        # 这里假设有DL1等数据记录器（见251208.ipynb）
        if hasattr(station, 'DL1'):
            meas.register_parameter(station.DL1.frequency)
            meas.register_parameter(station.DL1.magnitude, setpoints=(station.DL1.frequency,))
            meas.register_parameter(station.DL1.phase, setpoints=(station.DL1.frequency,))
        else:
            # 降级处理：创建虚拟参数
            print("警告：Station中未找到DL1，使用简化存储模式")

    # 存储数据
    with meas.run() as datasaver:
        for freq, mag, phase in zip(freq_array, mag_array, phase_array):
            if hasattr(station, 'DL1'):
                datasaver.add_result(
                    (station.DL1.frequency, freq),
                    (station.DL1.magnitude, mag),
                    (station.DL1.phase, phase)
                )
            else:
                # 降级处理
                pass

    return meas.dataset


def setup_qcodes_experiment(exp_name, sample_name, db_path, station=None):
    """
    初始化QCoDeS实验环境

    参数：
    - exp_name: 实验名称
    - sample_name: 样品名称
    - db_path: 数据库文件路径
    - station: 可选的Station对象

    返回：
    - (exp, meas, station): Experiment, Measurement和Station对象
    """
    from qcodes.dataset import (
        initialise_or_create_database_at,
        load_experiment_by_name,
        new_experiment,
    )
    import qcodes as qc

    # 初始化数据库
    initialise_or_create_database_at(db_path)

    # 加载或创建实验
    try:
        exp = load_experiment_by_name(exp_name, sample=sample_name)
        print(f"实验已加载: {exp_name} (样品: {sample_name}), 最后ID: {exp.last_counter}")
    except ValueError:
        exp = new_experiment(exp_name, sample_name)
        print(f"创建新实验: {exp_name} (样品: {sample_name})")

    # 创建Measurement
    if station is None:
        station = qc.Station()

    meas = Measurement(exp=exp, station=station)

    return exp, meas, station


def load_cavity_scan_data(dataset):
    """
    从QCoDeS数据集加载腔频扫描数据

    参数：
    - dataset: QCoDeS Dataset对象或run ID

    返回：
    - dict: {'freq': array, 'mag': array, 'phase': array}
    """
    from qcodes.dataset import load_by_run_spec

    # 如果是run ID，加载数据集
    if isinstance(dataset, (int, str)):
        dataset = load_by_run_spec(table_name="results", run_id=int(dataset))

    # 提取数据
    try:
        freq = dataset.get_parameter_data()['DL1_frequency']['DL1_frequency']
        mag = dataset.get_parameter_data()['DL1_magnitude']['DL1_magnitude']
        phase = dataset.get_parameter_data().get('DL1_phase', {}).get('DL1_phase', None)

        return {
            'freq': freq,
            'mag': mag,
            'phase': phase
        }
    except Exception as e:
        print(f"加载数据失败: {e}")
        return None
