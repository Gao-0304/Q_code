# 技能：动态接线映射表生成 (Dynamic Wiring Map Generation)
## 触发时机
当实验方案规划完成，准备编写 QCoDeS 测量程序之前。
## 执行逻辑
1. **分析需求**：分析本次实验需要用到哪些物理信号（例如：XY控制线的微波脉冲、Z线的直流磁通偏置、Readout腔的探测微波）。
2. **生成 YAML 结构**：在 `memory/wiring_map.yaml` 中动态生成一个包含 `requested_wiring` 的表单。
3. **内容要求**：
   - 必须包含：用途 (purpose)、信号类型 (Microwave/DC)。
   - 必须预留字段供用户填写：仪器端口 (instrument_port)、制冷机线路 (fridge_line)、衰减/滤波参数 (attenuation_dB / filter_type)。
   - **对于 DC 线路**：必须自动强制加入 `max_safe_voltage` 预留字段。
4. **挂起确认**：生成文件后，在终端打印：“【接线需求已生成】请前往 `memory/wiring_map.yaml` 填写具体的物理接线与衰减参数。填写完成后请回复‘已填完’。”
5. **读取并校验**：用户回复后，读取该 YAML 文件。如果发现衰减值未填或 DC 线路未设置安全上限，拒绝进行下一步。
## 示例输出格式
```yaml
requested_wiring:
  experiment: "[提取的实验名]"
  lines:
    XY_Drive:
      type: "Microwave"
      instrument_port: "" # 等待用户填写
      fridge_line: ""     # 等待用户填写
      attenuation_dB:     # 等待用户填写 (例如: -60)
    Z_Bias:
      type: "DC"
      instrument_port: "" 
      fridge_line: ""
      filter_type: ""
      max_safe_voltage:   # 等待用户填写 (必填！)