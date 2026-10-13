#pragma once

static char gatewayNonce[33];

bool gatewayConfigVisible(int id) {
  switch (id) {
    case CF_USEEEPROM: case CF_NETWORK_TYPE: case CF_DHCP:
    case CF_IPADDRESS: case CF_MASK: case CF_GATEWAY: case CF_DNS:
    case CF_WIFI_SSID: case CF_WIFI_PASSWORD: case CF_BASICAUTH:
    case CF_MDNS_HOSTNAME: case CF_WRITEMODE: case CF_MQTT:
    case CF_MQTT_SERVER: case CF_MQTT_USERNAME: case CF_MQTT_PASSWORD:
    case CF_MQTT_TOPIC: case CF_MQTT_DEVICE: case CF_MQTT_UNITS:
    case CF_MQTT_REF_AD: case CF_LOGMODE: case CF_LOGCURRINTERVAL:
    case CF_CURRVALUESLIST:
      return true;
    default: return false;
  }
}

void gatewayNormalizeConfiguration() {
  LoggingMode &= CF_LOGMODE_MQTT | CF_LOGMODE_MQTT_ONLY_LOG_PARAMS;
  webserver = false;
  enable_ota_update = false;
  enable_max_cul = false;
  enable_ipwe = false;
  enable_version_check = false;
  logTelegram = 0;
  BME_Sensors = 0;
  One_Wire_Pin = -1;
  if (programWriteMode > 2) programWriteMode = 0;
  if (log_interval < 30) log_interval = 30;
  for (unsigned i = 0; i < sizeof(DHT_Pins) / sizeof(DHT_Pins[0]); ++i) DHT_Pins[i] = -1;
  if (!gatewayNonce[0]) {
    for (unsigned i = 0; i < 4; ++i) snprintf(gatewayNonce + i * 8, 9, "%08lx", (unsigned long)esp_random());
  }
}

bool gatewayTokenMatches(const char* value) {
  while (*value == ' ' || *value == '\t') ++value;
  if (strcspn(value, "\r\n") != 32) return false;
  unsigned diff = 0;
  for (unsigned i = 0; i < 32; ++i) diff |= value[i] ^ gatewayNonce[i];
  return diff == 0;
}

bool gatewayAllowRequest(const char* path, bool post, bool token, unsigned bodyLength) {
  const bool configWrite = !strcmp(path, "/CI") || !strcmp(path, "/JW");
  const bool parameterWrite = !strcmp(path, "/JS") || (path[1] == 'S' && isdigit(path[2]));
  const bool discovery = !strcmp(path, "/M1") || !strcmp(path, "/M0");
  const bool reboot = !strcmp(path, "/N");
  const bool mutates = configWrite || parameterWrite || discovery || reboot;
  const bool readable = !strcmp(path, "/") || !strcmp(path, "/C") ||
    path[1] == 'K' || isdigit(path[1]) ||
    !strcmp(path, "/JI") || !strcmp(path, "/JK") || !strcmp(path, "/JV") ||
    !strncmp(path, "/JC=", 4) || !strncmp(path, "/JQ=", 4);
  if (mutates && (!post || !token || !USER_PASS[0] || bodyLength > 4096)) {
    printHTTPheader(post ? 403 : 405, MIME_TYPE_TEXT_PLAIN, HTTP_DO_NOT_ADD_CHARSET_TO_HEADER, false, false, HTTP_DO_NOT_CACHE);
    printToWebClient("\r\nPOST with authentication and X-BSB-Token is required.\r\n");
    flushToWebClient();
    return false;
  }
  if (!mutates && (!readable || post)) {
    printHTTPheader(404, MIME_TYPE_TEXT_PLAIN, HTTP_DO_NOT_ADD_CHARSET_TO_HEADER, false, false, HTTP_DO_NOT_CACHE);
    printToWebClient("\r\nThis route is not part of the minimal gateway.\r\n");
    flushToWebClient();
    return false;
  }
  return true;
}
