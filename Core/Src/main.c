/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : 实验四（综合实验）LIS3DSH 加速度计 —— 简化版
  *
  *  只保留实验必需的功能，用户代码全部集中在本文件：
  *    1) SPI1 读 LIS3DSH：先读 WHO_AM_I 自检，再配置 100 Hz / ±2 g
  *    2) INT1(PE0) 数据就绪中断，主循环据此采样（20 ms 兜底轮询）
  *    3) 每 200 ms 通过 USART2(9600) 上传一行：RTC 时间 + 三轴 mg
  *    4) 自由落体 / 超阈值事件提示
  *    5) 串口命令：$0,1,YYMMDD,HHMMSS* 改时间；$0,5,0/1* 开关上传
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
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "rtc.h"
#include "spi.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
/* LIS3DSH 寄存器地址 */
#define WHO_AM_I      0x0F
#define CTRL_REG3     0x23    /* DRDY->INT1、INT1/INT2 引脚使能 */
#define CTRL_REG4     0x20    /* ODR、三轴使能 */
#define CTRL_REG5     0x24    /* 量程、滤波、SPI 线数 */
#define OUT_X_L       0x28    /* X/Y/Z 输出，共 6 字节 */

#define CS_LOW()      HAL_GPIO_WritePin(LIS3DSH_CS_GPIO_Port, LIS3DSH_CS_Pin, GPIO_PIN_RESET)
#define CS_HIGH()     HAL_GPIO_WritePin(LIS3DSH_CS_GPIO_Port, LIS3DSH_CS_Pin, GPIO_PIN_SET)

#define PRINT_MS      200     /* 上传周期 200 ms = 5 Hz */
#define SAMPLE_MS     20      /* INT1 不来时的兜底采样周期 */
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */
static volatile uint8_t  s_drdy;        /* INT1 中断置 1：有新数据 */
static volatile uint32_t s_drdyCnt;     /* INT1 中断次数，用于统计 */
static volatile uint8_t  s_rxByte;      /* 串口收到的 1 个字节 */
static volatile uint8_t  s_cmdRdy;      /* 收到完整命令帧 */
static volatile uint32_t s_rxCnt;       /* 收到的字节数（诊断） */
static volatile uint32_t s_errCnt;      /* 串口错误次数（诊断） */
static char     s_cmd[32];
static uint8_t  s_cmdLen;
static uint8_t  s_inFrame;
static uint8_t  s_stream = 1;           /* 1 = 持续上传 */
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
static void LIS3DSH_Write(uint8_t reg, uint8_t val);
static void LIS3DSH_Read(uint8_t reg, uint8_t *buf, uint8_t len);
static uint8_t LIS3DSH_Init(void);
static void LIS3DSH_GetXYZ(int16_t *x, int16_t *y, int16_t *z);
static void Uart_Cmd(char *s);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
#if defined(__CC_ARM)
#pragma import(__use_no_semihosting)     /* 不用半主机，printf 才能脱机工作 */
struct __FILE { int handle; };
FILE __stdout;
/* 半主机模式空实现（armcc 要求） */
void _sys_exit(int x) { (void)x; }
/* 半主机模式空实现（armcc 要求） */
void _ttywrch(int ch) { (void)ch; }
#endif

/* printf 重定向：阻塞发送 1 字节（9600 下一行约 40 ms） */
int fputc(int ch, FILE *f)
{
  (void)f;
  HAL_UART_Transmit(&huart2, (uint8_t *)&ch, 1, 10);
  return ch;
}

/* 写一个寄存器：地址 bit7 = 0 */
static void LIS3DSH_Write(uint8_t reg, uint8_t val)
{
  uint8_t buf[2] = { reg, val };
  CS_LOW();
  HAL_SPI_Transmit(&hspi1, buf, 2, 10);
  CS_HIGH();
}

/* 读 len 个寄存器：地址 bit7 = 1，逐字节读 */
static void LIS3DSH_Read(uint8_t reg, uint8_t *buf, uint8_t len)
{
  uint8_t i;
  for (i = 0; i < len; i++)
  {
    uint8_t tx[2] = { (uint8_t)(reg + i) | 0x80, 0x00 };
    uint8_t rx[2];
    CS_LOW();
    HAL_SPI_TransmitReceive(&hspi1, tx, rx, 2, 10);
    CS_HIGH();
    buf[i] = rx[1];
  }
}

/* 初始化：ID 自检 + ±2 g + 100 Hz + 三轴 + DRDY 中断到 INT1 */
static uint8_t LIS3DSH_Init(void)
{
  uint8_t id = 0;
  LIS3DSH_Read(WHO_AM_I, &id, 1);
  if (id != 0x3F)
  {
    return 0;
  }
  LIS3DSH_Write(CTRL_REG5, 0x00);   /* ±2 g，800 Hz，4 线 SPI */
  LIS3DSH_Write(CTRL_REG4, 0x67);   /* 100 Hz，XYZ 使能 */
  LIS3DSH_Write(CTRL_REG3, 0xF8);   /* DRDY->INT1，高有效脉冲，INT1/INT2 使能 */
  return 1;
}

