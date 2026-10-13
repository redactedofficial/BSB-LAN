
/** *****************************************************************
 *  Function:  webPrintHeader()
 *  Does:      Sets up the HTML code to start a web page
 *  Pass parameters:
 *   none
 *  Parameters passed back:
 *   none
 *  Function value returned:
 *   none
 *  Global resources used:
 *   client object
 * *************************************************************** */
void webPrintHeader(void) {
  flushToWebClient();
  printHTTPheader(HTTP_OK, MIME_TYPE_TEXT_HTML, HTTP_ADD_CHARSET_TO_HEADER, HTTP_FILE_NOT_GZIPPED, HTTP_NO_DOWNLOAD, HTTP_DO_NOT_CACHE);
  printPStr(header_html, sizeof(header_html));
  printPStr(console_style, sizeof(console_style));
  printPStr(header_html2, sizeof(header_html2));
  printPStr(console_script, sizeof(console_script));
  printToWebClient("<a class='skip-link' href='#app-main'>Skip to content</a><header class='site-header'><div class='header-inner'><a class='brand' id='main_link' href='/");
  printPassKey();
  printToWebClient("'>");
  printPStr(svg_favicon, sizeof(svg_favicon));
  printToWebClient("<strong>BSB-LAN</strong><span>/ Heating console</span></a><nav class='site-nav' aria-label='Main navigation'><a href='/");
  printPassKey();
  printToWebClient("'>Overview</a><a href='/");
  printPassKey();
  printToWebClient("K'>" MENU_TEXT_HFK "</a><a href='/");
  printPassKey();
  printToWebClient("C'>" MENU_TEXT_CFG "</a><div class='nav-tools'><a href='/");
  printPassKey();
  printFmtToWebClient("K%d'>", CAT_USERSENSORS);
  printToWebClient(STR_TEXT_SNS);
  printToWebClient("</a>");
  #if defined(ARDUINO_ESP32_POE_ISO)
  printToWebClient("<a href='/"); printPassKey(); printToWebClient("SD'>SD card</a>");
  #endif
  if (LoggingMode & CF_LOGMODE_SD_CARD) {
    printToWebClient("<a href='/");
    printPassKey();
    printToWebClient("DG'>" MENU_TEXT_SLG "</a>");
  }
  printToWebClient("<a href='/");
  printPassKey();
  printToWebClient("Q' target='_blank' rel='noopener'>" MENU_TEXT_CHK "</a><a href='" MENU_LINK_TOC "' target='_blank' rel='noopener'>" MENU_TEXT_TOC "</a><a href='" MENU_LINK_URL "' target='_blank' rel='noopener'>" MENU_TEXT_URL "</a><a href='" MENU_LINK_FAQ "' target='_blank' rel='noopener'>" MENU_TEXT_FAQ "</a></div></nav><span class='mode-status' id='write-mode'>");
  printToWebClient((default_flag & FL_RONLY) == FL_RONLY ? "Read-only" : "Check write mode");
  printToWebClient("</span></div></header><main id='app-main' data-supported='");
  // Presentation allow-list: never ask the JSON API for an absent definition.
  const uint16_t overview_parameters[] = {8310, 8314, 8326, 8327, 8700, 8740, 8830};
  bool notfirst = false;
  for (uint i = 0; i < sizeof(overview_parameters) / sizeof(overview_parameters[0]); i++) {
    if (findLine(overview_parameters[i]) >= 0) {
      if (notfirst) printToWebClient(",");
      printFmtToWebClient("%hu", overview_parameters[i]);
      notfirst = true;
    }
  }
  printToWebClient("'><table class='legacy-page'><tr><td class='header'>\r\n");
  flushToWebClient();
} // --- webPrintHeader() ---


/** *****************************************************************
 *  Function:  webPrintFooter()
 *  Does:      Sets up the closing HTML code of a web page.
 *  Pass parameters:
 *   none
 *  Parameters passed back:
 *   none
 *  Function value returned:
 *   none
 *  Global resources used:
 *   client object
 * *************************************************************** */
