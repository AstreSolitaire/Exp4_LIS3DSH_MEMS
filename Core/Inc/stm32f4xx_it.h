/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    stm32f4xx_it.h
  * @brief   中断服务函数声明
  *          包含 Cortex-M 系统异常与 EXTI0 / TIM3 / USART2 / RTC_WKUP 四个外设中断
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
#ifndef __STM32F4xx_IT_H
#define __STM32F4xx_IT_H

#ifdef __cplusplus
extern "C" {
#endif

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
/* 不可屏蔽中断声明 */
void NMI_Handler(void);
/* 硬件错误中断声明 */
void HardFault_Handler(void);
/* 存储器管理错误中断声明 */
void MemManage_Handler(void);
/* 总线错误中断声明 */
void BusFault_Handler(void);
/* 用法错误中断声明 */
void UsageFault_Handler(void);
/* 系统服务调用中断声明 */
void SVC_Handler(void);
/* 调试监视中断声明 */
void DebugMon_Handler(void);
/* 可挂起系统调用中断声明 */
void PendSV_Handler(void);
/* 系统节拍中断声明 */
void SysTick_Handler(void);
/* EXTI0 中断声明（PE0 = INT1） */
void EXTI0_IRQHandler(void);
/* USART2 中断声明 */
void USART2_IRQHandler(void);
/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

#ifdef __cplusplus
}
#endif

#endif /* __STM32F4xx_IT_H */