/* 读三轴，换算成 mg（±2 g：0.06 mg/LSB，即 raw*6/100） */
static void LIS3DSH_GetXYZ(int16_t *x, int16_t *y, int16_t *z)
{
  uint8_t b[6];
  LIS3DSH_Read(OUT_X_L, b, 6);
  *x = (int16_t)(((uint16_t)b[1] << 8) | b[0]) * 6 / 100;
  *y = (int16_t)(((uint16_t)b[3] << 8) | b[2]) * 6 / 100;
  *z = (int16_t)(((uint16_t)b[5] << 8) | b[4]) * 6 / 100;
}

/* 执行一条命令：帧内容形如 "0,5,1" 或 "0,1,251120,120000" */
static void Uart_Cmd(char *s)
{
  int addr, code, ymd = 0, hms = 0;

  if (sscanf(s, "%d,%d,%d,%d", &addr, &code, &ymd, &hms) < 2)
  {
    return;
  }
  (void)addr;

  if (code == 5)                                  /* 开关上传 */
  {
    s_stream = (ymd != 0) ? 1 : 0;
    HAL_GPIO_WritePin(GPIOD, LD3_Pin, s_stream ? GPIO_PIN_SET : GPIO_PIN_RESET);
    printf("[CMD] stream %s\r\n", s_stream ? "ON" : "OFF");
  }
  else if (code == 1)                             /* 改 RTC 时间 */
  {
    RTC_TimeTypeDef t = {0};
    RTC_DateTypeDef d = {0};
    if (ymd < 100000 || hms < 100000)
    {
      return;
    }
    t.Hours = hms / 10000;
    t.Minutes = hms % 10000 / 100;
    t.Seconds = hms % 100;
    t.DayLightSaving = RTC_DAYLIGHTSAVING_NONE;
    t.StoreOperation = RTC_STOREOPERATION_RESET;
    d.Year = ymd / 10000;
    d.Month = ymd % 10000 / 100;
    d.Date = ymd % 100;
    d.WeekDay = RTC_WEEKDAY_MONDAY;               /* 星期不影响走时，固定值 */
    HAL_RTC_SetTime(&hrtc, &t, RTC_FORMAT_BIN);
    HAL_RTC_SetDate(&hrtc, &d, RTC_FORMAT_BIN);
    printf("[RTC] 20%02d-%02d-%02d %02d:%02d:%02d\r\n",
           d.Year, d.Month, d.Date, t.Hours, t.Minutes, t.Seconds);
  }
}
/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
/* 主函数：初始化外设 -> 传感器自检 -> 主循环（采样 / 上传 / 事件 / 命令） */
int main(void)
{

  /* USER CODE BEGIN 1 */
  int16_t x = 0, y = 0, z = 0;
  uint32_t lastSample, lastPrint, lastStat, ffTick = 0, hgTick = 0, evtTick = 0;
  RTC_TimeTypeDef t;
  RTC_DateTypeDef d;
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_RTC_Init();
  MX_SPI1_Init();
  MX_USART2_UART_Init();
  /* USER CODE BEGIN 2 */
  /* RTC 上电给一个初始时间：2025-11-20 09:00:00 */
  {
    RTC_TimeTypeDef t0 = {0};
    RTC_DateTypeDef d0 = {0};
    t0.Hours = 9; t0.Minutes = 0; t0.Seconds = 0;
    t0.DayLightSaving = RTC_DAYLIGHTSAVING_NONE;
    t0.StoreOperation = RTC_STOREOPERATION_RESET;
    d0.WeekDay = RTC_WEEKDAY_THURSDAY;
    d0.Month = RTC_MONTH_NOVEMBER; d0.Date = 20; d0.Year = 25;
    HAL_RTC_SetTime(&hrtc, &t0, RTC_FORMAT_BIN);
    HAL_RTC_SetDate(&hrtc, &d0, RTC_FORMAT_BIN);
  }

  printf("\r\n** Experiment 4: LIS3DSH accelerometer **\r\n");
  printf("SPI1: PA5/PA6/PA7  CS=PE3  INT1=PE0\r\n");
  printf("USART2: 9600-8-N-1, data 5 Hz\r\n");

  if (LIS3DSH_Init() == 0)
  {
    printf("[ERR] WHO_AM_I != 0x3F, check SPI1/CS wiring\r\n");
    while (1)                              /* 自检失败：LD5 慢闪 */
    {
      HAL_GPIO_TogglePin(GPIOD, LD5_Pin);
      HAL_Delay(200);
    }
  }
  printf("[OK] LIS3DSH ready: 100 Hz, +-2 g\r\n");
  HAL_GPIO_WritePin(GPIOD, LD3_Pin, GPIO_PIN_SET);       /* LD3：上传中 */

  HAL_UART_Receive_IT(&huart2, (uint8_t *)&s_rxByte, 1); /* 开串口接收中断 */

  lastSample = lastPrint = lastStat = HAL_GetTick();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    uint32_t now = HAL_GetTick();

    /* 0) 兜底：接收中断若因错误停摆，这里重新挂上 */
    if (huart2.RxState == HAL_UART_STATE_READY)
    {
      HAL_UART_Receive_IT(&huart2, (uint8_t *)&s_rxByte, 1);
    }

    /* 1) 采样：INT1 触发；20 ms 没中断就自己读一次（INT1 没接也能用） */
    if (s_drdy || (now - lastSample) >= SAMPLE_MS)
    {
      s_drdy = 0;
      lastSample = now;
      LIS3DSH_GetXYZ(&x, &y, &z);

      /* 自由落体：合加速度 < 300 mg（用平方比较，省去开方） */
      if ((int32_t)x * x + (int32_t)y * y + (int32_t)z * z < 300L * 300L)
      {
        if (now - ffTick > 2000)
        {
          ffTick = now;
          printf("[EVT] FREE-FALL\r\n");
          HAL_GPIO_WritePin(GPIOD, LD5_Pin, GPIO_PIN_SET);
          evtTick = now;
        }
      }
      /* 超阈值：任一轴 > 1.5 g */
      if ((x > 1500) || (x < -1500) || (y > 1500) || (y < -1500) ||
          (z > 1500) || (z < -1500))
      {
        if (now - hgTick > 1000)
        {
          hgTick = now;
          printf("[EVT] HIGH-G X=%d Y=%d Z=%d\r\n", x, y, z);
          HAL_GPIO_WritePin(GPIOD, LD5_Pin, GPIO_PIN_SET);
          evtTick = now;
        }
      }
    }

    /* 2) 每 200 ms 上传一行：RTC 时间 + 三轴 mg */
    if (s_stream && (now - lastPrint) >= PRINT_MS)
    {
      lastPrint = now;
      HAL_RTC_GetTime(&hrtc, &t, RTC_FORMAT_BIN);
      HAL_RTC_GetDate(&hrtc, &d, RTC_FORMAT_BIN);
      printf("%02d:%02d:%02d  X=%+05d Y=%+05d Z=%+05d mg\r\n",
             t.Hours, t.Minutes, t.Seconds, x, y, z);
    }

    /* 3) 执行串口命令（中断里只收帧，解析放主循环） */
    if (s_cmdRdy)
    {
      s_cmdRdy = 0;
      Uart_Cmd(s_cmd);
    }

    /* 4) LED：LD6 亮表示 INT1 中断正常；LD5 事件亮 300 ms */
    HAL_GPIO_WritePin(GPIOD, LD6_Pin, s_drdyCnt ? GPIO_PIN_SET : GPIO_PIN_RESET);
    if (evtTick && (now - evtTick) > 300)
    {
      evtTick = 0;
      HAL_GPIO_WritePin(GPIOD, LD5_Pin, GPIO_PIN_RESET);
    }

    /* 5) 每 10 s 报一次 INT1 中断次数，可用来核对 100 Hz */
    if ((now - lastStat) >= 10000)
    {
      lastStat = now;
      printf("[STAT] drdy=%lu rx=%lu err=%lu\r\n",
             (unsigned long)s_drdyCnt, (unsigned long)s_rxCnt, (unsigned long)s_errCnt);
    }
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
/* 系统时钟配置：HSE 8 MHz 经 PLL 倍频到 168 MHz（APB1=42M，APB2=84M） */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_LSI|RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.LSIState = RCC_LSI_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 8;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */
/* INT1(PE0) 上升沿：只置标志、计数，不做耗时操作 */
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
  if (GPIO_Pin == LIS3DSH_INT1_Pin)
  {
    s_drdy = 1;
    s_drdyCnt++;
  }
}

/* 串口收 1 字节：组帧 $...*，收满置标志，主循环解析 */
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  uint8_t c = s_rxByte;
  if (c == '$')
  {
    s_inFrame = 1;
    s_cmdLen = 0;
  }
  else if (s_inFrame && c == '*')
  {
    s_inFrame = 0;
    s_cmd[s_cmdLen] = '\0';
    s_cmdRdy = 1;
  }
  else if (s_inFrame && s_cmdLen < sizeof(s_cmd) - 1)
  {
    s_cmd[s_cmdLen++] = (char)c;
  }
  s_rxCnt++;
  HAL_UART_Receive_IT(&huart2, (uint8_t *)&s_rxByte, 1);
}

/* 串口出错（溢出/噪声）：清标志并重新挂接收，避免接收永久停摆 */
void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
  (void)huart;
  s_errCnt++;
  __HAL_UART_CLEAR_OREFLAG(&huart2);
  HAL_UART_Receive_IT(&huart2, (uint8_t *)&s_rxByte, 1);
}
/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
/* 错误兜底：关中断并停在这里，方便调试器定位 */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
/* 参数断言失败回调（仅 USE_FULL_ASSERT 打开时使用） */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  (void)file;
  (void)line;
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
