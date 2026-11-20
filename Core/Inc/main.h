/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : 主头文件
  *                   集中定义：板级引脚编号、跨文件共享变量声明、
  *                   串口 DMA 收发接口（Uart_* 系列）
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32f4xx_hal.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
/* 错误处理函数声明 */
void Error_Handler(void);

/* USER CODE BEGIN EFP */
/* 实验四：RTC 秒中断与主循环共享的时间数据（数据行时间戳 / 暂停心跳） */
extern volatile uint32_t m_nRtcYMD;      /* 年月日 YYMMDD */
extern volatile uint32_t m_nRtcHMS;      /* 时分秒 HHMMSS */
extern volatile uint8_t  g_rtcSecFlag;   /* 1 = 有一帧新的时间字符串待发送 */
extern char              g_rtcString[32];/* 已格式化的时间字符串 */

/* 串口帧接收 */
extern char    chRxBuf[];                 /* 当前帧内容（不含 $ 和 *） */
extern volatile uint8_t g_frameRdy;       /* 1 = 收到完整一帧 */

/* 串口 DMA 收发接口（usart.c 实现） */
extern uint8_t g_uartRxDma[64];           /* RX DMA 接收缓冲 */
void    Uart_DmaInit(void);               /* 初始化 USART2 TX/RX 的 DMA */
void    Uart_SendAsync(const uint8_t *data, uint16_t len);  /* 异步发送（入环形缓冲） */
int     Uart_TxChar(int ch);              /* printf 重定向用：单字节入队 */
uint8_t App_FrameFeed(const uint8_t *buf, uint16_t len);    /* 收到一段数据 -> 喂帧状态机 */
/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define LIS3DSH_CS_Pin GPIO_PIN_3
#define LIS3DSH_CS_GPIO_Port GPIOE
#define PH0_OSC_IN_Pin GPIO_PIN_0
#define PH0_OSC_IN_GPIO_Port GPIOH
#define PH1_OSC_OUT_Pin GPIO_PIN_1
#define PH1_OSC_OUT_GPIO_Port GPIOH
#define USART2_TX_Pin GPIO_PIN_2
#define USART2_TX_GPIO_Port GPIOA
#define USART2_RX_Pin GPIO_PIN_3
#define USART2_RX_GPIO_Port GPIOA
#define SPI1_SCK_Pin GPIO_PIN_5
#define SPI1_SCK_GPIO_Port GPIOA
#define SPI1_MISO_Pin GPIO_PIN_6
#define SPI1_MISO_GPIO_Port GPIOA
#define SPI1_MOSI_Pin GPIO_PIN_7
#define SPI1_MOSI_GPIO_Port GPIOA
#define LD3_Pin GPIO_PIN_13
#define LD3_GPIO_Port GPIOD
#define LD5_Pin GPIO_PIN_14
#define LD5_GPIO_Port GPIOD
#define LD6_Pin GPIO_PIN_15
#define LD6_GPIO_Port GPIOD
#define SWDIO_Pin GPIO_PIN_13
#define SWDIO_GPIO_Port GPIOA
#define SWCLK_Pin GPIO_PIN_14
#define SWCLK_GPIO_Port GPIOA
#define LIS3DSH_INT1_Pin GPIO_PIN_0
#define LIS3DSH_INT1_GPIO_Port GPIOE
#define LIS3DSH_INT1_EXTI_IRQn EXTI0_IRQn

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
