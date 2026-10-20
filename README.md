# Modbus Rotator

PySide6 深色工业控制台，支持 XY-SMH Modbus-RTU、模拟设备、GS-232B、N1MM UDP、Hamlib `rotctld`、断电偏移恢复和硬止点。

## 启动

```powershell
python -m pip install -r requirements.txt
python -m app.main --simulate
```

界面为中文深色控制台。真实设备模式在“设置”页配置 COM、波特率、从机地址和超时。默认 Modbus 为 `115200 8N1`、从机地址 `1`。配置保存到 `%LOCALAPPDATA%\ModbusRotator\rotator_config.json`，写入使用临时文件、`fsync`、`os.replace`，不会写入 PyInstaller 临时目录。

## Modbus 安全参数

运动前自动读取并校验：运行模式 `0x0002 = 4`、循环次数 `0x0106 = 1`、F-02 距离 `0x010E/0x010F = 360000`。不匹配时禁止运动；设置页“应用安全参数”会同步这些值。距离寄存器按高字在前编码：正转 `0x0100/0x0101`，反转 `0x0103/0x0104`，先写停止触发值并等待 100 ms，再写距离和触发值。

硬止点由旋转范围和止点组成，默认范围 360°、止点 0°，可配置至 450°。目标会转换为止点区间内的等价角度，不能安全到达时拒绝；运行中越界触发急停。距离寄存器当前按 1000 单位/度换算，对应 F-02 `360000` 的默认圈距。真实角度遵循 `Hardware_Coord_Deg + Software_Offset_Deg`。控制器重启后若硬件角度接近 0°，会用上次真实角度恢复偏移。

`0x0003/0x0004` 当前角度、`0x0108` 温度、`0x0109` 限位、`0x010A` 报警、`0x0102/0x0105/0x0107` 触发状态和 `0x0015` 运行位按候选布局实现。请与所用 XY-SMH 固件手册核对后再接真实设备；原始需求未给出这些 telemetry 寄存器的正式映射。F-08/F-04/F-05/P-2/P-4/F-13/F-14 数值会保存到配置，但具体硬件写入映射也需手册确认。已知安全参数和正反转距离地址按需求实现。

## 外部控制

- GS-232B：独立串口线程，默认 9600 8N1，支持 `C`、`C2`、`Mxxx`、`S`、`A`、`R`、`L`。
- N1MM UDP：默认监听 `127.0.0.1:12040`，解析 `<N1MMRotor><goazi>xxx</goazi></N1MMRotor>`，非法 XML 或角度丢弃。
- Hamlib `rotctld`：默认 `127.0.0.1:4533`，支持 `p`、`P <az> <el>`、`S`，仰角忽略，查询固定返回 0°。
- com0com：设置页可浏览并保存任意 `setupc.exe` 路径，分别填写左右端口名称（默认 `COM10`、`COM11`），再创建虚拟串口对。留空路径时自动检查 PATH、`%ProgramFiles%` 和 `%ProgramFiles(x86)%`。缺少安装、路径无效或权限不足时只显示中文提示，不阻塞界面。

网络服务只提交运动队列，串口和 Modbus 仍由 worker 独占。N1MM、Hamlib 默认仅本机监听。

## 接线与调试

RS-485 A/B、地线和 XY-SMH 设备手册保持一致；先低速确认方向，再启用自动控制。“调试终端”支持原始报文、寄存器读写和触发值测试。界面底部显示运行、温度、限位和报警状态。设置页采用左右两列分组布局，小窗口可滚动查看。

## Windows 构建

GitHub Actions 使用 `windows-latest`、Python 3.12 x64，运行 pytest 后调用 `rotator.spec` 构建 `ModbusRotator.exe` onefile，并上传带版本号的 zip artifact。工作流由推送到 `main` 或 `workflow_dispatch` 触发。

