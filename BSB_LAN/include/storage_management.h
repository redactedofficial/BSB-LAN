// Isolated SD management for the fixed-pin, 1-bit Olimex ESP32-POE-ISO.
// No boiler calls; never operates on LittleFS. Mutations require authenticated
// POST, a per-boot nonce, an idle logger and explicit confirmation for format.
#if defined(ARDUINO_ESP32_POE_ISO)
#include "esp_vfs_fat.h"
#include "driver/sdmmc_host.h"
#include "sdmmc_cmd.h"
static char sdManagementToken[33] = {};
static uint32_t sdAuditBoot = 0;
static void sdNewToken() {
  snprintf(sdManagementToken, sizeof(sdManagementToken), "%08lx%08lx%08lx%08lx",
    (unsigned long)esp_random(), (unsigned long)esp_random(),
    (unsigned long)esp_random(), (unsigned long)esp_random());
}
static bool sdBusy() {
  return webserver || (LoggingMode & (CF_LOGMODE_SD_CARD | CF_LOGMODE_24AVG)) || (logTelegram & LOGTELEGRAM_ON);
}
static String sdRootName(const char *name) { return String(name[0] == '/' ? name + 1 : name); }
static bool sdProtectedFile(const String &name) {
  return name == sdRootName(datalogIndexFileName) || name == sdRootName(datalogTemporaryFileName) ||
    name == sdRootName(datalogIndexTemporaryFileName) || name == sdRootName(averagesFileName);
}
static bool sdSafeName(const String &name) {
  if (!name.length() || name.length() > 96 || name[0] == '.' || name.indexOf("..") >= 0) return false;
  for (unsigned i = 0; i < name.length(); ++i) {
    char c = name[i];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
          (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.')) return false;
  }
  return true;
}
static bool sdAudit(const String &action, const String &name, bool ok) {
  if (SD_MMC.cardType() == CARD_NONE) return false;
  const char *path = "/storage-audit.jsonl";
  File existing = SD_MMC.open(path, FILE_READ);
  bool rotate = existing && existing.size() >= 262144; existing.close();
  if (rotate) {
    SD_MMC.remove("/storage-audit.previous.jsonl");
    if (!SD_MMC.rename(path, "/storage-audit.previous.jsonl")) return false;
  }
  File audit = SD_MMC.open(path, FILE_APPEND);
  if (!audit) return false;
  // Filenames/actions were validated. No passwords, nonces or boiler payloads.
  String line = String("{\"boot_id\":") + String(sdAuditBoot) + ",\"uptime_ms\":" + String(millis()) + ",\"action\":\"" + action +
    "\",\"file\":\"" + (sdSafeName(name) ? name : String("")) +
    "\",\"ok\":" + (ok ? "true" : "false") + "}\n";
  bool written = audit.print(line) == line.length(); audit.close(); return written;
}
static void sdResponse(int code, const String &body, const char *type = "application/json") {
  forcedflushToWebClient();
  client.printf("HTTP/1.1 %d %s\r\nContent-Type: %s; charset=utf-8\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nContent-Length: %u\r\nConnection: close\r\n\r\n",
    code, code == 200 ? "OK" : "Error", type, (unsigned)body.length());
  client.print(body);
}
static void sdError(int code, const char *message) {
  sdResponse(code, String("{\"error\":\"") + message + "\"}");
}
static bool sdManagement(const char *path, bool post, unsigned bodyLength, bool serial) {
  if (strncmp(path, "/SD", 3) || (path[3] && path[3] != '/')) return false;
  if (serial) { sdError(403, "Use the authenticated web interface."); return true; }
  if (!sdManagementToken[0]) { sdAuditBoot = esp_random(); sdNewToken(); }
  if (!strcmp(path, "/SD") && !post) {
    webPrintHeader(); printToWebClient("<div id='sd-management'></div>"); webPrintFooter(); return true;
  }
  bool mounted = SD_MMC.cardType() != CARD_NONE;
  if (!strcmp(path, "/SD/status") && !post) {
    String result = String("{\"mounted\":") + (mounted ? "true" : "false") +
      ",\"busy\":" + (sdBusy() ? "true" : "false") +
      ",\"selected\":" + (LogDestination == SDCARD ? "true" : "false") +
      ",\"authorized\":" + (USER_PASS[0] ? "true" : "false") +
      ",\"logging\":" + ((LoggingMode & CF_LOGMODE_SD_CARD) ? "true" : "false") +
      ",\"interval\":" + String(log_interval) +
      ",\"token\":\"" + sdManagementToken + "\",\"total\":" + String((unsigned long long)(mounted ? SD_MMC.totalBytes() : 0)) +
      ",\"used\":" + String((unsigned long long)(mounted ? SD_MMC.usedBytes() : 0)) + ",\"files\":[";
    bool comma = false; unsigned count = 0;
    if (mounted) {
      File root = SD_MMC.open("/"); File entry = root.openNextFile();
      while (entry && count < 100) {
        String name = entry.name();
        if (!entry.isDirectory() && sdSafeName(name)) {
          if (comma) result += ',';
          result += String("{\"name\":\"") + name + "\",\"protected\":" + (sdProtectedFile(name) ? "true" : "false") + ",\"size\":" + String((unsigned long)entry.size()) + "}";
          comma = true; count++;
        }
        entry.close(); entry = root.openNextFile();
      }
      bool truncated = (bool)entry; entry.close(); root.close();
      result += String("],\"truncated\":") + (truncated ? "true" : "false") + "}";
    } else result += "],\"truncated\":false}";
    sdResponse(200, result); return true;
  }
  if (!strncmp(path, "/SD/download/", 13) && !post) {
    String name(path + 13);
    if (!mounted || !sdSafeName(name)) { sdError(400, "Card or filename unavailable."); return true; }
    File file = SD_MMC.open("/" + name, FILE_READ);
    if (!file || file.isDirectory()) { file.close(); sdError(404, "File not found."); return true; }
    if (file.size() > 1048576) { file.close(); sdError(413, "Files above 1 MiB must be copied using a card reader."); return true; }
    forcedflushToWebClient();
    client.printf("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Disposition: attachment; filename=\"%s\"\r\nContent-Length: %u\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n", name.c_str(), (unsigned)file.size());
    uint8_t buffer[512]; unsigned long deadline = millis() + 15000;
    while (file.available() && client.connected() && (int32_t)(deadline - millis()) > 0) {
      size_t n = file.read(buffer, sizeof(buffer));
      if (!n || client.write(buffer, n) != n) break;
    }
    file.close(); return true;
  }
  if (strcmp(path, "/SD/action") || !post) { sdError(405, "Use POST for storage actions."); return true; }
  if (!USER_PASS[0]) { sdError(403, "Configure web authentication before managing storage."); return true; }
  if (sdBusy() || LogDestination != SDCARD) { sdError(409, "Stop SD logging, averages and telegram logging; select SD card storage first."); return true; }
  if (!bodyLength || bodyLength > 180) { sdError(400, "Invalid request length."); return true; }
  String body; body.reserve(bodyLength); unsigned long deadline = millis() + 3000;
  while (body.length() < bodyLength && client.connected() && (int32_t)(deadline - millis()) > 0) {
    if (client.available()) body += (char)client.read(); else delay(1);
  }
  int first = body.indexOf('\n'), second = body.indexOf('\n', first + 1), third = body.indexOf('\n', second + 1);
  if (body.length() != bodyLength || first != 32 || second < 0 || third < 0 || body.substring(0, first) != sdManagementToken) {
    sdError(403, "Request expired. Refresh card status and try again."); return true;
  }
  String action = body.substring(first + 1, second), name = body.substring(second + 1, third), confirmation = body.substring(third + 1);
  sdNewToken(); // Reject replay, including after a failed operation.
  bool ok = false;
  if (action == "mount") ok = SD_MMC.begin("", true, false, 10000);
  else if (action == "unmount" && mounted) {
    if (!sdAudit(action, "", true)) { sdError(500, "Could not record unmount. Card remains mounted."); return true; }
    SD_MMC.end(); ok = true;
  }
  else if (action == "delete" && mounted && sdSafeName(name) && confirmation == "DELETE") {
    File file = SD_MMC.open("/" + name, FILE_READ);
    bool regular = file && !file.isDirectory(); file.close();
    if (regular && !sdProtectedFile(name)) {
      ok = SD_MMC.remove("/" + name);
      if (ok && name == sdRootName(datalogFileName)) ok = createdatalogFileAndWriteHeader();
    }
  } else if (action == "format" && name == "" && confirmation == "FORMAT") {
    // Public IDF APIs own the temporary card handle; no protected members or raw sector writes.
    SD_MMC.end();
    sdmmc_host_t host = SDMMC_HOST_DEFAULT(); host.flags = SDMMC_HOST_FLAG_1BIT; host.max_freq_khz = 10000;
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT(); slot.width = 1;
    esp_vfs_fat_mount_config_t config = {}; config.max_files = 5; config.format_if_mount_failed = true; // Only inside an explicitly confirmed format action.
    sdmmc_card_t *card = nullptr;
    esp_err_t mountedResult = esp_vfs_fat_sdmmc_mount("/bsbformat", &host, &slot, &config, &card);
    if (mountedResult == ESP_OK) {
      esp_err_t formatted = esp_vfs_fat_sdcard_format("/bsbformat", card);
      esp_err_t unmounted = esp_vfs_fat_sdcard_unmount("/bsbformat", card);
      bool remounted = unmounted == ESP_OK && SD_MMC.begin("", true, false, 10000);
      ok = formatted == ESP_OK && remounted;
    } else SD_MMC.begin("", true, false, 10000); // Try to restore access without automatic formatting.
  } else { sdError(400, "Invalid action or confirmation."); return true; }
  if (ok && (action == "mount" || action == "format")) {
    if (!SD_MMC.exists(datalogFileName)) ok = createdatalogFileAndWriteHeader();
    else readFirstAndPreviousDatalogDateFromFile();
  }
  bool audited = action == "unmount" ? ok : sdAudit(action, name, ok);
  if (ok) sdResponse(200, String("{\"ok\":true,\"audited\":") + (audited ? "true" : "false") + "}");
  else sdError(500, action == "format" ? "Format failed. Data may have been erased; check the card and refresh status." : "Card operation failed. Check card seating and compatibility, then refresh status.");
  return true;
}
#else
static bool sdManagement(const char *, bool, unsigned, bool) { return false; }
#endif
