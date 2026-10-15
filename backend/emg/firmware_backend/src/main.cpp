#include <Arduino.h>
#include "board_config.h"

#if FLEXMAP_EMG_CHANNEL_COUNT != 1 && FLEXMAP_EMG_CHANNEL_COUNT != 2
#error "FLEXMAP_EMG_CHANNEL_COUNT must be 1 or 2"
#endif
#if FLEXMAP_EMG_CH1_PIN < 32 || FLEXMAP_EMG_CH1_PIN > 39
#error "Set FLEXMAP_EMG_CH1_PIN to the verified ADC1 GPIO (32-39)"
#endif
#if FLEXMAP_EMG_CHANNEL_COUNT == 2 && (FLEXMAP_EMG_CH2_PIN < 32 || FLEXMAP_EMG_CH2_PIN > 39)
#error "Set FLEXMAP_EMG_CH2_PIN to the verified ADC1 GPIO (32-39)"
#endif

namespace {
constexpr uint32_t kPeriodUs = 1000000UL / FLEXMAP_SAMPLE_RATE_HZ;
uint32_t nextSampleUs = 0;
}

void setup() {
  Serial.begin(FLEXMAP_SERIAL_BAUD);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
  pinMode(FLEXMAP_EMG_CH1_PIN, INPUT);
#if FLEXMAP_EMG_CHANNEL_COUNT == 2
  pinMode(FLEXMAP_EMG_CH2_PIN, INPUT);
#endif
  nextSampleUs = micros() + kPeriodUs;
}

void loop() {
  const int32_t remaining = static_cast<int32_t>(nextSampleUs - micros());
  if (remaining > 0) {
    if (remaining > 80) delayMicroseconds(static_cast<uint32_t>(remaining - 50));
    return;
  }
  nextSampleUs += kPeriodUs;
  const uint16_t channel1 = analogRead(FLEXMAP_EMG_CH1_PIN);
#if FLEXMAP_EMG_CHANNEL_COUNT == 2
  const uint16_t channel2 = analogRead(FLEXMAP_EMG_CH2_PIN);
  Serial.print(channel1);
  Serial.write(',');
  Serial.println(channel2);
#else
  Serial.println(channel1);
#endif
}
