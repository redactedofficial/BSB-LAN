/* Heating presentation and isolated SD actions: no boiler SET/INF, bus mode changes or decoding. */
(() => {
  'use strict';
  const selected = [
    [8310,'Boiler temperature'],[8314,'Return temperature'],[8326,'Burner output'],
    [8327,'Water pressure'],[8700,'Outside temperature'],[8740,'Room temperature'],[8830,'Hot water temperature']
  ];
  const $ = id => document.getElementById(id);
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function searchControl(onChange) {
    const wrap = node('div', undefined, 'search-wrap');
    const input = node('input'); input.type = 'search'; input.placeholder = 'Search parameters';
    input.setAttribute('aria-label','Search parameters');
    const clear = node('button','Clear'); clear.type = 'button'; clear.hidden = true;
    clear.setAttribute('aria-label','Clear parameter search');
    let composing = false;
    const run = () => { if (!composing) { clear.hidden = !input.value; onChange(input.value.trim().toLowerCase()); } };
    input.addEventListener('compositionstart', () => composing = true);
    input.addEventListener('compositionend', () => { composing = false; run(); });
    input.addEventListener('input', run);
    clear.addEventListener('click', () => { input.value = ''; run(); input.focus(); });
    wrap.append(input,clear); return wrap;
  }
  function reading(item, loaded) {
    if (!loaded) return {value:'—', state:'Definition not loaded', kind:'unavailable'};
    if (!item) return {value:'—', state:'Not read yet', kind:'unavailable'};
    if (Number(item.error) !== 0) return {value:'—', state:Number(item.error) === 7 ? 'Not supported' : 'Read failed',kind:'unavailable'};
    const value = String(item.value ?? '').trim();
    if (!value || /^(---|none|null|nan)$/i.test(value)) return {value:'—',state:'Unavailable',kind:'unavailable'};
    // Values are already decoded by the upstream API; only display formatting here.
    const unit = String(item.unit ?? '').replace(/&deg;/g,'°').replace(/&nbsp;/g,' ');
    return {value:value + (unit ? ' '+unit : ''),state:'Available',kind:''};
  }
  if(typeof module !== 'undefined' && module.exports) module.exports = {reading};
  if(typeof document === 'undefined') return;
  document.addEventListener('DOMContentLoaded', () => {
    const base = new URL($('main_link').href);
    const route = location.pathname.slice(base.pathname.length);
    const labels = route === '' ? ['Overview','Your heating system'] : route === 'C' ? ['Settings','Settings'] : route.startsWith('K') ? ['Parameters','Parameters'] : ['Readings','Readings'];
    document.title = labels[0] + ' · BSB-LAN';
    document.querySelectorAll('.site-nav a').forEach(a => { const target=new URL(a.href); if (target.origin === location.origin && target.pathname === location.pathname) a.setAttribute('aria-current','page'); });
    if (route === '') dashboard(base);
    else if (route === 'SD') storage(base);
    else enhanceLegacy(labels[1], route);
  });
  function storage(base) {
    document.title = 'SD card · BSB-LAN';
    const main = $('app-main'); main.replaceChildren();
    const title = node('h1','SD card');
    const intro = node('p','Manage removable storage. Stop SD logging before changing files or removing the card.','subtitle');
    const notice = node('p','Reading card status…','connection'); notice.setAttribute('role','status');
    const summary = node('p');
    const logging = node('p'); const settings = node('a','Configure logging'); settings.href=new URL('C',base);
    const tools = node('div',undefined,'refreshbar');
    const refresh = node('button','Refresh status'), mount = node('button','Mount card'), unmount = node('button','Safely unmount'), format = node('button','Format card');
    format.className = 'danger'; tools.append(refresh,mount,unmount,format);
    const files = node('div',undefined,'card-files');
    const foot = node('p','Lists up to 100 files in the card root with simple filenames. Downloads up to 1 MiB; use a card reader for larger files and folders. Formatting erases the entire card.','subtitle');
    main.append(title,intro,notice,summary,logging,settings,tools,files,foot);
    let status, busy = false, controller;
    const buttons = () => {
      refresh.disabled = busy;
      const locked = busy || !status || status.busy || !status.selected || !status.authorized;
      mount.disabled = locked || status.mounted; unmount.disabled = locked || !status.mounted; format.disabled = locked;
      files.querySelectorAll('[data-delete]').forEach(b => b.disabled = locked || b.dataset.protected === 'true');
    };
    const bytes = n => Number(n) < 1048576 ? (Number(n)/1024).toLocaleString(undefined,{maximumFractionDigits:1})+' KiB' : (Number(n)/1048576).toLocaleString(undefined,{maximumFractionDigits:1})+' MiB';
    async function request(path, options = {}) {
      controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 90000);
      try {
        const response = await fetch(new URL('SD/'+path,base),{...options,signal:controller.signal,cache:'no-store',credentials:'same-origin'});
        const data = await response.json();
        if (!response.ok || data.error) throw new Error(data.error || 'Storage request failed.');
        return data;
      } finally { clearTimeout(timer); }
    }
    function render() {
      summary.textContent = status.mounted ? `${bytes(status.used)} used of ${bytes(status.total)} · ${bytes(Math.max(0,status.total-status.used))} free` : 'No mounted card. Insert a card and choose Mount card. Format can prepare an unreadable filesystem, but erases all card data.';
      notice.textContent = status.busy ? 'Storage is in use. Stop SD logging, averages and telegram logging, and disable SD web serving before making changes.' : !status.selected ? 'Select SD card as the storage device in Settings before making changes.' : !status.authorized ? 'Configure web authentication before making changes.' : status.mounted ? 'Card mounted' : 'Card not mounted';
      logging.textContent = `Heating data logging: ${status.logging ? 'on' : 'off'} · interval ${status.interval ?? '—'} seconds. Storage actions are recorded in storage-audit.jsonl (two files, 256 KiB each).`;
      files.replaceChildren();
      if (!status.mounted) return;
      if (!status.files.length) { files.append(node('p','No manageable files in the card root.')); return; }
      const table = node('table'); const head = node('thead'), row = node('tr');
      ['File','Size','Actions'].forEach(label => { const h=node('th',label); h.scope='col'; row.append(h); }); head.append(row); table.append(head);
      const body = node('tbody');
      status.files.forEach(file => {
        const row=node('tr'), actions=node('td'), link=node('a','Download'), remove=node('button','Delete');
        link.href = new URL('SD/download/'+encodeURIComponent(file.name),base); link.download=file.name;
        remove.dataset.delete=''; remove.dataset.protected=String(!!file.protected); remove.title=file.protected ? 'Managed index or averages file; cannot be deleted separately.' : '';  remove.className='danger'; remove.addEventListener('click',()=>confirmAction('delete',file.name));
        actions.append(link,document.createTextNode(' '),remove); row.append(node('td',file.name),node('td',bytes(file.size)),actions); body.append(row);
      }); table.append(body); files.append(table);
      if (status.truncated) files.append(node('p','Showing the first 100 manageable files. Use a card reader for the full list.'));
    }
    async function load() {
      if (busy) return; busy=true; buttons(); notice.textContent='Reading card status…';
      try { status=await request('status'); render(); }
      catch(error) { status=undefined; notice.textContent='Unable to read card status. '+error.message; }
      finally { busy=false; buttons(); }
    }
    async function act(action,name='',confirmation='') {
      if (busy) return; busy=true; buttons(); notice.textContent=action === 'format' ? 'Formatting card… Keep power connected.' : 'Updating card…';
      let outcome;
      try { const result = await request('action',{method:'POST',headers:{'Content-Type':'text/plain'},body:[status.token,action,name,confirmation].join('\n')}); outcome= action === 'format' ? 'Card formatted successfully.' : 'Storage updated.'; if (result.audited === false) outcome += ' Audit entry could not be saved.'; }
      catch(error) { outcome=error.name === 'AbortError' ? 'Request timed out. The operation may still be running; refresh status before trying again.' : error.message; }
      finally { busy=false; await load(); notice.textContent=outcome+' '+notice.textContent; }
    }
    function confirmAction(action,name='') {
      const previous=document.activeElement, dialog=node('dialog'), heading=node('h2',action==='format'?'Format this SD card?':'Delete this file?');
      const description=node('p',action==='format'?'All files and folders on the removable card will be erased. Download anything you need first. This cannot be undone.':`Remove the contents of “${name}” permanently? Heating data logs are recreated with a fresh header and index.`);
      const label=node('label','Type FORMAT to confirm'), input=node('input'); input.autocomplete='off'; label.append(input);
      const cancel=node('button','Cancel'), confirm=node('button',action==='format'?'Erase and format':'Delete file'); confirm.className='danger';
      heading.id='storage-confirm-title'; dialog.setAttribute('aria-labelledby',heading.id); dialog.append(heading,description);
      if(action==='format') { dialog.append(label); confirm.disabled=true; input.addEventListener('input',()=>confirm.disabled=input.value !== 'FORMAT'); }
      const controls=node('div',undefined,'refreshbar'); controls.append(cancel,confirm); dialog.append(controls); document.body.append(dialog);
      cancel.addEventListener('click',()=>dialog.close());
      confirm.addEventListener('click',()=>{ dialog.close(); act(action,name,action==='format'?'FORMAT':'DELETE'); });
      dialog.addEventListener('close',()=>{ dialog.remove(); previous?.focus(); },{once:true});
      dialog.showModal(); cancel.focus();
    }
    refresh.addEventListener('click',load); mount.addEventListener('click',()=>act('mount')); unmount.addEventListener('click',()=>act('unmount')); format.addEventListener('click',()=>confirmAction('format'));
    window.addEventListener('pagehide',()=>controller?.abort(),{once:true}); buttons(); load();
  }
  function dashboard(base) {
    const main = $('app-main');
    const legacy = main.querySelector('.legacy-page');
    const help = node('details', undefined, 'help-disclosure');
    help.append(node('summary','About BSB-LAN and available functions')); help.append(legacy); main.append(help);
    const section = node('section'); section.setAttribute('aria-label','Heating overview'); main.prepend(section);
    const heading = node('div',undefined,'page-heading');
    const title = node('div'); title.append(node('h1','Your heating system'));
    const subtitle = node('p','Checking controller…','subtitle'); title.append(subtitle);
    const refreshbar = node('div',undefined,'refreshbar');
    const connection = node('span','Checking connection','connection'); connection.setAttribute('role','status');
    const last = node('span','Not updated yet','last-update');
    const refresh = node('button','Refresh'); refresh.type = 'button';
    const autoLabel = node('label'); const auto = node('input'); auto.type = 'checkbox';
    autoLabel.append(auto, document.createTextNode(' Auto refresh · 30 s'));
    refreshbar.append(connection,last,refresh,autoLabel); heading.append(title,refreshbar); section.append(heading);
    const strip = node('div',undefined,'temperature-strip'); const displays = new Map();
    const icons = {
      temp:'<path d="M10 27V8a6 6 0 0 1 12 0v19a10 10 0 1 1-12 0Z"/><path d="M16 12v20"/><circle cx="16" cy="34" r="3"/>',
      room:'<path d="M2 19 16 5l14 14M6 16v23h20V16M13 39V25h6v14"/>',
      water:'<path d="M4 18h24v8H16v11h-8V26H4ZM13 18V8h8M17 8V3M10 3h14"/>'
    };
    for (const [id,name] of [[8310,'Boiler temperature'],[8314,'Return temperature'],[8740,'Room temperature'],[8830,'Hot water']]) {
      const box = node('div',undefined,'temperature');
      const icon = document.createElementNS('http://www.w3.org/2000/svg','svg'); icon.setAttribute('viewBox','0 0 32 46'); icon.setAttribute('aria-hidden','true');
      icon.innerHTML = icons[id === 8740 ? 'room' : id === 8830 ? 'water' : 'temp']; // Constant trusted SVG only.
      const body = node('div'); const value = node('div','—','reading-value'); const note = node('div','Waiting for data','reading-note');
      body.append(node('div',name,'reading-name'),value,note); box.append(icon,body); strip.append(box); displays.set(id,{value,note});
    }
    section.append(strip);
    const sectionHeading = node('div',undefined,'section-heading'); sectionHeading.append(node('h2','Selected readings'));
    const region = node('div',undefined,'table-region'); region.setAttribute('tabindex','0'); region.setAttribute('aria-label','Selected readings table; scroll horizontally on small screens');
    const table = node('table'); const thead = node('thead'); const headRow = node('tr');
    ['Parameter','Reading','Value','State'].forEach(label => { const th = node('th',label); th.scope = 'col'; headRow.append(th); });
    thead.append(headRow); const tbody = node('tbody'); table.append(thead,tbody); region.append(table);
    let query = ''; const count = node('p','','result-count'); count.setAttribute('aria-live','polite');
    sectionHeading.append(searchControl(value => { query = value; render(); })); section.append(sectionHeading,region,count);
    const notice = node('div','Readings are read-only. Missing definitions will become available after loading the matching parameter file.','notice');
    const error = node('div','','notice error'); error.hidden = true; error.setAttribute('role','status'); section.append(error,notice);
    const supported = new Set(($('app-main').dataset.supported || '').split(',').filter(Boolean).map(Number));
    let data = {}, busy = false, stopped = false, controller, timer, failures = 0, stale = false;
    function render() {
      tbody.replaceChildren(); let visible = 0;
      for (const [id,name] of selected) {
        const r = reading(data[id],supported.has(id));
        if (!(`${id} ${name} ${r.value} ${r.state}`.toLowerCase().includes(query))) continue;
        visible++; const row = node('tr'); row.append(node('td',String(id)),node('td',name),node('td',r.value,'value-cell'),node('td',stale && data[id] ? 'Stale · '+r.state : r.state,'state '+(stale && data[id] ? 'stale' : r.kind))); tbody.append(row);
      }
      if (!visible) { const row = node('tr'); const cell = node('td','No matching readings. Clear the search to see all parameters.','empty-result'); cell.colSpan=4;row.append(cell);tbody.append(row); }
      count.textContent = visible + ' of ' + selected.length + ' readings';
      displays.forEach((display,id) => { const r = reading(data[id],supported.has(id)); display.value.textContent=r.value; display.note.textContent=stale && data[id] ? 'Stale reading' : r.state === 'Available' ? 'Read-only' : r.state; });
    }
    async function request(path) {
      const url = new URL(path,base); controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(),60000);
      try {
        const response = await fetch(url,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
        if (!response.ok) throw new Error(response.status === 401 ? 'Sign-in required. Reload this page to sign in.' : 'The adapter could not return the readings. Try Refresh.');
        return await response.json();
      } finally { clearTimeout(timeout); controller = null; }
    }
    function schedule() {
      clearTimeout(timer);
      if (auto.checked && failures < 3 && !document.hidden && !stopped) timer=setTimeout(update,30000);
    }
    async function update() {
      if (busy || stopped || document.hidden) return;
      busy=true; refresh.disabled=true; refresh.setAttribute('aria-busy','true'); connection.textContent='Updating…';error.hidden=true;
      try {
        const info = await request('JI'); if(stopped) return;
        const devices = Array.isArray(info.busdevices) ? info.busdevices : [];
        const boiler = devices.find(d=>Number(d.dev_id) === Number(info.busdest));
        const connected = boiler && Number(boiler.dev_fam)>0;
        subtitle.textContent=boiler ? boiler.dev_name + ' · '+info.bus : 'Boiler not detected · '+(info.bus || 'Bus');
        $('write-mode').textContent=Number(info.buswritable) === 0 ? 'Read-only' : 'Writes enabled';
        const ids = selected.map(r=>r[0]).filter(id=>supported.has(id));
        if(connected && ids.length) data=await request('JQ='+ids.join(','));
        else data={};
        if(stopped) return;
        failures=0;stale=false; connection.textContent=connected ? 'Controller detected' : 'Boiler not detected'; connection.classList.toggle('failed',!connected);
        last.textContent='Updated '+new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date());
        notice.textContent = ids.length < selected.length ? 'Device-specific parameter file pending. Some readings are not available yet.' : 'Read-only overview. Refresh reads the boiler; it does not change settings.';
      } catch(e) {
        if(stopped) return;
        failures++;stale=true;connection.textContent='Connection interrupted';connection.classList.add('failed');
        if(last.textContent === 'Not updated yet') subtitle.textContent='Controller status unavailable';
        error.textContent=e.name === 'AbortError' ? 'The adapter did not respond within 60 seconds. It may be busy generating a parameter list. Wait for that operation to finish, then select Refresh.' : e.message === 'Sign-in required. Reload this page to sign in.' ? e.message : 'Could not update readings. Check power and network connection, then select Refresh.';
        if(failures >= 3){auto.checked=false;error.textContent+=' Auto refresh paused after three failed attempts.';}
        error.hidden=false;
      } finally { busy=false;refresh.disabled=false;refresh.removeAttribute('aria-busy');render();schedule(); }
    }
    refresh.addEventListener('click',update); auto.addEventListener('change',schedule);
    document.addEventListener('visibilitychange',schedule);
    window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(timer);if(controller)controller.abort();});
    render();update();
  }
  function enhanceLegacy(title,route) {
    const main=$('app-main'), table=main.querySelector('.legacy-page');
    const heading=node('h1',title,'legacy-title'); main.prepend(heading);
    if(route === 'C') {
      const form=table.querySelector('form'); if(form) form.noValidate=true;
      const rows=[...table.querySelectorAll('tr')].filter(row=>row.cells.length >= 3 && row.querySelector('input,select'));
      if(rows.length) rows[0].closest('table').classList.add('settings-table');
      rows.forEach((row,index)=>{
        const label=row.cells[1].textContent.trim();
        row.querySelectorAll('input:not([type=submit]):not([type=button]),select').forEach((input,i)=>{
          if(!input.id)input.id='setting-'+index+'-'+i;
          if(!input.labels?.length)input.setAttribute('aria-label',label+(i ? ' '+(i+1) : ''));
          if(input.type==='password') {
            input.autocomplete='current-password'; const wrap=node('div',undefined,'field-secret');input.before(wrap);wrap.append(input);
            const reveal=node('button','Show');reveal.type='button';reveal.setAttribute('aria-label','Show '+label);reveal.setAttribute('aria-pressed','false');
            reveal.addEventListener('click',()=>{const show=input.type==='password';input.type=show?'text':'password';reveal.textContent=show?'Hide':'Show';reveal.setAttribute('aria-label',(show?'Hide ':'Show ')+label);reveal.setAttribute('aria-pressed',String(show));});wrap.append(reveal);
          }
        });
      });
    } else {
      const dataRows=[...table.querySelectorAll('tr')].filter(row=>!row.querySelector('tr') && row.textContent.trim());
      if(dataRows.length>3) {
        const toolbar=node('div',undefined,'legacy-toolbar');const status=node('span','','result-count');status.setAttribute('aria-live','polite');
        const filter=searchControl(q=>{let shown=0;dataRows.forEach(row=>{const match=row.textContent.toLowerCase().includes(q);row.hidden=!match;if(match)shown++;});status.textContent=shown+' of '+dataRows.length+' rows';});
        status.textContent=dataRows.length+' rows';toolbar.append(filter,status);heading.after(toolbar);
      }
    }
  }
})();
