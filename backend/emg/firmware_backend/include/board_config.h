#pragma once

// Set these to the GPIOs physically wired to the EMG sensors.
// Use ADC1-capable pins (GPIO 32-39) on the original ESP32.
#define FLEXMAP_EMG_CHANNEL_COUNT 1
#define FLEXMAP_EMG_CH1_PIN 32
#define FLEXMAP_EMG_CH2_PIN -1

#define FLEXMAP_SERIAL_BAUD 115200
#define FLEXMAP_SAMPLE_RATE_HZ 1000
