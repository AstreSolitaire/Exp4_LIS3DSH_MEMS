# 第三方组件说明 / Third-Party Notices

本仓库自有代码（`Core/`、`tools/`、文档、视频）采用根目录 [LICENSE](LICENSE) 中的 **MIT License**。

以下第三方组件遵循其原始许可：

| 目录 / 文件 | 来源 | 许可 |
|---|---|---|
| `Drivers/CMSIS/` | ARM CMSIS（随 STM32Cube FW_F4 V1.28.0 分发） | Apache-2.0（见目录内 LICENSE.txt） |
| `Drivers/STM32F4xx_HAL_Driver/` | STMicroelectronics HAL 驱动 | BSD-3-Clause（见目录内 LICENSE.txt） |
| `MDK-ARM/startup_stm32f407xx.s` | STMicroelectronics 启动文件 | BSD-3-Clause |
| `Drivers/.../stm32f4xx_hal_conf.h` | 由 ST 官方模板裁剪而来 | BSD-3-Clause |

`Exp2_EXTI_TIM_UART_RTC.ioc`、`Core/`、`tools/`、`docs/`、`README.md` 为本人原创，
`.ioc` 由 STM32CubeMX 6.15 生成，工程骨架（外设初始化代码）由该工具自动生成后在其
`USER CODE` 段内补充应用逻辑。

串口监测工具（`tools/serial_monitor_gui.py`、`tools/serial_monitor.py`、
`tools/exp2_selftest.py`）依赖 [pyserial](https://github.com/pyserial/pyserial)（BSD-3-Clause）。
