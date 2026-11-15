(function(){
  'use strict';
  const APP_ID='com.webosbrew.panelcomfort';
  const APP_VERSION='0.3.20';
  const APP_DIR='/media/developer/apps/usr/palm/applications/'+APP_ID;
  const ROOT='/var/lib/webosbrew/panelcomfort';
  const HOOK='/var/lib/webosbrew/init.d/90-panelcomfort';
  const $=id=>document.getElementById(id);
  const fields=['enabled','dimMode','upMode','fadeMethod','fadeCurve','dimStart','dimDuration','undimStart','undimDuration','ambientLuxMin','ambientLuxMax','luxStability','ambientBrightnessOffset','minBrightness','maxBrightness','movieBrightnessEnabled','movieBrightness','eyeEnabled','eyeComfortMode','eyeLuxThreshold','eyeTiming','eyeStart','eyeEnd','eyeStartOffset','eyeEndOffset','latitude','longitude','sunsetOffset','sunriseOffset','profileProtectionEnabled','webUiEnabled','haApiEnabled','haApiPort','webhookEnabled','hyperhdrEnabled','hyperhdrHost','hyperhdrPort','hyperhdrToken','hyperhdrInstanceIds','hyperhdrMinBrightness','hyperhdrMaxBrightness','webhookHost'];
  let bootInstalled=false, overrideActive=false, rootAvailable=false, schedulerReady=false, busy=false, needsRootUpdate=false, rootScriptVersion='';
  let formDirty=false;
  let haServerRunning=false, ssdpRunning=false, tvLanIp='', haDeviceId='', webhookToken='', haBrightnessOffset=0;

  function say(text,kind){const n=$('notice');n.textContent=text;n.className='notice show'+(kind?' '+kind:'');}
  function setStatus(text,state){$('statusText').textContent=text;$('statusDot').className='status-dot'+(state?' '+state:'');}
  window.onerror=function(message,source,line,col,error){try{setStatus('PanelComfort UI error','bad');say('The interface hit an error: '+String(message)+' (line '+line+'). Use Refresh or the service repair action; your saved configuration is not changed by this error.','error');}catch(_){}return false;};
  window.addEventListener('unhandledrejection',function(event){try{const reason=event&&event.reason;const message=reason&&reason.message?reason.message:String(reason||'Unknown async error');say('An action failed: '+message,'error');}catch(_){} });
  function disableActions(disabled){
    $('applyBtn').disabled=disabled||!schedulerReady;
    document.querySelectorAll('[data-save]').forEach(b=>b.disabled=disabled||!schedulerReady);
    $('overrideBtn').disabled=disabled||!schedulerReady;
    // Recovery must stay available even when the initial root-service check fails.
    $('bootBtn').disabled=disabled;
    $('removeBtn').disabled=disabled||!rootAvailable||!bootInstalled;
    $('refreshBtn').disabled=disabled;
    $('hyperhdrTestBtn').disabled=disabled||!rootAvailable||!schedulerReady;
    $('detectLocationBtn').disabled=disabled;
    $('webhookRotateBtn').disabled=disabled||!rootAvailable||!schedulerReady;
  }
  function lunaExec(command,timeoutMs){
    timeoutMs=Number(timeoutMs)||12000;
    return new Promise((resolve,reject)=>{
      if(typeof PalmServiceBridge==='undefined'){reject(new Error('PalmServiceBridge is unavailable in this app runtime.'));return;}
      const bridge=new PalmServiceBridge();let done=false,timer=0;
      const marker='PANELCOMFORT_COMMAND_EXIT=';
      const wrapped='( '+command+' ); __pc_rc=$?; printf "\\n'+marker+'%s\\n" "$__pc_rc"';
      bridge.onservicecallback=function(message){
        if(done)return;done=true;if(timer)window.clearTimeout(timer);
        try{
          const r=typeof message==='string'?JSON.parse(message):message;
          if(r&&(r.returnValue===false||r.error)){reject(new Error(r.errorText||r.error||'Root command failed'));return;}
          const raw=String(r&&(r.stdoutString!==undefined?r.stdoutString:r.stdout)||'');
          const match=raw.match(/(?:\\r?\\n)?PANELCOMFORT_COMMAND_EXIT=(\\d+)\\s*$/);
          if(match){
            const code=Number(match[1]);
            const cleaned=raw.replace(/(?:\\r?\\n)?PANELCOMFORT_COMMAND_EXIT=\\d+\\s*$/,'');
            if(r.stdoutString!==undefined)r.stdoutString=cleaned;else r.stdout=cleaned;
            r.panelcomfortExitCode=code;
            if(code!==0){const stderr=String(r.stderrString||r.stderr||'').trim();const detail=stderr||cleaned.trim().split(/\\r?\\n/).slice(-5).join(' | ');reject(new Error('Root command failed (exit '+code+')'+(detail?': '+detail.slice(-500):'.')));return;}
          }
          resolve(r||{});
        }catch(e){reject(new Error('Could not read root-service response: '+String(message)));}
      };
      try{bridge.call('luna://org.webosbrew.hbchannel.service/exec',JSON.stringify({command:wrapped}));}
      catch(e){done=true;reject(e);return;}
      timer=window.setTimeout(()=>{if(!done){done=true;reject(new Error('Root command timed out after '+Math.round(timeoutMs/1000)+' seconds. Check Homebrew Channel root access and the TV service.'));}},timeoutMs);
    });
  }
  function stdout(r){return String(r.stdoutString||r.stdout||'');}
  function setFormValue(id,value){if($(id)&&value!==undefined&&value!==null&&String(value)!=='')$(id).value=String(value);}
  function updateFormDirty(){const el=$('formState');if(el){el.hidden=!formDirty;el.textContent=formDirty?'Unsaved settings — Save & apply to keep changes':'Saved';}}
  function markFormDirty(){if(busy)return;formDirty=true;updateFormDirty();}
  function parseDuration(raw,allowNegative=false){
    const match=String(raw==null?'':raw).trim().match(/^(-)?(\d{1,3}):([0-5]\d)$/);
    if(!match)return null;
    const minutes=Number(match[2])*60+Number(match[3]);
    if(minutes>720)return null;
    if(match[1]&&!allowNegative)return null;
    return match[1]?-minutes:minutes;
  }
  function formatDuration(minutes,allowNegative=false){
    let n=Number(minutes);if(!Number.isFinite(n))n=0;n=Math.round(n);
    const negative=n<0;n=Math.abs(n);const h=Math.floor(n/60),m=n%60;
    return (negative&&allowNegative?'-':'')+h+':'+String(m).padStart(2,'0');
  }
  function protectDurationInput(inputId,allowNegative){
    const el=$(inputId);if(!el)return;
    el.addEventListener('keydown',e=>{
      if(e.key!=='Backspace'&&e.key!=='Delete')return;
      const value=el.value,start=el.selectionStart,end=el.selectionEnd,colon=value.indexOf(':');
      if(colon<0||start!==end)return;
      if(e.key==='Backspace'&&start===colon+1&&colon>0){e.preventDefault();const left=value.slice(0,colon);const nextLeft=left.length<=1?'0':left.slice(0,-1);el.value=nextLeft+value.slice(colon);el.setSelectionRange(nextLeft.length,nextLeft.length);}
      else if(e.key==='Delete'&&start===colon&&colon<value.length-1){e.preventDefault();el.value=value.slice(0,colon+1)+'0'+value.slice(colon+2);el.setSelectionRange(colon+2,colon+2);}
    });
    el.addEventListener('blur',()=>{
      const value=String(el.value||'').trim();if(value.indexOf(':')>=0)return;
      const neg=allowNegative&&value.charAt(0)==='-';const digits=value.replace(/[^0-9]/g,'');if(!digits)return;
      const padded=digits.length<=2?digits.padStart(2,'0'):' '+digits;
      const clean=padded.trim();const hours=clean.length>2?clean.slice(0,-2).replace(/^0+(?=\d)/,''):'0';const minutes=clean.slice(-2).padStart(2,'0');el.value=(neg?'-':'')+hours+':'+minutes;
    });
  }
  function readableDuration(minutes){const n=Math.max(0,Number(minutes)||0);if(n===0)return 'instantly';const h=Math.floor(n/60),m=n%60;return h?(m?h+' h '+m+' min':h+' h'):m+' min';}
  function parseStatus(out){
    const parsed={};out.split(/\r?\n/).forEach(line=>{const i=line.indexOf('=');if(i>0)parsed[line.slice(0,i).trim()]=line.slice(i+1).trim();});
    if(parsed.CONFIG_PRESENT==='1'){
      // Polling refreshes live status every minute. Never replace unsaved user edits
      // with the saved config while the form is dirty.
      if(!formDirty){
        $('enabled').checked=parsed.ENABLED==='1';
        const map={dimMode:'DIM_MODE',upMode:'UP_MODE',fadeMethod:'FADE_METHOD',fadeCurve:'FADE_CURVE',dimStart:'DIM_START',dimDuration:'DIM_DURATION',undimStart:'UNDIM_START',undimDuration:'UNDIM_DURATION',ambientLuxMin:'AMBIENT_LUX_MIN',ambientLuxMax:'AMBIENT_LUX_MAX',luxStability:'LUX_STABILITY',ambientBrightnessOffset:'AMBIENT_BRIGHTNESS_OFFSET',minBrightness:'MIN_BRIGHTNESS',maxBrightness:'MAX_BRIGHTNESS',movieBrightness:'MOVIE_BRIGHTNESS',eyeComfortMode:'HA_EYE_COMFORT_OVERRIDE',eyeLuxThreshold:'EYE_LUX_THRESHOLD',eyeTiming:'EYE_TIMING',eyeStart:'EYE_START',eyeEnd:'EYE_END',eyeStartOffset:'EYE_START_OFFSET',eyeEndOffset:'EYE_END_OFFSET',latitude:'SUNSET_LAT',longitude:'SUNSET_LON',sunsetOffset:'SUNSET_OFFSET',sunriseOffset:'SUNRISE_OFFSET',haApiPort:'HA_API_PORT',hyperhdrHost:'HYPERHDR_HOST',hyperhdrPort:'HYPERHDR_PORT',hyperhdrToken:'HYPERHDR_TOKEN',hyperhdrInstanceIds:'HYPERHDR_INSTANCE_IDS',hyperhdrMinBrightness:'HYPERHDR_MIN_BRIGHTNESS',hyperhdrMaxBrightness:'HYPERHDR_MAX_BRIGHTNESS'};
        Object.keys(map).forEach(id=>{if(parsed[map[id]]!==undefined){if(id==='latitude'||id==='longitude')$(id).value=parsed[map[id]];else if(['dimDuration','undimDuration'].includes(id))setFormValue(id,formatDuration(parsed[map[id]],false));else if(['eyeStartOffset','eyeEndOffset'].includes(id))setFormValue(id,formatDuration(parsed[map[id]],true));else setFormValue(id,parsed[map[id]]);}});
        if(parsed.HYPERHDR_INSTANCE_IDS!==undefined&&$('hyperhdrInstanceIdsManual'))$('hyperhdrInstanceIdsManual').value=parsed.HYPERHDR_INSTANCE_IDS;
        $('eyeEnabled').checked=parsed.EYE_ENABLED==='1';
        if(!parsed.HA_EYE_COMFORT_OVERRIDE||parsed.HA_EYE_COMFORT_OVERRIDE==='auto')$('eyeComfortMode').value='dynamic';
        $('movieBrightnessEnabled').checked=parsed.MOVIE_BRIGHTNESS_ENABLED==='1';
        $('profileProtectionEnabled').checked=parsed.PROFILE_PROTECTION_ENABLED!=='0';
        $('webUiEnabled').checked=parsed.WEB_UI_ENABLED==='1';
        $('haApiEnabled').checked=parsed.HA_API_ENABLED==='1';
        $('webhookEnabled').checked=parsed.WEBHOOK_ENABLED==='1';
        $('hyperhdrEnabled').checked=parsed.HYPERHDR_ENABLED==='1';
        if(parsed.WEBHOOK_HOST!==undefined)setFormValue('webhookHost',parsed.WEBHOOK_HOST);
      }
      haDeviceId=parsed.HA_DEVICE_ID||'';webhookToken=parsed.WEBHOOK_TOKEN||'';haBrightnessOffset=Number(parsed.HA_BRIGHTNESS_OFFSET||0);if(!Number.isFinite(haBrightnessOffset))haBrightnessOffset=0;
      $('haDeviceId').value=haDeviceId||'Generated when boot service is installed';
    }
    bootInstalled=parsed.BOOT_INSTALLED==='1';overrideActive=parsed.OVERRIDE_ACTIVE==='1';haServerRunning=parsed.HTTPD_RUNNING==='1'||parsed.HA_API_RUNNING==='1';ssdpRunning=parsed.SSDP_RUNNING==='1';tvLanIp=parsed.TV_LAN_IP||'';rootScriptVersion=parsed.ROOT_SCRIPT_VERSION||'unknown';needsRootUpdate=rootScriptVersion!==APP_VERSION||parsed.ROOT_SCRIPTS_OK==='0';if(!formDirty&&$('webhookHost')){if(parsed.WEBHOOK_HOST)$('webhookHost').value=parsed.WEBHOOK_HOST;else if(tvLanIp)$('webhookHost').value=tvLanIp;}
    schedulerReady=parsed.CONFIG_PRESENT==='1';rootAvailable=true;updateLiveSummary(parsed);
    // Keep repair/update visible when the service version is old; only hide it when current.
    $('bootBtn').classList.toggle('hidden',bootInstalled&&!needsRootUpdate);
    $('removeBtn').classList.toggle('hidden',!bootInstalled);
    $('bootBtn').textContent=bootInstalled?'Repair / update service':'Install boot service';
    $('bootTitle').textContent=bootInstalled?(needsRootUpdate?(parsed.ROOT_SCRIPTS_OK==='0'?'Service repair required':'Service update required'):'Boot service installed'):'Run automatically';
    $('bootDescription').textContent=bootInstalled?(needsRootUpdate?(parsed.ROOT_SCRIPTS_OK==='0'?'An installed service file is missing or not executable. Use Repair / update service to restore the TV scheduler and listener.':'TV scheduler scripts are at version '+rootScriptVersion+'. Use Repair / update service to install '+APP_VERSION+'.'):'The root startup hook is present. Your schedule applies even while the app is closed.'):'Install the root startup hook once. Settings stay on the TV and apply even when the app is closed.';
    updateOverrideUI();updateRanges();updateScheduleUI();updateHAUI();updateWebhookUI();updateProfileProtectionUI(parsed);
    if(parsed.RUNNING==='1')setStatus('Root service running','ok');else if(bootInstalled)setStatus('Boot hook installed · service idle','');else setStatus('Root access ready · setup needed','');
  }
  function statusValues(out){
    const values={};out.split(/\r?\n/).forEach(line=>{const i=line.indexOf('=');if(i>0)values[line.slice(0,i).trim()]=line.slice(i+1).trim();});return values;
  }
  function needsServiceRecovery(out){
    const s=statusValues(out);
    if(s.CONFIG_PRESENT!=='1'||s.BOOT_INSTALLED!=='1'||s.ROOT_SCRIPT_VERSION!==APP_VERSION||s.ROOT_SCRIPTS_OK==='0')return false;
    const schedulerStopped=s.ENABLED==='1'&&s.RUNNING!=='1';
    return schedulerStopped||s.HTTPD_RUNNING!=='1';
  }
  async function refresh(options){
    options=options||{};
    try{
      setStatus('Checking TV service…','');
      // Status inspection is read-only; app-open recovery only runs the already-installed start script.
      const cmd='echo PC_STATUS_OK=1; echo ROOT_SCRIPT_VERSION=$(cat '+ROOT+'/service-version 2>/dev/null || echo missing); root_scripts_ok=1; for f in daemon.sh apply-queue.sh start.sh ha-server.sh panelcomfort-httpd.js ssdp-broadcast.sh hyperhdr.sh hyperhdr-retry.sh picture-watch.sh panelcomfort.cgi panelcomfort-ha.cgi panelcomfort-discovery.cgi panelcomfort-web.cgi panelcomfort-health.cgi default.env install-root.sh remove-root.sh update-root.sh; do [ -r '+ROOT+'/$f ] || root_scripts_ok=0; done; for f in daemon.sh apply-queue.sh start.sh ha-server.sh panelcomfort-httpd.js ssdp-broadcast.sh hyperhdr.sh hyperhdr-retry.sh picture-watch.sh panelcomfort.cgi panelcomfort-ha.cgi panelcomfort-discovery.cgi panelcomfort-web.cgi panelcomfort-health.cgi install-root.sh remove-root.sh update-root.sh; do [ -x '+ROOT+'/$f ] || root_scripts_ok=0; done; echo ROOT_SCRIPTS_OK=$root_scripts_ok; if [ -f '+ROOT+'/config.env ]; then echo CONFIG_PRESENT=1; cat '+ROOT+'/config.env; fi; [ -f '+HOOK+' ] && echo BOOT_INSTALLED=1 || echo BOOT_INSTALLED=0; [ -f '+ROOT+'/override.flag ] && echo OVERRIDE_ACTIVE=1 || echo OVERRIDE_ACTIVE=0; if [ -f '+ROOT+'/pid ] && kill -0 "$(cat '+ROOT+'/pid)" 2>/dev/null; then echo RUNNING=1; else echo RUNNING=0; fi; if [ -f '+ROOT+'/picture-watch.pid ] && kill -0 "$(cat '+ROOT+'/picture-watch.pid)" 2>/dev/null; then echo PROFILE_WATCHER_RUNNING=1; else echo PROFILE_WATCHER_RUNNING=0; fi; [ -r '+ROOT+'/profile-status ] && printf "PROFILE_CONTEXT=%s\\n" "$(cat '+ROOT+'/profile-status)"; if [ -x '+ROOT+'/ha-server.sh ]; then sh '+ROOT+'/ha-server.sh status; else echo HA_API_RUNNING=0; echo HTTPD_RUNNING=0; echo SSDP_RUNNING=0; fi; echo CURRENT_TIME=$(date +%H:%M:%S); echo CURRENT_DATE=$(date +%Y-%m-%d); if command -v timeout >/dev/null 2>&1; then set -- $(timeout 5 sh '+ROOT+'/daemon.sh --calculate 2>/dev/null || echo "0 off unavailable 0"); else set -- $(sh '+ROOT+'/daemon.sh --calculate 2>/dev/null || echo "0 off unavailable 0"); fi; echo CURRENT_BACKLIGHT=$1; echo CURRENT_EYE=$2; echo CURRENT_PHASE=$3; echo CURRENT_HYPERHDR=$4; echo CURRENT_NEXT=$(date +%H:%M)';
      async function readStatus(){const r=await lunaExec(cmd);const out=stdout(r);if(!/PC_STATUS_OK=1/.test(out))throw new Error('The root command returned no valid status response.');return out;}
      let out=await readStatus();parseStatus(out);
      if(options.recover&&needsServiceRecovery(out)){
        setStatus('Starting TV services…','');say('PanelComfort is installed but its scheduler or local control listener is stopped. Trying to start it now…','');
        try{
          await lunaExec('if [ -x '+ROOT+'/start.sh ]; then '+ROOT+'/start.sh; else echo "PanelComfort start script is missing" >&2; exit 1; fi',25000);
          const recoveredOut=await readStatus();out=recoveredOut;parseStatus(out);
          if(needsServiceRecovery(out)){setStatus('TV service still stopped','bad');say('PanelComfort could not confirm that all enabled services restarted. Check Homebrew root access, then use Refresh or Repair / update service.','error');}
          else say('PanelComfort detected a stopped service and restarted it. Settings and Home Assistant / webhook endpoints are available again.','good');
        }catch(recoveryError){setStatus('Service recovery failed','bad');say('PanelComfort detected a stopped service but could not restart it: '+recoveryError.message+'. Check that Homebrew root access is available, then use Repair / update service.','error');}
      }
      disableActions(false);
      if(!outHasConfig(out))say('Root access works. Install the boot service once to add the scheduler and startup hook.','good');
    }catch(e){rootAvailable=false;schedulerReady=false;needsRootUpdate=true;disableActions(false);$('refreshBtn').disabled=false;$('bootBtn').classList.remove('hidden');$('bootBtn').textContent='Repair / reinstall service';$('bootTitle').textContent='TV service check failed';$('bootDescription').textContent='The status check did not complete. Try Refresh or attempt service repair / reinstall.';setStatus('TV service check failed','bad');say('Could not read PanelComfort service status: '+e.message+'. The repair button remains available.','error');}
  }
  function outHasConfig(out){return /CONFIG_PRESENT=1/.test(out);}
  function mapMovieHyperHdrTarget(tvTarget,tvMin,tvMax,hdrMin,hdrMax){
    const tvRange=tvMax-tvMin;if(tvRange<=0)return tvTarget>=tvMax?hdrMax:hdrMin;
    const position=Math.max(0,Math.min(1,(tvTarget-tvMin)/tvRange));
    return Math.round(hdrMin+(hdrMax-hdrMin)*position);
  }
  function updateRanges(){
    $('minOut').value=$('minBrightness').value;$('minOut').textContent=$('minBrightness').value;
    $('maxOut').value=$('maxBrightness').value;$('maxOut').textContent=$('maxBrightness').value;
    $('movieBrightnessOut').value=$('movieBrightness').value+'%';$('movieBrightnessOut').textContent=$('movieBrightness').value+'%';$('movieBrightness').disabled=!$('movieBrightnessEnabled').checked;
    const min=Number($('minBrightness').value),max=Number($('maxBrightness').value);
    $('previewTitle').textContent=min+'% at night · '+max+'% daytime';$('previewMeterFill').style.width=max+'%';
    const hmin=Number($('hyperhdrMinBrightness').value),hmax=Number($('hyperhdrMaxBrightness').value);
    $('hyperhdrMinOut').value=hmin+'%';$('hyperhdrMinOut').textContent=hmin+'%';$('hyperhdrMaxOut').value=hmax+'%';$('hyperhdrMaxOut').textContent=hmax+'%';
    const customMovie=$('movieBrightnessEnabled').checked,movieTvTarget=customMovie?Number($('movieBrightness').value):Number($('maxBrightness').value);
    const movieHdrTarget=customMovie?mapMovieHyperHdrTarget(movieTvTarget,min,max,hmin,hmax):hmax;
    $('hyperhdrPreviewTitle').textContent=hmin+'% at night · '+hmax+'% day · movie TV '+movieTvTarget+'% / LEDs '+movieHdrTarget+'%';$('hyperhdrPreviewMeterFill').style.width=movieHdrTarget+'%';
    $('hyperhdrTestBtn').disabled=!rootAvailable||!schedulerReady||busy;updateScheduleUI();
  }
  function updateScheduleUI(){
    const sunset=$('dimMode').value==='sunset',sunrise=$('upMode').value==='sunrise';
    $('dimTimeWrap').classList.toggle('hidden',sunset);$('sunsetOffsetWrap').classList.toggle('hidden',!sunset);
    $('upTimeWrap').classList.toggle('hidden',sunrise);$('sunriseOffsetWrap').classList.toggle('hidden',!sunrise);
    $('solarLocationCard').classList.remove('hidden');
    const eyeOn=$('eyeEnabled').checked,linked=$('eyeTiming').value==='linked';
    $('eyeLinkedFields').classList.toggle('hidden',!linked);$('eyeCustomFields').classList.toggle('hidden',linked);
    $('eyeLinkedFields').style.opacity=eyeOn?'1':'.45';$('eyeCustomFields').style.opacity=eyeOn?'1':'.45';
    const start=sunset?'sunset '+signedOffset($('sunsetOffset').value):$('dimStart').value;
    const morning=sunrise?'sunrise '+signedOffset($('sunriseOffset').value):$('undimStart').value;
    const duration=parseDuration($('dimDuration').value,false),solar=$('fadeMethod').value==='solar',ambient=$('fadeMethod').value==='ambient',tvSensor=$('fadeMethod').value==='tv-sensor';
    $('durationControls').classList.toggle('hidden',solar);$('fadeCurveWrap').classList.remove('hidden');const needsLocation=sunset||sunrise||solar;$('locationHint').classList.toggle('hidden',!needsLocation);
    $('ambientLuxControls').classList.toggle('hidden',!ambient);
    $('previewText').textContent=solar?'Brightness follows calculated solar elevation from your coordinates; fixed fade durations are bypassed.':ambient?'Fresh room lux maps from '+$('ambientLuxMin').value+' to '+$('ambientLuxMax').value+' lx across the configured screen and LED limits, with a '+Number($('ambientBrightnessOffset').value||0)+' point offset. The evening and morning triggers are only fallback if sensor data is missing or stale.':tvSensor?'Brightness follows the TV\'s own luminance sensor if this model exposes it. If unavailable, the timed schedule is used.':'Evening: '+start+' · '+$('fadeCurve').selectedOptions[0].text.toLowerCase()+' fade '+(duration===null?'(enter H:MM)':readableDuration(duration))+'. Morning starts at '+morning+'.';
    $('timelineMode').textContent=solar?'Solar elevation':ambient?'Ambient illuminance':tvSensor?'TV luminance':'Time-based';updateCurvePreview();updateTimeline();
    $('overrideBtn').disabled=!rootAvailable||!schedulerReady||busy;
  }
  function signedOffset(raw){const n=Number(raw);if(n===0)return 'at';return Math.abs(n)+' min '+(n<0?'before':'after');}
  function updateOverrideUI(){
    $('overrideBtn').classList.toggle('active',overrideActive);$('overrideLabel').textContent=overrideActive?'Exit movie override':'Movie override';
    const customMovie=$('movieBrightnessEnabled').checked,tvTarget=customMovie?Number($('movieBrightness').value):Number($('maxBrightness').value);
    const hdrTarget=customMovie?mapMovieHyperHdrTarget(tvTarget,Number($('minBrightness').value),Number($('maxBrightness').value),Number($('hyperhdrMinBrightness').value),Number($('hyperhdrMaxBrightness').value)):Number($('hyperhdrMaxBrightness').value);
    const movieTarget=customMovie?'TV '+tvTarget+'% · HyperHDR '+hdrTarget+'% (mapped to each configured range)':'daytime targets (TV '+tvTarget+'% · HyperHDR '+hdrTarget+'%)';
    const eyeMovieTarget=$('eyeComfortMode').value==='on'?'forced Eye Comfort on':'Eye Comfort off';
    $('overrideHint').textContent=overrideActive?'Schedule will resume when exited':movieTarget+' · '+eyeMovieTarget;
    $('modeHeadline').textContent=overrideActive?'Movie override is active':'Your picture, on a schedule';
    $('modeDescription').textContent=overrideActive?'The '+movieTarget+' is applied and '+eyeMovieTarget.toLowerCase()+' until you resume the schedule.':'PanelComfort gradually dims your TV, optionally dims HyperHDR, and can follow sunrise and sunset.';
  }
  function updateHAUI(){
    const enabled=$('haApiEnabled').checked;$('haTvIp').value=tvLanIp||'Could not detect';$('haDeviceId').value=haDeviceId||'Generated when boot service is installed';
    const badge=$('haApiBadge');badge.classList.toggle('neutral',!(enabled&&haServerRunning));
    badge.textContent=!enabled?'Disabled':haServerRunning?'Listening':'Not listening';
    $('haApiStatus').textContent=!enabled?'Enable this to announce the TV to Home Assistant.':haServerRunning?(ssdpRunning?'LAN API running · discovery announcement active':'LAN API running · SSDP announcement unavailable'):'Save & apply to start the LAN API and discovery announcement.';
    const port=String($('haApiPort').value||8765),host=tvLanIp||$('haTvIp').value,webEnabled=$('webUiEnabled').checked; $('haApiAddress').textContent='Port '+port;const webUrl=webEnabled&&host&&host!=='Could not detect'?'http://'+host+':'+port+'/':'';$('openWebInterface').href=webUrl||'#';$('webInterfaceAddress').textContent=!webEnabled?'Dashboard disabled. Enable it and Save & apply.':(webUrl||'TV address not detected; refresh status first.');$('openWebInterface').setAttribute('aria-disabled',webUrl?'false':'true');const healthUrl=host&&host!=='Could not detect'?'http://'+host+':'+port+'/cgi-bin/panelcomfort-health.cgi':'';if($('haHealthUrl'))$('haHealthUrl').value=healthUrl||'TV address not detected';
  }
  function updateWebhookUI(){
    const enabled=$('webhookEnabled').checked,port=String($('haApiPort').value||'8765'),host=String(($('webhookHost')&&$('webhookHost').value)||tvLanIp||'').trim();
    const base=(enabled&&host&&/^[a-zA-Z0-9.-]+$/.test(host)&&/^[a-fA-F0-9]{8}$/.test(webhookToken)&&/^\d+$/.test(port))?'http://'+host+':'+port+'/cgi-bin/pc-'+webhookToken:'';
    const help=base?'Links are generated. '+(haServerRunning?'Listener is running.':'Listener is not currently confirmed as running; these links will not respond until the local HTTP listener starts.')+' Treat these URLs as passwords.':'Enable webhooks, install the boot service, and ensure the TV IP and webhook secret are available.';
    $('webhookOnUrl').value=base?base+'?movie=on':'URL unavailable — refresh TV status';$('webhookOffUrl').value=base?base+'?movie=off':'URL unavailable — refresh TV status';$('webhookToggleUrl').value=base?base+'?movie=toggle':'URL unavailable — refresh TV status';$('webhookStatusUrl').value=base?base+'?action=status':'URL unavailable — refresh TV status';$('webhookAmbientUrl').value=base?base+'?ambient_lux=0':'URL unavailable — refresh TV status';
    document.querySelectorAll('.copy-webhook').forEach(b=>b.disabled=!base);
    const badge=$('webhookBadge');badge.textContent=!enabled?'Disabled':haServerRunning?'Enabled':base?'Links ready · listener check needed':'Enabled · URL unavailable';badge.classList.toggle('neutral',!enabled||!haServerRunning);
    $('webhookUrlStatus').textContent=!enabled?'Disabled':haServerRunning?'Ready to use':base?'URLs generated; listener not confirmed':'Waiting for TV IP / secret';$('webhookUrlHelp').textContent=help;
    if(enabled)$('webhookDetails').open=true;
  }
  function updateLiveSummary(parsed){
    const now=parsed.CURRENT_TIME||new Date().toLocaleTimeString();$('liveTime').textContent=now;$('liveDate').textContent=parsed.CURRENT_DATE||'TV local time';$('statusChipTime').title='TV local time · '+$('liveDate').textContent;
    const bri=parsed.CURRENT_BACKLIGHT;$('liveBrightness').textContent=(bri!==undefined&&/^\d+$/.test(bri)?bri:'--')+'%';
    const phase=String(parsed.CURRENT_PHASE||'unknown').replace(/-/g,' ');$('livePhase').textContent=phase.charAt(0).toUpperCase()+phase.slice(1);
    $('liveEye').textContent='Eye Comfort: '+(parsed.CURRENT_EYE==='on'?'on':parsed.CURRENT_EYE==='off'?'off':'unknown');$('statusChipPhase').title='Current phase: '+$('livePhase').textContent+' · '+$('liveEye').textContent;
    const dim=$('dimMode').value==='sunset'?'sunset '+signedOffset($('sunsetOffset').value):$('dimStart').value;
    const up=$('upMode').value==='sunrise'?'sunrise '+signedOffset($('sunriseOffset').value):$('undimStart').value;
    let next='—',detail='No scheduled transition';
    const fadeMethod=$('fadeMethod').value;
    if(overrideActive){next='Movie override';detail='Schedule paused until you exit override';}
    else if(phase==='evening fade'){next='Night level';detail='Fade toward '+$('minBrightness').value+'%';}
    else if(phase==='morning fade'){next='Day level';detail='Fade toward '+$('maxBrightness').value+'%';}
    else if(phase==='solar fade'){next='Solar curve active';detail='Target follows current solar elevation; there is no fixed fade end time';}
    else if(phase==='ambient response'){next='Ambient sensor update';detail='Lux mapping and Ambient Brightness Offset update both TV and HyperHDR targets';}
    else if(fadeMethod==='solar'&&phase==='day'){next='Sun elevation +4°';detail='Dimming begins as the sun drops below about +4°';}
    else if(fadeMethod==='solar'&&phase==='night'){next='Sun elevation −8°';detail='Brightness rises as the sun climbs above about −8°';}
    else if(phase==='night'){next=up;detail='Morning brightness transition';}
    else {next=dim;detail='Evening brightness transition';}
    $('liveNext').textContent=next;$('liveNextDetail').textContent=detail;$('statusChipNext').title='Next transition: '+next+' · '+detail;
  }
  function curveProgress(t,curve){t=Math.max(0,Math.min(1,t));if(curve==='easein')return t*t;if(curve==='easeout')return 1-(1-t)*(1-t);if(curve==='smooth')return t*t*(3-2*t);if(curve==='smootherstep')return t*t*t*(t*(t*6-15)+10);if(curve==='twilight')return 0.5-0.5*Math.cos(Math.PI*t);if(curve==='rolloff-soft')return Math.log1p(4*t)/Math.log(5);if(curve==='rolloff')return Math.log1p(9*t)/Math.log(10);if(curve==='rolloff-strong')return Math.log1p(19*t)/Math.log(20);if(curve==='exponential')return (Math.exp(4*t)-1)/(Math.exp(4)-1);if(curve==='gamma-late')return Math.pow(t,2.2);if(curve==='gamma-early')return Math.pow(t,0.4545454545);return t;}
  function updateCurvePreview(){const curve=$('fadeCurve').value,points=[];for(let i=0;i<=50;i++){const t=i/50,x=18+268*t,y=12+58*curveProgress(t,curve);points.push((i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1));}$('curvePreviewPath').setAttribute('d',points.join(' '));$('curvePreviewCaption').textContent='Sunset: day → night · '+$('fadeCurve').selectedOptions[0].text;}
  function updateTimeline(){
    const mode=$('fadeMethod').value,solar=mode==='solar',ambient=mode==='ambient',tvSensor=mode==='tv-sensor',sensorBased=ambient||tvSensor,curve=$('fadeCurve').value,low=Number($('minBrightness').value),high=Number($('maxBrightness').value);
    const start=parseClock($('dimStart').value),duration=parseDuration($('dimDuration').value,false)||0,morning=parseClock($('undimStart').value),upDuration=parseDuration($('undimDuration').value,false)||0;
    const points=[];const x0=32,x1=608,yTop=28,yBottom=108;
    const now=new Date(),latitude=Number($('latitude').value),longitude=Number($('longitude').value);
    const dayOfYear=Math.floor((now-new Date(now.getFullYear(),0,0))/86400000),tzMinutesEast=-now.getTimezoneOffset();
    function shape(t){return curveProgress(t,curve);}
    function solarElevation(minute){
      if(!Number.isFinite(latitude)||Math.abs(latitude)>89||!Number.isFinite(longitude)||Math.abs(longitude)>180)return null;
      const b=2*Math.PI*(dayOfYear-81)/364,eot=9.87*Math.sin(2*b)-7.53*Math.cos(b)-1.5*Math.sin(b);
      const decl=23.44*Math.sin(2*Math.PI*(284+dayOfYear)/365)*Math.PI/180;
      const solarMinutes=(minute%1440)+eot+4*longitude-tzMinutesEast;
      const hourAngle=(solarMinutes/4-180)*Math.PI/180,latRad=latitude*Math.PI/180;
      let sinAlt=Math.sin(latRad)*Math.sin(decl)+Math.cos(latRad)*Math.cos(decl)*Math.cos(hourAngle);
      sinAlt=Math.max(-1,Math.min(1,sinAlt));return Math.asin(sinAlt)*180/Math.PI;
    }
    function valueAt(minute){
      if(solar){const altitude=solarElevation(minute);if(altitude===null){const t=minute/1440;return low+(high-low)*(0.5-0.5*Math.cos(2*Math.PI*t));}let progress=altitude>=4?0:altitude<=-8?1:(4-altitude)/12;return high-(high-low)*shape(progress);}
      if(sensorBased){const x=minute/1440,lux=Math.pow(1001,x)-1;let progress=(Math.log(lux+1)-Math.log(6))/(Math.log(501)-Math.log(6));progress=Math.max(0,Math.min(1,progress));return low+(high-low)*shape(progress);}
      const elapsedFromEvening=(minute-start+1440)%1440;
      const nightLength=(morning-start+1440)%1440;
      if(duration>0&&elapsedFromEvening<duration)return high-(high-low)*shape(elapsedFromEvening/duration);
      if(duration===0&&elapsedFromEvening<nightLength)return low;
      if(elapsedFromEvening>=duration&&elapsedFromEvening<nightLength)return low;
      const elapsedFromMorning=(minute-morning+1440)%1440;
      if(upDuration>0&&elapsedFromMorning<upDuration)return low+(high-low)*shape(elapsedFromMorning/upDuration);
      return high;
    }
    for(let i=0;i<=120;i++){const m=i*12;const x=x0+(x1-x0)*i/120;const val=valueAt(m);const y=yBottom-(Math.max(0,Math.min(100,val))/100)*(yBottom-yTop);points.push([x,y]);}
    const d=points.map((pt,i)=>(i?'L':'M')+pt[0].toFixed(1)+' '+pt[1].toFixed(1)).join(' ');
    $('timelinePath').setAttribute('d',d);$('timelineArea').setAttribute('d',d+' L '+x1+' '+yBottom+' L '+x0+' '+yBottom+' Z');
    const minute=now.getHours()*60+now.getMinutes(),nx=x0+(x1-x0)*minute/1440;$('timelineNow').setAttribute('x1',nx);$('timelineNow').setAttribute('x2',nx);$('timelineNow').style.display=sensorBased?'none':'block';
    $('timelineTopLabel').textContent=high+'% high';$('timelineBottomLabel').textContent=low+'% low';
    const labelIds=['timelineLabel0','timelineLabel1','timelineLabel2','timelineLabel3','timelineLabel4'];
    const labels=sensorBased?['Low','Dim','Indoor','Bright','Very bright']:['00:00','06:00','12:00','18:00','24:00'];
    labelIds.forEach((id,i)=>$(id).textContent=labels[i]);
    $('timelineKicker').textContent=solar?'SOLAR-ELEVATION RESPONSE':sensorBased?'AMBIENT SENSOR RESPONSE':'DAILY LIGHT CURVE';
    $('timelineTitle').textContent=solar?'Solar elevation to brightness':ambient?'Ambient illuminance response':tvSensor?'Illustrative built-in sensor response':'Illustrative brightness timeline';
    $('timelineCaption').textContent=solar?(Number.isFinite(latitude)&&Math.abs(latitude)<=89&&Number.isFinite(longitude)&&Math.abs(longitude)<=180?'Uses the current date, TV timezone, and coordinates; solar elevation is approximate.':'Set latitude and longitude in Extras → Solar location.') :ambient?'Illustrative response curve for recent external lux readings. Select an illuminance entity in Home Assistant options, or post samples to the secret ambient-lux webhook / local dashboard.':tvSensor?'Illustrative response curve for the TV sensor; actual readings vary by model and firmware. Use Extras → Check TV sensor to verify support.':('Preview uses '+($('fadeCurve').selectedOptions[0].text.toLowerCase())+' ramps. Sunrise/sunset triggers are calculated by the TV when selected.');
  }
  function parseClock(raw){const m=String(raw||'00:00').match(/^(\d{1,2}):(\d{2})$/);return m?Number(m[1])*60+Number(m[2]):0;}
  function updateProfileProtectionUI(parsed){
    const checked=$('profileProtectionEnabled').checked,enabled=$('enabled').checked,running=parsed.PROFILE_WATCHER_RUNNING==='1';
    const badge=$('profileProtectionBadge');badge.classList.toggle('neutral',!checked||!running);
    if(!checked){badge.textContent='Disabled';$('profileProtectionStatus').textContent='Turn this on and Save & apply to watch picture changes.';}
    else if(!enabled){badge.textContent='Paused';$('profileProtectionStatus').textContent='Paused because the main PanelComfort service is off.';}
    else if(running){badge.textContent='Watcher active';$('profileProtectionStatus').textContent='Checks foreground app / input dimensions and picture-mode changes where webOS exposes them.';}
    else{badge.textContent='Not running';$('profileProtectionStatus').textContent='Save & apply or reinstall the boot service to start the watcher.';}
    const context=parsed.PROFILE_CONTEXT||'';if(context.startsWith('Profile context unavailable'))$('profileContext').textContent='The watcher is running, but this firmware did not return input/profile metadata. The normal minute-based schedule remains active.';else $('profileContext').textContent=context?'Last profile: '+context:'Waiting for webOS to report the active input / picture profile.';
  }
  function activateTab(name,focus){if(!focus&&typeof window.scrollTo==='function')window.scrollTo(0,0);document.querySelectorAll('[data-tab]').forEach(btn=>{const a=btn.getAttribute('data-tab')===name;btn.classList.toggle('active',a);btn.setAttribute('aria-selected',a?'true':'false');btn.tabIndex=a?0:-1;});document.querySelectorAll('[data-panel]').forEach(p=>{const a=p.getAttribute('data-panel')===name;p.hidden=!a;p.classList.toggle('active',a);});if(focus){const b=document.querySelector('[data-tab="'+name+'"]');if(b)b.focus();}}
  const remoteArrowKeys={37:'left',38:'up',39:'right',40:'down'};
  function getRemoteDirection(event){if(event.key==='ArrowLeft')return 'left';if(event.key==='ArrowUp')return 'up';if(event.key==='ArrowRight')return 'right';if(event.key==='ArrowDown')return 'down';return remoteArrowKeys[event.keyCode]||null;}
  function focusables(){return Array.prototype.slice.call(document.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')).filter(el=>{
    if(el.disabled||el.tabIndex<0||el.getAttribute('aria-disabled')==='true'||el.closest('[hidden]'))return false;
    const style=window.getComputedStyle(el);if(style.display==='none'||style.visibility==='hidden'||style.visibility==='collapse')return false;
    const rect=el.getBoundingClientRect();return rect.width>0&&rect.height>0;
  });}
  function focusRect(el){
    if(el&&el.type==='checkbox'&&el.closest('.switch-label,.instance-option'))return el.closest('.switch-label,.instance-option').getBoundingClientRect();
    return el.getBoundingClientRect();
  }
  function nativeArrowEditing(el,direction){
    if(!el)return false;
    if(el.tagName==='TEXTAREA'||el.isContentEditable)return true;
    if(el.tagName==='SELECT')return false;
    if(el.tagName!=='INPUT')return false;
    const type=String(el.type||'text').toLowerCase();
    if(type==='range')return direction==='left'||direction==='right';
    if(['text','search','email','url','tel','password'].indexOf(type)>=0)return direction==='left'||direction==='right';
    if(type==='number'||type==='time')return direction==='left'||direction==='right';
    return false;
  }
  function nearestFocusable(from,direction,items){
    const start=focusRect(from),sx=start.left+start.width/2,sy=start.top+start.height/2;
    let best=null,bestScore=Infinity;
    items.forEach(el=>{
      if(el===from)return;
      const r=focusRect(el),x=r.left+r.width/2,y=r.top+r.height/2,dx=x-sx,dy=y-sy;
      let primary,secondary;
      if(direction==='left'){if(dx>=-2)return;primary=-dx;secondary=Math.abs(dy);}
      else if(direction==='right'){if(dx<=2)return;primary=dx;secondary=Math.abs(dy);}
      else if(direction==='up'){if(dy>=-2)return;primary=-dy;secondary=Math.abs(dx);}
      else{if(dy<=2)return;primary=dy;secondary=Math.abs(dx);}
      const score=primary+secondary*1.7;
      if(score<bestScore){best=el;bestScore=score;}
    });
    return best;
  }
  function focusRemoteTarget(target){
    if(!target)return;
    target.focus();
    try{target.scrollIntoView({block:'nearest',inline:'nearest'});}catch(_){try{target.scrollIntoView(false);}catch(__){}}
  }
  function handleRemoteArrows(event){
    const direction=getRemoteDirection(event);if(!direction)return;
    const active=document.activeElement;
    if(nativeArrowEditing(active,direction))return;
    if(active&&active.matches&&active.matches('[data-tab]')&&(direction==='left'||direction==='right')){
      const tabs=Array.prototype.slice.call(document.querySelectorAll('[data-tab]')),index=tabs.indexOf(active),step=direction==='right'?1:-1;
      activateTab(tabs[(index+step+tabs.length)%tabs.length].getAttribute('data-tab'),true);event.preventDefault();return;
    }
    const items=focusables();
    if(!active||active===document.body||active===document.documentElement){const first=document.getElementById('tabSchedule')||items[0];if(first){focusRemoteTarget(first);event.preventDefault();}return;}
    const target=nearestFocusable(active,direction,items);
    if(target){event.preventDefault();focusRemoteTarget(target);}
  }
  document.addEventListener('keydown',handleRemoteArrows,false);
  document.addEventListener('focusin',function(event){
    const target=event.target;if(!target||!target.matches||!target.matches('a[href],button,input,select,textarea,summary,[tabindex]'))return;
    try{target.scrollIntoView({block:'nearest',inline:'nearest'});}catch(_){try{target.scrollIntoView(false);}catch(__){}}
  },false);
  function getConfig(){
    const min=Number($('minBrightness').value),max=Number($('maxBrightness').value);
    const luxMin=Number($('ambientLuxMin').value),luxMax=Number($('ambientLuxMax').value),luxStability=Number($('luxStability').value),ambientOffset=Number($('ambientBrightnessOffset').value);
    const movieBrightness=Number($('movieBrightness').value);
    if(!Number.isInteger(min)||min<0||min>70||!Number.isInteger(max)||max<1||max>100)throw new Error('Backlight values must be whole percentages within their slider limits.');
    if(!Number.isInteger(movieBrightness)||movieBrightness<0||movieBrightness>100)throw new Error('Movie Mode brightness must be a whole percentage from 0 to 100.');
    if(min>max)throw new Error('Night minimum must not exceed the Day Maximum.');
    if(!Number.isInteger(luxMin)||luxMin<0||luxMin>199999||!Number.isInteger(luxMax)||luxMax<1||luxMax>200000||luxMin>=luxMax)throw new Error('Ambient lux limits must be whole lux values from 0 to 200000, with minimum below maximum.');
    if(!Number.isInteger(luxStability)||luxStability<0||luxStability>1000)throw new Error('Lux Stability must be a whole value from 0 to 1000 lx.');
    if(!Number.isInteger(ambientOffset)||ambientOffset< -30||ambientOffset>30)throw new Error('Ambient brightness offset must be a whole percentage adjustment from -30 to +30.');
    const clockIds=['dimStart','undimStart','eyeStart','eyeEnd'];
    clockIds.forEach(id=>{if(!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(String($(id).value||'')))throw new Error('Please enter valid 24-hour times for all schedule and Eye Comfort triggers.');});
    const solar=$('dimMode').value==='sunset'||$('upMode').value==='sunrise'||$('fadeMethod').value==='solar';
    const lat=$('latitude').value,lon=$('longitude').value;
    if(solar&&(lat===''||lon===''||!Number.isFinite(Number(lat))||!Number.isFinite(Number(lon))||Number(lat)<-89||Number(lat)>89||Number(lon)<-180||Number(lon)>180))throw new Error('Use Detect by internet or enter valid coordinates for sunrise / sunset mode.');
    const haPort=Number($('haApiPort').value||8765),hdrEnabled=$('hyperhdrEnabled').checked,hdrHost=String($('hyperhdrHost').value||'127.0.0.1').trim(),hdrPort=String($('hyperhdrPort').value||'auto').trim().toLowerCase(),hdrToken=String($('hyperhdrToken').value||'').trim(),hdrMin=Number($('hyperhdrMinBrightness').value),hdrMax=Number($('hyperhdrMaxBrightness').value),webhookHost=String($('webhookHost').value||tvLanIp||'').trim(),webhookHostOverride=String($('webhookHost').value||'').trim()===tvLanIp?'':String($('webhookHost').value||'').trim();
    if(!Number.isInteger(haPort)||haPort<1024||haPort>65535)throw new Error('Home Assistant / webhook port must be a whole number between 1024 and 65535.');
    if(!/^[a-zA-Z0-9.-]+$/.test(hdrHost))throw new Error('HyperHDR host must be a hostname or IPv4 address (no scheme or path).');
    if(webhookHost&&!/^[a-zA-Z0-9.-]+$/.test(webhookHost))throw new Error('TV address for webhook URLs must be an IP address or hostname without a scheme or path.');
    if(hdrPort!=='auto'&&(!/^\d+$/.test(hdrPort)||Number(hdrPort)<1||Number(hdrPort)>65535))throw new Error('HyperHDR port must be auto or a number from 1 to 65535.');
    if(hdrToken&&!/^[A-Za-z0-9._-]+$/.test(hdrToken))throw new Error('HyperHDR token may contain letters, digits, dots, underscores and hyphens only.');
    if(!Number.isInteger(hdrMin)||hdrMin<0||hdrMin>100||!Number.isInteger(hdrMax)||hdrMax<1||hdrMax>100)throw new Error('HyperHDR brightness values must be whole percentages from 0 to 100.');
    if(hdrMin>hdrMax)throw new Error('HyperHDR night minimum must not exceed its day/movie maximum.');
    const sunsetOffset=Number($('sunsetOffset').value),sunriseOffset=Number($('sunriseOffset').value);
    if(!Number.isInteger(sunsetOffset)||sunsetOffset< -180||sunsetOffset>180||!Number.isInteger(sunriseOffset)||sunriseOffset< -180||sunriseOffset>180)throw new Error('Sunrise and sunset offsets must be whole minutes between -180 and 180.');
    if(!['duration','solar','ambient','tv-sensor'].includes($('fadeMethod').value))throw new Error('Choose a valid fade calculation.');if(!['linear','easein','easeout','smooth','smootherstep','twilight','rolloff-soft','rolloff','rolloff-strong','exponential','gamma-late','gamma-early'].includes($('fadeCurve').value))throw new Error('Choose a valid fade curve.');if($('fadeMethod').value==='solar'&&(!lat||!lon))throw new Error('Solar fade mode needs latitude and longitude. Enter coordinates or use Detect by internet.');
    // Ambient mode can be configured without HA; browser dashboard/webhook can post samples, with a timed fallback until a recent reading arrives.
    const dimDuration=parseDuration($('dimDuration').value,false),undimDuration=parseDuration($('undimDuration').value,false),eyeStartOffset=parseDuration($('eyeStartOffset').value,true),eyeEndOffset=parseDuration($('eyeEndOffset').value,true);
    if(dimDuration===null||undimDuration===null)throw new Error('Fade durations must use H:MM (hours:minutes), from 0:00 to 12:00.');
    if(eyeStartOffset===null||eyeEndOffset===null)throw new Error('Eye Comfort offsets must use H:MM, optionally prefixed by - to mean before the trigger; maximum magnitude is 12:00.');
    const instanceSpec=String($('hyperhdrInstanceIds').value||'').trim().toLowerCase();if(hdrEnabled&&!instanceSpec)throw new Error('Select at least one HyperHDR instance, or choose “All running instances”.');if(instanceSpec&&instanceSpec!=='all'&&!/^[0-9]+(?:,[0-9]+)*$/.test(instanceSpec))throw new Error('HyperHDR instances must be “all” or comma-separated IDs such as 0,3.');if(instanceSpec&&instanceSpec!=='all'&&new Set(instanceSpec.split(',')).size!==instanceSpec.split(',').length)throw new Error('Each HyperHDR instance ID should appear only once.');
    const eyeLuxThreshold=Number($('eyeLuxThreshold').value);
    if(!Number.isInteger(eyeLuxThreshold)||eyeLuxThreshold<0||eyeLuxThreshold>200000)throw new Error('Eye Comfort lux threshold must be a whole number from 0 to 200000.');
    if(!['dynamic','time','on','off'].includes($('eyeComfortMode').value))throw new Error('Choose Dynamic, Time, On, or Off for Eye Comfort.');
    const values={ENABLED:$('enabled').checked?1:0,FADE_METHOD:$('fadeMethod').value,FADE_CURVE:$('fadeCurve').value,DIM_MODE:$('dimMode').value,DIM_START:$('dimStart').value||'21:00',DIM_DURATION:dimDuration,UP_MODE:$('upMode').value,UNDIM_START:$('undimStart').value||'06:30',UNDIM_DURATION:undimDuration,AMBIENT_LUX_MIN:luxMin,AMBIENT_LUX_MAX:luxMax,LUX_STABILITY:luxStability,AMBIENT_BRIGHTNESS_OFFSET:ambientOffset,MIN_BRIGHTNESS:min,MAX_BRIGHTNESS:max,MOVIE_BRIGHTNESS_ENABLED:$('movieBrightnessEnabled').checked?1:0,MOVIE_BRIGHTNESS:movieBrightness,EYE_ENABLED:$('eyeEnabled').checked?1:0,HA_EYE_COMFORT_OVERRIDE:$('eyeComfortMode').value,EYE_LUX_THRESHOLD:eyeLuxThreshold,EYE_TIMING:$('eyeTiming').value,EYE_START:$('eyeStart').value||'21:30',EYE_END:$('eyeEnd').value||'06:30',EYE_START_OFFSET:eyeStartOffset,EYE_END_OFFSET:eyeEndOffset,SUNSET_LAT:lat||'',SUNSET_LON:lon||'',SUNSET_OFFSET:$('sunsetOffset').value||'-20',SUNRISE_OFFSET:$('sunriseOffset').value||'0',PROFILE_PROTECTION_ENABLED:$('profileProtectionEnabled').checked?1:0,WEB_UI_ENABLED:$('webUiEnabled').checked?1:0,HA_API_ENABLED:$('haApiEnabled').checked?1:0,HA_API_PORT:haPort,HA_DEVICE_ID:haDeviceId,WEBHOOK_ENABLED:$('webhookEnabled').checked?1:0,WEBHOOK_TOKEN:webhookToken,WEBHOOK_HOST:webhookHostOverride,HYPERHDR_ENABLED:hdrEnabled?1:0,HYPERHDR_HOST:hdrHost,HYPERHDR_PORT:hdrPort,HYPERHDR_TOKEN:hdrToken,HYPERHDR_INSTANCE_IDS:instanceSpec,HYPERHDR_MIN_BRIGHTNESS:hdrMin,HYPERHDR_MAX_BRIGHTNESS:hdrMax};
    Object.keys(values).forEach(k=>{const v=String(values[k]);if(!/^[A-Z_]+$/.test(k))throw new Error('Invalid setting name');if(!/^-?[0-9.]+$/.test(v)&&!/^[a-zA-Z0-9:._,-]*$/.test(v))throw new Error('Invalid setting value for '+k);});
    return Object.keys(values).map(k=>k+'='+values[k]).join('\n')+'\n';
  }
  function toBase64(text){return btoa(unescape(encodeURIComponent(text)));}
  function configWriteCommand(encoded){
    // Merge old keys missing from the UI's form payload. This preserves the live
    // lux sample, timestamp, dashboard toggle, and future-version settings.
    return 'new='+ROOT+'/config.env.new; printf %s '+encoded+' | base64 -d > "$new" || exit 1; '+
      'if [ -r '+ROOT+'/config.env ]; then while IFS= read -r line || [ -n "$line" ]; do key=${line%%=*}; case "$key" in ""|*[!A-Z0-9_]*) continue;; esac; if ! grep -q "^${key}=" "$new"; then printf "%s\n" "$line" >> "$new"; fi; done < '+ROOT+'/config.env; fi; '+
      'chmod 600 "$new" && mv "$new" '+ROOT+'/config.env';
  }
  async function save(){
    try{if(!rootAvailable)throw new Error('Root service is not connected.');const config=getConfig();busy=true;disableActions(true);say('Saving settings and applying the current schedule…','');const encoded=toBase64(config);const cmd='mkdir -p '+ROOT+' && '+configWriteCommand(encoded)+' && if ! grep -Eq "^WEBHOOK_TOKEN=[a-fA-F0-9]{8}$" '+ROOT+'/config.env; then token=$(od -An -N4 -tx1 /dev/urandom | tr -d " \\n"); if grep -q "^WEBHOOK_TOKEN=" '+ROOT+'/config.env; then sed "s/^WEBHOOK_TOKEN=.*/WEBHOOK_TOKEN=$token/" '+ROOT+'/config.env > '+ROOT+'/config.env.tmp && mv '+ROOT+'/config.env.tmp '+ROOT+'/config.env; else echo "WEBHOOK_TOKEN=$token" >> '+ROOT+'/config.env; fi; fi && if ! grep -Eq "^HA_DEVICE_ID=[a-fA-F0-9]{24}$" '+ROOT+'/config.env; then device_id=$(od -An -N12 -tx1 /dev/urandom | tr -d " \\n"); sed "s/^HA_DEVICE_ID=.*/HA_DEVICE_ID=$device_id/" '+ROOT+'/config.env > '+ROOT+'/config.env.tmp && mv '+ROOT+'/config.env.tmp '+ROOT+'/config.env; fi && chmod 600 '+ROOT+'/config.env && '+ROOT+'/start.sh && '+ROOT+'/daemon.sh --once';await lunaExec(cmd);formDirty=false;updateFormDirty();say('Settings saved and applied'+(bootInstalled?'; they will resume after reboot.':'. Install the boot service for reboot persistence.'),'good');$('lastAction').textContent='Last saved: '+new Date().toLocaleTimeString();await refresh();return true;}catch(e){say(e.message,'error');return false;}finally{busy=false;disableActions(false);}
  }
  async function installBoot(){try{busy=true;disableActions(true);say('Installing / repairing the boot hook and scheduler scripts…','');const r=await lunaExec('sh '+APP_DIR+'/scripts/install-root.sh');const out=stdout(r);if(/ERROR=/.test(out))throw new Error(out.match(/ERROR=(.*)/)[1]);await refresh();const saved=await save();if(!saved)throw new Error('The service was installed, but settings were not saved/applied. Review the validation or error message and press Save & apply.');await refresh();say('Boot service installed / repaired and settings saved. It should run after reboots.','good');}catch(e){say('Could not complete boot-service setup: '+e.message+'. The existing settings have not intentionally been removed.','error');}finally{busy=false;disableActions(false);}}
  async function removeBoot(){try{busy=true;disableActions(true);await lunaExec('sh '+APP_DIR+'/scripts/remove-root.sh');await refresh();say('Autostart hook removed. The current configuration was kept.','good');}catch(e){say('Could not remove the boot hook: '+e.message,'error');}finally{busy=false;disableActions(false);}}
  async function rotateWebhook(){
    try{if(!rootAvailable||!schedulerReady)throw new Error('Install the boot service first.');const config=getConfig();busy=true;disableActions(true);say('Saving settings and rotating the webhook secret…','');const encoded=toBase64(config);const cmd=configWriteCommand(encoded)+' && token=$(od -An -N4 -tx1 /dev/urandom | tr -d " \\n"); [ "${#token}" -eq 8 ] || exit 1; if grep -q "^WEBHOOK_TOKEN=" '+ROOT+'/config.env; then sed "s/^WEBHOOK_TOKEN=.*/WEBHOOK_TOKEN=$token/" '+ROOT+'/config.env > '+ROOT+'/config.env.tmp && mv '+ROOT+'/config.env.tmp '+ROOT+'/config.env; else echo "WEBHOOK_TOKEN=$token" >> '+ROOT+'/config.env; fi; chmod 600 '+ROOT+'/config.env && '+ROOT+'/start.sh';await lunaExec(cmd);formDirty=false;updateFormDirty();await refresh();say('Webhook secret rotated. All old webhook URLs are invalid.','good');}catch(e){say('Could not rotate webhook links: '+e.message,'error');}finally{busy=false;disableActions(false);}
  }
  async function detectLocation(){
    function normaliseGeo(candidate){
      if(!candidate||candidate.success===false||candidate.status==='fail')return null;
      const latRaw=candidate.latitude!==undefined?candidate.latitude:candidate.lat;
      const lonRaw=candidate.longitude!==undefined?candidate.longitude:candidate.lon;
      if(latRaw===null||latRaw===undefined||lonRaw===null||lonRaw===undefined||latRaw===''||lonRaw==='')return null;
      const lat=Number(latRaw),lon=Number(lonRaw);
      if(!Number.isFinite(lat)||!Number.isFinite(lon)||Math.abs(lat)>89||Math.abs(lon)>180)return null;
      return {latitude:lat,longitude:lon,city:candidate.city,region:candidate.region||candidate.regionName||candidate.region_name,country:candidate.country_name||candidate.country};
    }
    async function browserGeoFallback(){
      if(typeof window.fetch!=='function')return null;
      const urls=['https://ipwho.is/','https://ipapi.co/json/'];
      for(const url of urls){
        let timer=0;
        try{
          const data=await Promise.race([
            window.fetch(url,{cache:'no-store',credentials:'omit'}).then(response=>{if(!response.ok)throw new Error('HTTP '+response.status);return response.json();}),
            new Promise((_,reject)=>{timer=window.setTimeout(()=>reject(new Error('Location request timed out')),8000);})
          ]);
          const point=normaliseGeo(data);if(point)return point;
        }catch(_){}finally{if(timer)window.clearTimeout(timer);}
      }
      return null;
    }
    try{
      busy=true;disableActions(true);$('locationStatus').textContent='Looking up approximate public-IP location from the TV, with an in-app HTTPS fallback…';
      // Prefer TV-side networking (avoids WebKit CORS/TLS issues on some webOS builds).
      const cmd='fetch(){ if command -v curl >/dev/null 2>&1; then curl -4fsSL --max-time 10 "$1" 2>/dev/null; elif command -v wget >/dev/null 2>&1; then wget -q -T 10 -O - "$1" 2>/dev/null; elif command -v busybox >/dev/null 2>&1 && busybox --list 2>/dev/null | grep -qx wget; then busybox wget -q -T 10 -O - "$1" 2>/dev/null; fi; }; data=$(fetch https://ipapi.co/json/ || true); case "$data" in *latitude*longitude*) printf "%s" "$data"; exit 0;; esac; fetch "http://ip-api.com/json/?fields=status,lat,lon,city,regionName,country"';
      const r=await lunaExec(cmd,25000),out=stdout(r);let data=null;
      try{data=JSON.parse(out);}catch(_){const latM=out.match(/"latitude"\s*:\s*(-?\d+(?:\.\d+)?)/),lonM=out.match(/"longitude"\s*:\s*(-?\d+(?:\.\d+)?)/);if(latM&&lonM)data={latitude:latM[1],longitude:lonM[1]};}
      let point=normaliseGeo(data);
      if(!point)point=await browserGeoFallback();
      if(!point)throw new Error('Neither the TV shell nor the in-app HTTPS lookup could retrieve valid coordinates. Check internet access; you can enter latitude and longitude manually.');
      $('latitude').value=point.latitude.toFixed(4);$('longitude').value=point.longitude.toFixed(4);
      const city=[point.city,point.region,point.country].filter(Boolean).join(', ');
      $('locationStatus').textContent='Approximate public-IP location'+(city?': '+city:'')+'. Review the coordinates and Save & apply.';
      say('Approximate solar location detected. Review it, then Save & apply.','good');updateScheduleUI();
    }catch(e){$('locationStatus').textContent='Location lookup failed: '+e.message+' Enter latitude and longitude manually.';say('Location lookup failed. No settings were changed on the TV.','error');}finally{busy=false;disableActions(false);}
  }
  async function copyWebhook(id,button){const value=$(id).value;if(!/^https?:\/\//.test(value)){say('That webhook URL is not ready yet. Refresh TV status and check the listener.','error');return;}try{if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(value);}else{$(id).focus();$(id).select();if(!document.execCommand('copy'))throw new Error('Copy command was blocked; select the URL and copy it manually.');}const old=button.textContent;button.textContent='Copied';window.setTimeout(()=>button.textContent=old,1200);say('Webhook URL copied. Treat it like a password.','good');}catch(e){$(id).focus();$(id).select();say('Could not copy automatically. The URL is selected so you can copy it manually.','error');}}
  function selectedHyperHdrIds(){return String($('hyperhdrInstanceIds').value||'').trim().toLowerCase();}
  function setHyperHdrSelection(value,dirty){
    $('hyperhdrInstanceIds').value=value;
    if($('hyperhdrInstanceIdsManual'))$('hyperhdrInstanceIdsManual').value=value;
    syncHyperHdrInstanceChecks();
    if(dirty)markFormDirty();
  }
  function renderHyperHdrInstances(ids){
    const box=$('hyperhdrInstanceOptions');if(!box)return;box.textContent='';
    const details=document.querySelector('#panelHyperHDR details.advanced-settings');if(details)details.open=true;
    const allLabel=document.createElement('label');allLabel.className='instance-option instance-option-all';const allInput=document.createElement('input');allInput.type='checkbox';allInput.value='all';allInput.checked=selectedHyperHdrIds()==='all';allInput.setAttribute('data-instance-all','1');const allText=document.createElement('span');allText.textContent='All running instances';allInput.addEventListener('change',()=>setHyperHdrSelection(allInput.checked?'all':'',true));allLabel.appendChild(allInput);allLabel.appendChild(allText);box.appendChild(allLabel);
    ids.forEach(id=>{const label=document.createElement('label');label.className='instance-option';const input=document.createElement('input');input.type='checkbox';input.value=String(id);input.checked=selectedHyperHdrIds()==='all'||selectedHyperHdrIds().split(',').indexOf(String(id))!==-1;input.setAttribute('data-instance-id',String(id));const text=document.createElement('span');text.textContent='Instance '+id;input.addEventListener('change',()=>{const checked=Array.from(box.querySelectorAll('input[data-instance-id]:checked')).map(x=>x.value);setHyperHdrSelection(checked.length===ids.length&&ids.length?'all':checked.join(','),true);});label.appendChild(input);label.appendChild(text);box.appendChild(label);});
    if(!ids.length){const note=document.createElement('span');note.className='muted small-copy';note.textContent='No running instance IDs detected. “All running instances” will use HyperHDR’s live instance list; manual IDs are available below.';box.appendChild(note);}
  }
  function syncHyperHdrInstanceChecks(){const box=$('hyperhdrInstanceOptions');if(!box)return;const ids=Array.from(box.querySelectorAll('input[data-instance-id]')).map(x=>x.value),current=selectedHyperHdrIds(),chosen=current==='all'?ids:current.split(',');const all=box.querySelector('input[data-instance-all]');if(all){all.checked=current==='all';if(all.parentNode&&all.parentNode.classList)all.parentNode.classList.toggle('selected',all.checked);}box.querySelectorAll('input[data-instance-id]').forEach(input=>{input.checked=chosen.indexOf(input.value)!==-1;if(input.parentNode&&input.parentNode.classList)input.parentNode.classList.toggle('selected',input.checked);});}
  async function testHyperHDR(){
    try{if(!rootAvailable||!schedulerReady)throw new Error('Install the boot service and save settings first.');busy=true;disableActions(true);$('hyperhdrDiscoveryStatus').textContent='Checking HyperHDR JSON-RPC connection…';const r=await lunaExec('sh '+ROOT+'/hyperhdr.sh test; rc=$?; echo PANELCOMFORT_TEST_EXIT=$rc; exit 0',20000);const out=stdout(r);const ok=/HYPERHDR_OK=1/.test(out);const port=(out.match(/HYPERHDR_PORT=([^\r\n]+)/)||[])[1]||'';const host=(out.match(/HYPERHDR_HOST=([^\r\n]+)/)||[])[1]||'';const ids=(out.match(/HYPERHDR_INSTANCE_IDS=([^\r\n]+)/)||[])[1]||'';if(!ok){const reason=(out.match(/ERROR=([^\r\n]+)/)||[])[1]||'No compatible JSON-RPC response.';throw new Error(reason);} const foundIds=(ids||'').split(',').filter(x=>/^\d+$/.test(x));renderHyperHdrInstances(foundIds);$('hyperhdrDiscoveryStatus').textContent=foundIds.length?'Connected to '+host+':'+port+' · running instances '+foundIds.join(', '):'JSON-RPC is reachable at '+host+':'+port+', but instance IDs could not be parsed. Use “All running instances” or enter IDs manually below.';say(foundIds.length?'HyperHDR connection successful. Select the instance(s) you want controlled, then Save & apply.':'HyperHDR answers, but instance discovery was inconclusive. Check “All running instances” or use the manual ID field.',''+(foundIds.length?'good':'error'));}catch(e){$('hyperhdrDiscoveryStatus').textContent='Connection failed';say('HyperHDR test failed: '+e.message,'error');}finally{busy=false;disableActions(false);}
  }
  async function checkTvSensor(){
    try{
      busy=true;disableActions(true);$('tvSensorStatus').textContent='Querying webOS luminance sensor…';
      const command = `if command -v timeout >/dev/null 2>&1; then timeout 3 luna-send -i -f "luna://com.webos.service.pqcontroller/getEyeqSensorData" '{"subscribe":true}' 2>/dev/null; elif command -v busybox >/dev/null 2>&1; then busybox timeout 3 luna-send -i -f "luna://com.webos.service.pqcontroller/getEyeqSensorData" '{"subscribe":true}' 2>/dev/null; else echo SENSOR_TIMEOUT_UNAVAILABLE; fi | tail -n 40; true`;
      const r=await lunaExec(command),out=stdout(r);const l=(out.match(/"luminance"\s*:\s*(\d+)/)||[])[1],v=(out.match(/"visibleLuminance"\s*:\s*(\d+)/)||[])[1];
      if(l||v){$('tvSensorStatus').textContent='Sensor responded · luminance '+(l||'—')+' · visible '+(v||'—')+' (model-specific units)';$('tvSensorBadge').textContent='Available';$('tvSensorBadge').classList.remove('unavailable');$('tvSensorBadge').classList.add('enabled');say('The TV luminance sensor responded. Select its mode in Schedule → Fade calculation.','good');}
      else{$('tvSensorStatus').textContent='No luminance reading returned. This model / firmware may not expose the sensor service.';$('tvSensorBadge').textContent='Unavailable';$('tvSensorBadge').classList.add('unavailable');$('tvSensorBadge').classList.remove('enabled');say('No TV luminance value was returned; TV-sensor mode will fall back to the timed schedule.','error');}
    }catch(e){$('tvSensorStatus').textContent='Sensor test failed: '+e.message;$('tvSensorBadge').textContent='Test failed';say('Could not query the TV sensor: '+e.message,'error');}finally{busy=false;disableActions(false);}
  }
  async function testHaEndpoint(){
    try{
      busy=true;disableActions(true);$('haEndpointTestStatus').textContent='Checking listener and discovery endpoint…';
      const port=String($('haApiPort').value||'8765'),ip=tvLanIp||$('haTvIp').value;
      const cmd='sh '+ROOT+'/ha-server.sh status; if command -v curl >/dev/null 2>&1; then curl -sS --max-time 3 -o /tmp/panelcomfort-health-test.json -w "LOCAL_HEALTH_HTTP=%{http_code}\n" http://127.0.0.1:'+port+'/cgi-bin/panelcomfort-health.cgi 2>&1; cat /tmp/panelcomfort-health-test.json 2>/dev/null; elif command -v wget >/dev/null 2>&1; then wget -q -T 3 -O /tmp/panelcomfort-health-test.json http://127.0.0.1:'+port+'/cgi-bin/panelcomfort-health.cgi && echo LOCAL_HEALTH_HTTP=200 && cat /tmp/panelcomfort-health-test.json || echo LOCAL_HEALTH_HTTP=000; else echo LOCAL_HTTP_CLIENT=unavailable; fi; echo ---HTTPD_LOG---; tail -n 12 '+ROOT+'/httpd.log 2>/dev/null; true';
      const r=await lunaExec(cmd),out=stdout(r);const running=/HTTPD_RUNNING=1/.test(out),http=(out.match(/LOCAL_HEALTH_HTTP=(\d+)/)||[])[1],err=(out.match(/ERROR=([^\r\n]+)/)||[])[1];
      let summary='HTTP listener '+(running?'running':'not running')+'; local health HTTP '+(http||'not checked')+'.';if(err)summary+=' '+err;
      $('haEndpointTestStatus').textContent=summary+' Detailed status and the last server-log lines are shown below.';
      const existing=$('haEndpointTestDetails');if(existing)existing.textContent=out;else{const pre=document.createElement('pre');pre.id='haEndpointTestDetails';pre.className='diagnostic-output';pre.textContent=out;$('haEndpointTestStatus').parentNode.appendChild(pre);}
      say(running&&http==='200'?'Local HTTP listener responds. Enable Home Assistant API and Save & apply before testing its discovery URL; check the TV health URL from Home Assistant next.':'The local HTTP health check failed. See the status and server-log details below.',''+(running&&http==='200'?'good':'error'));
    }catch(e){$('haEndpointTestStatus').textContent='Endpoint diagnostic failed: '+e.message;say(e.message,'error');}finally{busy=false;disableActions(false);}
  }
  async function toggleOverride(){
    try{
      busy=true;disableActions(true);say('Applying Movie Override to the TV and HyperHDR…','');
      const cmd='if [ -f '+ROOT+'/override.flag ]; then rm -f '+ROOT+'/override.flag; else : > '+ROOT+'/override.flag; fi; '+ROOT+'/daemon.sh --once; screen_rc=$?; echo MOVIE_SCREEN_APPLY_EXIT=$screen_rc; hdr_status=$(sed -n "s/^HYPERHDR_APPLY_STATUS=//p" '+ROOT+'/hyperhdr-apply-status 2>/dev/null | tail -n 1); hdr_target=$(sed -n "s/^HYPERHDR_APPLY_BRIGHTNESS=//p" '+ROOT+'/hyperhdr-apply-status 2>/dev/null | tail -n 1); echo MOVIE_HDR_APPLY_STATUS=${hdr_status:-unknown}; echo MOVIE_HDR_TARGET=${hdr_target:-0}; if [ -f '+ROOT+'/override.flag ]; then echo MOVIE_OVERRIDE_STATE=on; else echo MOVIE_OVERRIDE_STATE=off; fi; exit 0';
      const r=await lunaExec(cmd),out=stdout(r);
      const state=(out.match(/MOVIE_OVERRIDE_STATE=(on|off)/)||[])[1],screenRc=(out.match(/MOVIE_SCREEN_APPLY_EXIT=(\d+)/)||[])[1],hdrStatus=(out.match(/MOVIE_HDR_APPLY_STATUS=(sent|error|skipped|unknown)/)||[])[1],target=(out.match(/MOVIE_HDR_TARGET=(\d+)/)||[])[1];
      await refresh();
      if(screenRc!=='0')say('Movie Override '+(state==='on'?'enabled':'ended')+', but the TV did not confirm the screen brightness update. Check service.log for the luna-send response.','error');
      else if(hdrStatus==='sent')say('Movie Override '+(state==='on'?'enabled':'ended')+'. HyperHDR accepted the selected instance(s) and received a '+target+'% output-scale request.','good');
      else if(hdrStatus==='skipped')say('Movie Override '+(state==='on'?'enabled':'ended')+' on the TV. HyperHDR was not applied because its integration is disabled or its script is missing. Enable and test HyperHDR in Ambient LEDs settings.','error');
      else{const detail=(out.match(/ERROR=[^\r\n]+/)||[])[0]||'No successful HyperHDR confirmation was returned.';say('Movie Override '+(state==='on'?'enabled':'ended')+' on the TV, but HyperHDR did not confirm the LED brightness change. '+detail+' Check the Ambient LEDs connection test and service log.','error');}
    }catch(e){say('Could not change Movie Override: '+e.message,'error');}
    finally{busy=false;disableActions(false);}
  }

  ['dimDuration','undimDuration','eyeStartOffset','eyeEndOffset'].forEach(id=>protectDurationInput(id,id==='eyeStartOffset'||id==='eyeEndOffset'));
  fields.forEach(id=>{const e=$(id);if(!e)return;const update=()=>{markFormDirty();if(['minBrightness','maxBrightness','movieBrightness','movieBrightnessEnabled','hyperhdrMinBrightness','hyperhdrMaxBrightness'].includes(id))updateRanges();if(['movieBrightness','movieBrightnessEnabled','maxBrightness','eyeComfortMode'].includes(id))updateOverrideUI();if(['dimMode','upMode','fadeMethod','fadeCurve','dimStart','dimDuration','undimStart','undimDuration','ambientLuxMin','ambientLuxMax','ambientBrightnessOffset','sunsetOffset','sunriseOffset','eyeEnabled','eyeTiming','eyeStartOffset','eyeEndOffset','eyeStart','eyeEnd','enabled'].includes(id))updateScheduleUI();if(id==='fadeCurve')updateCurvePreview();if(id==='hyperhdrInstanceIds')syncHyperHdrInstanceChecks();if(['haApiEnabled','haApiPort','webUiEnabled'].includes(id))updateHAUI();if(['webhookEnabled','haApiPort','webhookHost'].includes(id))updateWebhookUI();if(id==='profileProtectionEnabled')updateProfileProtectionUI({PROFILE_WATCHER_RUNNING:'0'});};e.addEventListener('input',update);e.addEventListener('change',update);});
  $('hyperhdrInstanceIdsManual').addEventListener('input',function(){setHyperHdrSelection(this.value,true);});
  function bindClick(id,handler){const el=$(id);if(el)el.addEventListener('click',handler);else if(window.console&&console.warn)console.warn('PanelComfort: optional button missing:',id);}
  document.querySelectorAll('[data-save]').forEach(b=>b.addEventListener('click',save));
  bindClick('applyBtn',save);bindClick('overrideBtn',toggleOverride);bindClick('bootBtn',installBoot);bindClick('removeBtn',removeBoot);bindClick('refreshBtn',()=>refresh({recover:true}));bindClick('hyperhdrTestBtn',testHyperHDR);bindClick('detectLocationBtn',detectLocation);bindClick('webhookRotateBtn',rotateWebhook);bindClick('testTvSensorBtn',checkTvSensor);bindClick('testHaEndpointBtn',testHaEndpoint);bindClick('goToExtrasBtn',()=>activateTab('extras',false));
  document.querySelectorAll('.copy-webhook').forEach(b=>b.addEventListener('click',()=>copyWebhook(b.getAttribute('data-copy'),b)));
  $('webhookEnabled').addEventListener('change',()=>{if($('webhookEnabled').checked)$('webhookDetails').open=true;updateWebhookUI();});
  $('openWebInterface').addEventListener('click',e=>{if($('openWebInterface').getAttribute('aria-disabled')==='true')e.preventDefault();});
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>activateTab(b.getAttribute('data-tab'),false)));
  try{updateRanges();updateScheduleUI();updateHAUI();updateWebhookUI();activateTab('schedule',false);}catch(initError){setStatus('UI initialisation warning','bad');say('Some interface elements failed to initialise: '+initError.message+'. Service status will still be checked and Refresh remains available.','error');}
  refresh({recover:true});window.setInterval(()=>{if(!busy)refresh();},60000);
})();
