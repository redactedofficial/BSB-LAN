// Minimal application shell; boiler values and controls use the upstream engine.
void webPrintHeader() {
  flushToWebClient();
  printHTTPheader(HTTP_OK, MIME_TYPE_TEXT_HTML, true, false, false, HTTP_DO_NOT_CACHE);
  printToWebClient("\r\n");
  printPStr(header_html, sizeof(header_html));
  printFmtToWebClient("<meta name='gateway-token' content='%s'>", gatewayNonce);
  printPStr(header_html2, sizeof(header_html2));
  printToWebClient("<nav aria-label='Main'><a id='main_link' href='/"); printPassKey();
  printToWebClient("'>BSB-LAN MQTT</a><a href='/"); printPassKey();
  printToWebClient("K'>Parameters</a><a href='/"); printPassKey();
  printToWebClient("C'>Settings</a></nav><p id='notice' role='status' aria-live='polite'></p><main><div class='body-table'><table><tr><td>");
}

void webPrintFooter() {
  printToWebClient("</td></tr></table></div></main><footer>BSB-LAN minimal gateway</footer></body></html>");
  flushToWebClient();
}

void webPrintSite() {
  webPrintHeader();
  printToWebClient("<h1>Gateway status</h1><table><tr><th>Firmware</th><td>");
  printToWebClient(BSB_VERSION);
  printFmtToWebClient("</td></tr><tr><th>Controller</th><td>%s</td></tr><tr><th>Write access</th><td>%s</td></tr><tr><th>MQTT</th><td>%s</td></tr><tr><th>Uptime</th><td>%lu seconds</td></tr><tr><th>Free RAM</th><td>%lu bytes</td></tr></table>",
    my_dev_fam ? "Detected" : "Not detected",
    programWriteMode == 2 ? "Complete" : programWriteMode == 1 ? "Standard" : "Off",
    !(LoggingMode & CF_LOGMODE_MQTT) ? "Off" : MQTTPubSubClient && MQTTPubSubClient->connected() ? "Connected" : "Disconnected",
    (unsigned long)(millis()/1000), (unsigned long)ESP.getFreeHeap());
  printToWebClient("<p>Home Assistant handles history, budgets and automation. Settings select the broker and polled parameters.</p>");
  webPrintFooter();
}
