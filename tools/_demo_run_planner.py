from planner_and_plotter import visualize_and_confirm

sweep_config = {
    "scan_parameters": [
        {
            "symbol": "A",
            "name": "drive_amp_q1_p1",
            "range": [0.2, 0.8],
            "step": 0.1,
            "num_points": 7,
            "where": {"qubit": "q1", "role": "drive", "pulse_index": 0, "field": "amp"},
        },
        {
            "symbol": "B",
            "name": "z_bias_q1_p1",
            "range": [-0.2, 0.2],
            "step": 0.02,
            "num_points": 21,
            "where": {"qubit": "q1", "role": "z", "pulse_index": 0, "field": "amp"},
        },
    ],
    "safety_limits": {"max_safe_voltage": 0.3},
}

sequence_dict = {
    "scan_parameters": sweep_config["scan_parameters"],
    "qubits": [
        {
            "name": "q1",
            "xy": {
                "waveform_bank": {
                    "shape_list": ["Square", "Gauss"],
                    "pw_list": [20e-9, 40e-9],
                    "ew_list": [0.0, 0.0],
                    "amp_list": [0.5, 0.35],
                    "center_list": [0.0, 0.0],
                    "phase_list": [0.0, 90.0],
                    "freq_list": [5.0e9, 5.0e9],
                },
                "delay": 100e-9,
                "spacing_time": 20e-9,
            },
            "z": {
                "waveform_bank": {
                    "shape_list": ["Square"],
                    "pw_list": [120e-9],
                    "ew_list": [0.0],
                    "amp_list": [0.12],
                    "center_list": [0.0],
                    "phase_list": [0.0],
                    "freq_list": [None],
                },
                "delay": 80e-9,
                "spacing_time": 0.0,
            },
            "readout": {
                "waveform_bank": {
                    "shape_list": ["Square"],
                    "pw_list": [4096e-9],
                    "ew_list": [0.0],
                    "amp_list": [0.2],
                    "center_list": [0.0],
                    "phase_list": [0.0],
                    "freq_list": [6.26e9],
                },
                "delay": 150e-9,
                "spacing_time": 0.0,
                "in_delay": 200e-9,
                "sample_length": 2048e-9,
                "shots": 10240,
                "period": 200e-6,
            },
            "acquisition": {"start_ns": 450.0, "length_ns": 2048.0},
        },
        {
            "name": "q2",
            "xy": {
                "waveform_bank": {
                    "shape_list": ["Square"],
                    "pw_list": [30e-9],
                    "ew_list": [0.0],
                    "amp_list": [0.4],
                    "center_list": [0.0],
                    "phase_list": [45.0],
                    "freq_list": [4.9e9],
                },
                "delay": 120e-9,
                "spacing_time": 20e-9,
            },
            "readout": {
                "waveform_bank": {
                    "shape_list": ["Square"],
                    "pw_list": [4096e-9],
                    "ew_list": [0.0],
                    "amp_list": [0.25],
                    "center_list": [0.0],
                    "phase_list": [0.0],
                    "freq_list": [6.30e9],
                },
                "delay": 200e-9,
                "spacing_time": 0.0,
                "in_delay": 220e-9,
                "sample_length": 2048e-9,
                "shots": 8192,
                "period": 200e-6,
            },
            "acquisition": {"start_ns": 520.0, "length_ns": 2048.0},
        },
    ],
}

ok = visualize_and_confirm(sweep_config=sweep_config, sequence_dict=sequence_dict, interactive=False)
print("visualize_and_confirm return:", ok)