void webPrintFooter(void) {
  printToWebClient("</td></tr></table></main><footer class='site-footer'><span>BSB-LAN / Heating console</span><span>Local device &middot; UI refresh does not change heating settings</span></footer>\r\n</body>\r\n</html>\r\n\r\n");
  flushToWebClient();
} // --- webPrintFooter() ---

/** *****************************************************************
 *  Function:  webPrintSite()
 *  Does:      Sets up HTML code to display a help page.
 *  Pass parameters:
 *   none
 *  Parameters passed back:
 *   none
 *  Function value returned:
 *   none
 *  Global resources used:
 *   client object
 * *************************************************************** */
void webPrintSite() {
  webPrintHeader();

  printlnToWebClient("<p>");
  printToWebClient("BSB-LAN, Version ");
  printToWebClient(BSB_VERSION);
  if (enable_ota_update) {
    printToWebClient(" / <a id=\"ota_link\" target=\"_new\">OTA</a>");
    printToWebClient("<script>");
    printToWebClient("var port = 8080; var path = '/';");
    printToWebClient("var proto = (location.protocol === 'https' ? 'https' : 'http');");
    printToWebClient("document.getElementById('ota_link').href = proto + '://' + location.hostname + ':' + port + path;");
    printToWebClient("</script>");
  }
#if defined(DEFAULT_DEFS)
  if (bus_type < 2) {
    printlnToWebClient("<p><br><b>" MENU_TEXT_SDF "</b><br><br>");
  }
#endif
  printlnToWebClient("<p><b>" MENU_TEXT_HFK ":</b> " MENU_DESC_HFK );
  printlnToWebClient("<p><b>" MENU_TEXT_CFG ":</b> " MENU_DESC_CFG );
  printlnToWebClient("<p><b>" MENU_TEXT_URL ":</b> " MENU_DESC_URL );

  if (enable_version_check) {
    printlnToWebClient("<BR><BR>" MENU_TEXT_NVS "...<BR>");
    flushToWebClient();
    ComClient *httpclient = new ComClient();
    httpclient->connect("bsb-lan.de", 80);
    httpclient->println("GET /bsb-version.h\r\n");

    unsigned long timeout = millis();
    while (millis() - timeout < 3000 && !httpclient->available()) {
      delay(10);
    }

    int major = -1;
    int minor = -1;
    int patch = -1;
    char version_number[15] = { 0 };
    while (httpclient->available()) {
      char c = httpclient->read();
      if (c == '\"') {
        int index = 0;
        do {
          c = httpclient->read();
          if (index >= 14) continue;  // don't write beyond version_number[]!
          version_number[index] = c;
          index++;
        } while (c != '\"');
        if (index > 1) {
          version_number[index-1] = '\0';
          if (major < 0) {
            major = atoi(version_number);
          } else if (minor < 0) {
            minor = atoi(version_number);
          } else if (patch < 0) {
            patch = atoi(version_number);
          }
        }
      }
    }
    httpclient->stop();
    delete httpclient;
    httpclient = nullptr;
    if ((major > atoi(MAJOR)) || (major == atoi(MAJOR) && minor > atoi(MINOR)) || (major == atoi(MAJOR) && minor == atoi(MINOR) && patch > atoi(PATCH))) {
      printToWebClient(MENU_TEXT_NVA ": ");
      printFmtToWebClient("<A HREF=\"https://github.com/fredlcore/BSB-LAN/archive/master.zip\">%d.%d.%d</A><BR>\r\n", major, minor, patch);
      if (major > atoi(MAJOR) || minor > atoi(MINOR)) {
        printToWebClient(MENU_TEXT_NVW "<BR>\r\n");
      }
    } else {
      printlnToWebClient(MENU_TEXT_NVN);
    }
  }

  webPrintFooter();
} // --- webPrintSite() ---
