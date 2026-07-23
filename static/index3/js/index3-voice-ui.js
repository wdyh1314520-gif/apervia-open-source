// ====== Voice input (GPT-like recorder + backend transcription fallback) ======
function voiceUiT(key, params, fallback=''){
  return window.AperviaI18n?.t(key, params, fallback) || fallback || key;
}

let voiceMediaRecorder = null;
let voiceMediaStream = null;
let voiceRecordingChunks = [];
let voiceRecordingStartedAt = 0;
let voiceAcceptAfterStop = false;
let voiceInputActive = false;
let voiceInputBase = { prefix: '', suffix: '' };
let voiceInputPhase = 'idle';
let voiceMeterRaf = 0;
let voiceAudioContext = null;
let voiceAnalyser = null;
let voiceTranscribeAbort = null;
let voiceSpeechRecognition = null;
let voiceSpeechTranscript = '';
let voiceSpeechFinalTranscript = '';
let voiceSpeechAcceptOnEnd = false;
let voiceFlowPhase = 0;
let voiceFlowLastTs = 0;
let voiceWaveHistory = [];
let voiceWaveCanvasEl = null;
let voiceWaveCanvasCtx = null;
let voiceWaveSampleCarry = 0;
let voiceWaveLastSampleTs = 0;
let voiceWaveLastMoveSpeed = 52;
const VOICE_TRANSCRIBE_DEFAULT_MODEL = VOICE_SETTINGS_DEFAULTS.model || 'whisper-1';

function isVoiceInputSecureEnough(){
  try{
    if(window.isSecureContext) return true;
    const host = String(location.hostname || '').toLowerCase();
    return host === 'localhost' || host === '127.0.0.1' || host === '::1';
  }catch(_){
    return false;
  }
}

function isVoiceRecorderSupported(){
  try{
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder && window.FormData && window.Blob);
  }catch(_){
    return false;
  }
}

function isVoiceInputRuntimeSupported(engine = ''){
  const mode = normalizeVoiceEngine(engine || getVoiceSettings().engine);
  if(mode === 'web_api') return isBrowserSpeechRecognitionSupported();
  return isVoiceRecorderSupported();
}

function getConfiguredVoiceMimeTypes(){
  const cfg = getVoiceSettings();
  return String(cfg.mime_types || '')
    .split(',')
    .map(x => String(x || '').trim().toLowerCase())
    .filter(Boolean);
}

function voiceMimeMatchesConfigured(mime='', patternsText=''){
  const base = String(mime || '').split(';', 1)[0].trim().toLowerCase();
  if(!base) return false;
  const patterns = String(patternsText || '')
    .split(/[，,\n]+/)
    .map(x => String(x || '').trim().toLowerCase())
    .filter(Boolean);
  if(!patterns.length) return true;
  return patterns.some((pat)=>{
    if(pat.endsWith('/*')) return base.startsWith(pat.split('/', 1)[0] + '/');
    return base === pat;
  });
}

function getPreferredVoiceMimeType(){
  const configured = getConfiguredVoiceMimeTypes();
  const defaults = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/mpeg',
    'audio/wav',
  ];
  const expanded = [];
  for(const item of configured){
    if(item === 'audio/*' || item === 'video/*'){
      expanded.push(...defaults);
    }else if(item === 'audio/webm'){
      expanded.push('audio/webm;codecs=opus', 'audio/webm');
    }else{
      expanded.push(item);
    }
  }
  const candidates = expanded.length ? expanded : defaults;
  try{
    for(const item of candidates){
      if(window.MediaRecorder && typeof MediaRecorder.isTypeSupported === 'function' && MediaRecorder.isTypeSupported(item)) return item;
    }
  }catch(_){ }
  return expanded.length ? '' : '';
}

function getVoiceFileExt(mime=''){
  const m = String(mime || '').toLowerCase();
  if(m.includes('mp4')) return 'm4a';
  if(m.includes('mpeg') || m.includes('mp3')) return 'mp3';
  if(m.includes('wav')) return 'wav';
  if(m.includes('ogg')) return 'ogg';
  return 'webm';
}

function getVoiceTranscribeModel(){
  const cfg = getVoiceSettings();
  if(normalizeVoiceEngine(cfg.engine) === 'local_whisper') return String(cfg.local_model || VOICE_SETTINGS_DEFAULTS.local_model || 'base').trim() || 'base';
  return String(cfg.model || VOICE_TRANSCRIBE_DEFAULT_MODEL || 'whisper-1').trim() || 'whisper-1';
}
function getVoiceTranscribeRequestConfig(){
  const cfg = getVoiceSettings();
  const chat = getRequestSettings();
  const engine = normalizeVoiceEngine(cfg.engine);
  const apiKey = String(cfg.api_key || (cfg.follow_chat_api ? (chat.api_key || chat.api_settings?.api_key || '') : '') || '').trim();
  const apiBase = String(cfg.follow_chat_api ? (chat.api_base || chat.api_settings?.api_base || '') : '').trim();
  return {
    ...cfg,
    engine,
    api_key: engine === 'openai_compatible' ? apiKey : '',
    api_base: apiBase,
    api_settings: cfg.follow_chat_api ? (chat.api_settings || {}) : {},
  };
}

function normalizeVoiceTranscriptText(text){
  return String(text || '')
    .replace(/[\r\n\t]+/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\s+([，。！？、；：,.!?;:])/g, '$1')
    .trim();
}

function voiceNeedsSpace(left, right){
  const l = String(left || '').slice(-1);
  const r = String(right || '').slice(0, 1);
  if(!l || !r) return false;
  if(/\s/u.test(l) || /\s/u.test(r)) return false;
  const voiceBreakChars = '，。！？、；：,.!?;:"\'“”‘’（）()[]{}<>《》';
  if(voiceBreakChars.includes(l) || voiceBreakChars.includes(r)) return false;
  return /[A-Za-z0-9]/.test(l) && /[A-Za-z0-9]/.test(r);
}

function joinVoiceInputText(prefix, voiceText, suffix){
  const before = String(prefix || '');
  const spoken = normalizeVoiceTranscriptText(voiceText);
  const after = String(suffix || '');
  if(!spoken) return before + after;
  const leftGap = voiceNeedsSpace(before, spoken) ? ' ' : '';
  const rightGap = voiceNeedsSpace(spoken, after) ? ' ' : '';
  return before + leftGap + spoken + rightGap + after;
}

function applyVoiceTranscriptToInput(voiceText){
  if(!inputEl) return;
  const spoken = normalizeVoiceTranscriptText(voiceText);
  if(!spoken) return;
  const nextValue = joinVoiceInputText(voiceInputBase.prefix, spoken, voiceInputBase.suffix);
  inputEl.value = nextValue;
  const caretPos = joinVoiceInputText(voiceInputBase.prefix, spoken, '').length;
  try{ inputEl.setSelectionRange(caretPos, caretPos); }catch(_){ }
  try{ inputEl.dispatchEvent(new Event('input', { bubbles:true })); }catch(_){
    try{ resizeComposer(); updateComposerActionState(); }catch(__){ }
  }
  try{ inputEl.focus({ preventScroll:true }); }catch(_){ try{ inputEl.focus(); }catch(__){ } }
}

function syncVoiceInputUi(active, phase='recording'){
  const on = !!active;
  voiceInputPhase = on ? String(phase || 'recording') : 'idle';
  if(composerInputShellEl){
    composerInputShellEl.classList.remove('has-voice-input');
    composerInputShellEl.classList.toggle('voice-dictation-active', on);
    if(on){
      composerInputShellEl.style.setProperty('height', '58px', 'important');
      composerInputShellEl.style.setProperty('min-height', '58px', 'important');
      composerInputShellEl.style.setProperty('max-height', '58px', 'important');
      composerInputShellEl.style.setProperty('padding-left', '44px', 'important');
      composerInputShellEl.style.setProperty('padding-right', '12px', 'important');
      composerInputShellEl.style.setProperty('padding-top', '0', 'important');
      composerInputShellEl.style.setProperty('padding-bottom', '0', 'important');
    }else{
      for(const name of ['height','min-height','max-height','padding-left','padding-right','padding-top','padding-bottom']){
        try{ composerInputShellEl.style.removeProperty(name); }catch(_){ }
      }
      try{
        if(inputEl){
          inputEl.style.removeProperty('opacity');
          inputEl.style.removeProperty('pointer-events');
          inputEl.style.removeProperty('padding-top');
          inputEl.style.removeProperty('padding-bottom');
          inputEl.style.removeProperty('line-height');
          inputEl.style.removeProperty('font-size');
          inputEl.style.removeProperty('font-family');
          inputEl.style.removeProperty('letter-spacing');
        }
      }catch(_){ }
      try{ requestAnimationFrame(()=>{ try{ resizeComposer(); updateComposerActionState(); }catch(_){ } }); }catch(_){ }
    }
  }
  if(voiceInputBtn){
    voiceInputBtn.classList.toggle('is-active', on);
    voiceInputBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    voiceInputBtn.title = on ? '正在语音输入' : '语音输入';
    voiceInputBtn.setAttribute('aria-label', on ? '正在语音输入' : '语音输入');
  }
  if(voiceDictationUiEl){
    voiceDictationUiEl.hidden = !on;
    voiceDictationUiEl.classList.toggle('is-transcribing', on && voiceInputPhase === 'transcribing');
    voiceDictationUiEl.classList.toggle('is-speaking', false);
  }
  const busy = on && voiceInputPhase === 'transcribing';
  if(voiceInputCancelBtn) voiceInputCancelBtn.disabled = !!busy;
  if(voiceInputAcceptBtn) voiceInputAcceptBtn.disabled = !!busy;
}

function voiceWaveCssColor(alpha = 1){
  const a = Math.max(0, Math.min(1, Number(alpha || 0)));
  let color = '';
  try{ color = String(getComputedStyle(voiceDictationWaveEl || document.documentElement).color || '').trim(); }catch(_){ }
  if(!color) return `rgba(17,17,17,${a})`;
  const rgba = color.match(/^rgba?\(([^)]+)\)$/i);
  if(rgba){
    const parts = rgba[1].split(',').map(x => String(x || '').trim());
    if(parts.length >= 3) return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${a})`;
  }
  return color;
}

function ensureVoiceWaveCanvas(){
  const line = voiceDictationWaveEl;
  if(!line) return null;
  if(!voiceWaveCanvasEl || voiceWaveCanvasEl.parentElement !== line){
    line.innerHTML = '';
    voiceWaveCanvasEl = document.createElement('canvas');
    voiceWaveCanvasEl.className = 'voice-wave-canvas';
    voiceWaveCanvasEl.setAttribute('aria-hidden', 'true');
    line.appendChild(voiceWaveCanvasEl);
    voiceWaveCanvasCtx = null;
    voiceWaveHistory = [];
  }
  const canvas = voiceWaveCanvasEl;
  const rect = line.getBoundingClientRect ? line.getBoundingClientRect() : null;
  const cssWidth = Math.max(160, Math.round(rect?.width || line.clientWidth || 520));
  const cssHeight = Math.max(24, Math.round(rect?.height || line.clientHeight || 34));
  const dpr = Math.max(1, Math.min(2.5, window.devicePixelRatio || 1));
  const needResize = canvas.width !== Math.round(cssWidth * dpr) || canvas.height !== Math.round(cssHeight * dpr);
  if(needResize){
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(cssHeight * dpr);
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;
    voiceWaveCanvasCtx = canvas.getContext('2d');
    try{ voiceWaveCanvasCtx.setTransform(dpr, 0, 0, dpr, 0, 0); }catch(_){ }
    const targetLen = Math.max(90, Math.min(190, Math.round(cssWidth / 4.8)));
    if(voiceWaveHistory.length !== targetLen){
      const old = voiceWaveHistory.slice(-targetLen);
      voiceWaveHistory = Array(Math.max(0, targetLen - old.length)).fill(0).concat(old);
    }
  }else if(!voiceWaveCanvasCtx){
    voiceWaveCanvasCtx = canvas.getContext('2d');
    try{ voiceWaveCanvasCtx.setTransform(dpr, 0, 0, dpr, 0, 0); }catch(_){ }
  }
  return { line, canvas, ctx: voiceWaveCanvasCtx, width: cssWidth, height: cssHeight };
}

function pushVoiceWaveSamples(level = 0, waveformData = null){
  const view = ensureVoiceWaveCanvas();
  if(!view) return view;
  const targetLen = Math.max(90, Math.min(190, Math.round(view.width / 4.8)));
  if(voiceWaveHistory.length !== targetLen){
    const old = voiceWaveHistory.slice(-targetLen);
    voiceWaveHistory = Array(Math.max(0, targetLen - old.length)).fill(0).concat(old);
    voiceWaveSampleCarry = 0;
  }
  const eased = Math.max(0, Math.min(1, Number(level || 0)));
  const active = eased > 0.01;
  const data = waveformData && typeof waveformData.length === 'number' ? waveformData : null;
  const dataLen = data ? Math.max(1, data.length) : 0;

  const now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
  const dt = voiceWaveLastSampleTs ? Math.max(0.001, Math.min(0.08, (now - voiceWaveLastSampleTs) / 1000)) : 0.016;
  voiceWaveLastSampleTs = now;
  // v11: slow the perceived transmission speed.  Instead of pushing multiple
  // columns every animation frame, push a time-based number of samples so the
  // waveform moves like audio is passing through the line, not like a conveyor.
  const speakingSpeed = 24 + eased * 34;
  if(active){
    voiceWaveLastMoveSpeed = speakingSpeed;
  }
  // v13: use one shared travel speed for both speaking and silence.
  // Silence changes only the amplitude, not the horizontal transmission rate.
  const samplesPerSecond = Math.max(24, Math.min(72, voiceWaveLastMoveSpeed || speakingSpeed || 52));
  voiceWaveSampleCarry += dt * samplesPerSecond;
  let steps = Math.floor(voiceWaveSampleCarry);
  if(steps <= 0) return view;
  voiceWaveSampleCarry = Math.min(1.0, voiceWaveSampleCarry - steps);
  steps = Math.max(1, Math.min(3, steps));

  for(let step = 0; step < steps; step++){
    let sampleEnergy = 0;
    if(active && data){
      const start = Math.floor((step / steps) * dataLen);
      const end = Math.max(start + 1, Math.floor(((step + 1) / steps) * dataLen));
      let peak = 0;
      let sum = 0;
      let count = 0;
      for(let i = start; i < end; i += 2){
        const value = Math.abs((Number(data[i]) || 128) - 128) / 128;
        if(value > peak) peak = value;
        sum += value * value;
        count++;
      }
      const rms = Math.sqrt(sum / Math.max(1, count));
      sampleEnergy = Math.min(1, (rms * 2.3) + (peak * 0.58));
    }
    const silentPhase = ((voiceWaveHistory.length + step) % 18) / 18;
    const silentCarrier = 0.018 + Math.pow(Math.sin(silentPhase * Math.PI), 2) * 0.018;
    const value = active ? Math.max(0.03, Math.min(1, sampleEnergy * 0.82 + eased * 0.28)) : silentCarrier;
    voiceWaveHistory.push(value);
    while(voiceWaveHistory.length > targetLen) voiceWaveHistory.shift();
  }
  return view;
}

function drawVoiceWaveCanvas(level = 0){
  const view = ensureVoiceWaveCanvas();
  if(!view || !view.ctx) return;
  const { ctx, width, height } = view;
  const eased = Math.max(0, Math.min(1, Number(level || 0)));
  const active = eased > 0.01;
  const mid = Math.round(height / 2);
  const maxAmp = Math.max(8, Math.min(22, height * 0.44));
  ctx.clearRect(0, 0, width, height);

  // Subtle carrier line: stable reference, not the animation itself.
  ctx.save();
  ctx.lineWidth = 1.25;
  ctx.lineCap = 'round';
  ctx.strokeStyle = voiceWaveCssColor(active ? 0.12 : 0.16);
  ctx.beginPath();
  const dash = 12;
  const gap = 10;
  for(let x = 0; x < width; x += dash + gap){
    ctx.moveTo(x, mid);
    ctx.lineTo(Math.min(width, x + dash), mid);
  }
  ctx.stroke();
  ctx.restore();

  if(!voiceWaveHistory.length) return;
  const spacing = width / Math.max(1, voiceWaveHistory.length - 1);
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineWidth = active ? 2.2 : 1.6;
  for(let i = 0; i < voiceWaveHistory.length; i++){
    const v = Math.max(0, Math.min(1, Number(voiceWaveHistory[i] || 0)));
    if(v <= 0.006) continue;
    // Fade the oldest left side slightly, so new speech feels transmitted across the line.
    const age = i / Math.max(1, voiceWaveHistory.length - 1);
    const amp = Math.max(1.6, Math.pow(v, 0.72) * maxAmp);
    const opacity = Math.max(active ? 0.18 : 0.08, Math.min(0.95, (0.12 + Math.pow(v, 0.7) * 0.86) * (0.72 + age * 0.28)));
    const x = Math.round(i * spacing);
    ctx.strokeStyle = voiceWaveCssColor(opacity);
    ctx.beginPath();
    ctx.moveTo(x, mid - amp);
    ctx.lineTo(x, mid + amp);
    ctx.stroke();
  }
  ctx.restore();
}

function setVoiceMeterLevel(level = 0, waveformData = null){
  const eased = Math.max(0, Math.min(1, Number(level || 0)));
  pushVoiceWaveSamples(eased, waveformData);
  drawVoiceWaveCanvas(eased);
  const oldBars = Array.from(voiceDictationMeterEl?.querySelectorAll?.('span') || []);
  oldBars.forEach((bar)=>{
    bar.style.height = eased > 0.01 ? '10px' : '8px';
    bar.style.opacity = eased > 0.01 ? '0.35' : '0.12';
  });
  if(voiceDictationUiEl){
    voiceDictationUiEl.classList.toggle('is-speaking', eased > 0.01 && voiceInputPhase === 'recording');
  }
}

function stopVoiceMeter(){
  if(voiceMeterRaf){
    try{ cancelAnimationFrame(voiceMeterRaf); }catch(_){ }
    voiceMeterRaf = 0;
  }
  try{ voiceAudioContext?.close?.(); }catch(_){ }
  voiceAudioContext = null;
  voiceAnalyser = null;
  voiceFlowLastTs = 0;
  voiceWaveLastSampleTs = 0;
  voiceWaveSampleCarry = 0;
  voiceWaveLastMoveSpeed = 52;
  voiceWaveHistory = [];
  setVoiceMeterLevel(0);
}

function startVoiceMeter(stream){
  stopVoiceMeter();
  if(!voiceDictationMeterEl || !stream) return;
  try{
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if(!AudioCtx) return;
    const ctx = new AudioCtx();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.72;
    const source = ctx.createMediaStreamSource(stream);
    source.connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    voiceAudioContext = ctx;
    voiceAnalyser = analyser;
    let smoothedLevel = 0;
    setVoiceMeterLevel(0);
    const tick = ()=>{
      try{
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for(const value of data){
          const centered = (value - 128) / 128;
          sum += centered * centered;
        }
        const rms = Math.sqrt(sum / Math.max(1, data.length));
        const rawLevel = Math.min(1, rms * 5.2);
        smoothedLevel = (smoothedLevel * 0.78) + (rawLevel * 0.22);
        const gatedLevel = smoothedLevel > 0.055 ? Math.min(1, (smoothedLevel - 0.055) / 0.42) : 0;
        setVoiceMeterLevel(gatedLevel, data);
      }catch(_){ }
      voiceMeterRaf = requestAnimationFrame(tick);
    };
    tick();
  }catch(_){
    stopVoiceMeter();
  }
}

function getBrowserSpeechRecognitionCtor(){
  try{ return window.SpeechRecognition || window.webkitSpeechRecognition || null; }catch(_){ return null; }
}
function stopVoiceSpeechRecognition(){
  const rec = voiceSpeechRecognition;
  voiceSpeechRecognition = null;
  try{ if(rec) rec.onresult = rec.onerror = rec.onend = null; }catch(_){ }
  try{ rec?.stop?.(); }catch(_){ try{ rec?.abort?.(); }catch(__){ } }
}
function finishBrowserSpeechRecognition(){
  const text = normalizeVoiceTranscriptText(voiceSpeechFinalTranscript || voiceSpeechTranscript || '');
  const accepted = !!voiceSpeechAcceptOnEnd;
  voiceSpeechAcceptOnEnd = false;
  voiceSpeechRecognition = null;
  if(accepted && text){
    applyVoiceTranscriptToInput(text);
  }else if(accepted && !text){
    try{ toast(voiceUiT('voice.transcription_empty', null, 'The transcription was empty.')); }catch(_){ }
  }
  resetVoiceInputState({ clearStatus:true });
}
function startBrowserSpeechRecognition(){
  const Ctor = getBrowserSpeechRecognitionCtor();
  if(!Ctor){
    try{ toast(voiceUiT('voice.web_api_unsupported', null, 'This browser does not support Web API speech recognition.')); }catch(_){ }
    return;
  }
  const cfg = getVoiceSettings();
  const value = String(inputEl.value || '');
  const start = typeof inputEl.selectionStart === 'number' ? inputEl.selectionStart : value.length;
  const end = typeof inputEl.selectionEnd === 'number' ? inputEl.selectionEnd : start;
  voiceInputBase = {
    prefix: value.slice(0, Math.max(0, start)),
    suffix: value.slice(Math.max(0, end)),
  };
  voiceSpeechTranscript = '';
  voiceSpeechFinalTranscript = '';
  voiceSpeechAcceptOnEnd = false;
  voiceInputActive = true;
  syncVoiceInputUi(true, 'recording');
  try{ setStatus('正在听写…'); }catch(_){ }
  try{
    const rec = new Ctor();
    voiceSpeechRecognition = rec;
    rec.lang = cfg.language && cfg.language !== 'auto' ? cfg.language : 'zh-CN';
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (event)=>{
      let finalText = '';
      let interimText = '';
      try{
        for(let i = event.resultIndex || 0; i < event.results.length; i++){
          const result = event.results[i];
          const text = String(result?.[0]?.transcript || '').trim();
          if(!text) continue;
          if(result.isFinal) finalText += text + ' ';
          else interimText += text + ' ';
        }
      }catch(_){ }
      if(finalText.trim()) voiceSpeechFinalTranscript = normalizeVoiceTranscriptText((voiceSpeechFinalTranscript || '') + ' ' + finalText);
      voiceSpeechTranscript = normalizeVoiceTranscriptText((voiceSpeechFinalTranscript || '') + ' ' + interimText);
      setVoiceMeterLevel(interimText || finalText ? 0.36 : 0);
    };
    rec.onerror = (event)=>{
      const msg = String(event?.error || '网页 API 语音识别失败').trim();
      resetVoiceInputState({ clearStatus:true });
      try{ toast(msg || voiceUiT('voice.web_api_failed', null, 'Web API speech recognition failed.')); }catch(_){ }
    };
    rec.onend = ()=>{
      finishBrowserSpeechRecognition();
    };
    rec.start();
  }catch(e){
    resetVoiceInputState({ clearStatus:true });
    try{ toast(String(e?.message || e || voiceUiT('voice.web_api_start_failed', null, 'Unable to start Web API speech recognition.'))); }catch(_){ }
  }
}

function stopVoiceMediaTracks(){
  const stream = voiceMediaStream;
  voiceMediaStream = null;
  try{
    for(const track of (stream?.getTracks?.() || [])){
      try{ track.stop(); }catch(_){ }
    }
  }catch(_){ }
}

function resetVoiceInputState({ clearStatus = true } = {}){
  try{ voiceTranscribeAbort?.abort?.(); }catch(_){ }
  voiceTranscribeAbort = null;
  try{ stopVoiceSpeechRecognition(); }catch(_){ }
  voiceSpeechTranscript = '';
  voiceSpeechFinalTranscript = '';
  voiceSpeechAcceptOnEnd = false;
  voiceMediaRecorder = null;
  voiceRecordingChunks = [];
  voiceRecordingStartedAt = 0;
  voiceAcceptAfterStop = false;
  voiceInputActive = false;
  stopVoiceMeter();
  stopVoiceMediaTracks();
  syncVoiceInputUi(false);
  if(clearStatus){
    try{ setStatus(''); }catch(_){ }
  }
}

function stopVoiceInput(opts={}){
  if(!voiceInputActive && !voiceMediaRecorder && !voiceSpeechRecognition) return;
  const accept = !!opts.accept;
  voiceAcceptAfterStop = accept;
  if(voiceSpeechRecognition){
    voiceSpeechAcceptOnEnd = accept;
    if(accept){
      syncVoiceInputUi(true, 'transcribing');
      try{ setStatus('正在整理语音…'); }catch(_){ }
    }
    try{ voiceSpeechRecognition.stop(); }catch(_){ finishBrowserSpeechRecognition(); }
    return;
  }
  const rec = voiceMediaRecorder;
  if(accept){
    syncVoiceInputUi(true, 'transcribing');
    try{ setStatus('正在转写语音…'); }catch(_){ }
  }
  if(!rec){
    resetVoiceInputState({ clearStatus: !accept });
    return;
  }
  try{
    if(rec.state && rec.state !== 'inactive'){
      rec.stop();
      return;
    }
  }catch(_){ }
  handleVoiceRecorderStopped().catch(()=>{});
}

async function transcribeVoiceBlob(blob, mime=''){
  const settings = getVoiceTranscribeRequestConfig();
  if(!settings.enabled){
    throw new Error('语音输入未开启');
  }
  if(settings.engine === 'web_api'){
    throw new Error('网页 API 模式不需要上传音频');
  }
  if(settings.engine === 'openai_compatible' && !String(settings.api_key || '').trim()){
    throw new Error('请先在语音设置里填写语音 API Key，或开启 Key 跟随主聊天');
  }
  const form = new FormData();
  const ext = getVoiceFileExt(mime || blob?.type || '');
  form.append('audio', blob, `voice-input-${Date.now()}.${ext}`);
  form.append('engine', String(settings.engine || 'openai_compatible'));
  form.append('model', String(settings.model || getVoiceTranscribeModel() || 'whisper-1'));
  form.append('local_model', String(settings.local_model || 'base'));
  form.append('local_device', String(settings.local_device || 'auto'));
  form.append('local_compute_type', String(settings.local_compute_type || 'auto'));
  form.append('local_vad_filter', settings.local_vad_filter ? '1' : '0');
  const effectiveMime = String(mime || blob?.type || '').trim();
  form.append('mime_types', voiceMimeMatchesConfigured(effectiveMime, settings.mime_types) ? String(settings.mime_types || '') : '');
  form.append('language', String(settings.language || 'zh').slice(0, 16));
  form.append('response_format', String(settings.response_format || 'json'));
  form.append('api_key', settings.api_key || '');
  form.append('api_base', settings.api_base || '');
  form.append('transcribe_url', settings.transcribe_url || '');
  if(String(settings.prompt || '').trim()) form.append('prompt', String(settings.prompt || '').trim());
  try{ form.append('api_settings', JSON.stringify(settings.api_settings || {})); }catch(_){ }
  try{ form.append('voice_settings', JSON.stringify(settings || {})); }catch(_){ }
  const ctl = new AbortController();
  voiceTranscribeAbort = ctl;
  const res = await fetch('/api3/voice/transcribe', {
    method:'POST',
    body:form,
    credentials:'same-origin',
    cache:'no-store',
    signal:ctl.signal,
  });
  let data = null;
  try{ data = await res.json(); }catch(_){
    let raw = '';
    try{ raw = await res.text(); }catch(__){ }
    data = { error: raw || `HTTP ${res.status}` };
  }
  if(!res.ok || data?.ok === false){
    throw new Error(String(data?.error || data?.message || `HTTP ${res.status}`));
  }
  const text = normalizeVoiceTranscriptText(data?.text || data?.transcript || '');
  if(!text) throw new Error('语音转写结果为空');
  return text;
}

async function handleVoiceRecorderStopped(){
  const accept = !!voiceAcceptAfterStop;
  const chunks = voiceRecordingChunks.slice();
  const durationMs = Date.now() - Number(voiceRecordingStartedAt || Date.now());
  const mime = String(voiceMediaRecorder?.mimeType || getPreferredVoiceMimeType() || 'audio/webm');
  voiceMediaRecorder = null;
  stopVoiceMeter();
  stopVoiceMediaTracks();
  if(!accept){
    resetVoiceInputState({ clearStatus:true });
    return;
  }
  try{
    const blob = new Blob(chunks, { type:mime });
    if(durationMs < 350 || blob.size < 700){
      resetVoiceInputState({ clearStatus:true });
      try{ toast(voiceUiT('voice.no_speech', null, 'No usable speech was detected.')); }catch(_){ }
      return;
    }
    syncVoiceInputUi(true, 'transcribing');
    const text = await transcribeVoiceBlob(blob, mime);
    applyVoiceTranscriptToInput(text);
    resetVoiceInputState({ clearStatus:true });
  }catch(e){
    const msg = String(e?.message || e || '语音转写失败').trim();
    resetVoiceInputState({ clearStatus:true });
    try{ toast(msg || voiceUiT('voice.transcription_failed', null, 'Voice transcription failed.')); }catch(_){ }
  }
}

async function startVoiceInput(){
  if(!voiceInputBtn || !inputEl) return;
  if(voiceInputActive){
    stopVoiceInput({ accept:false });
    return;
  }
  if(!isVoiceInputSecureEnough()){
    try{ toast(voiceUiT('voice.secure_context_required', null, 'Voice input requires HTTPS or a local address.')); }catch(_){ }
    return;
  }
  const voiceEngine = normalizeVoiceEngine(getVoiceSettings().engine);
  if(voiceEngine === 'web_api'){
    if(!isBrowserSpeechRecognitionSupported()){
      try{ toast(voiceUiT('voice.web_api_unsupported', null, 'This browser does not support Web API speech recognition.')); }catch(_){ }
      return;
    }
    startBrowserSpeechRecognition();
    return;
  }
  if(!isVoiceRecorderSupported()){
    try{ toast(voiceUiT('voice.recording_unsupported', null, 'This browser does not support audio recording.')); }catch(_){ }
    return;
  }

  const value = String(inputEl.value || '');
  const start = typeof inputEl.selectionStart === 'number' ? inputEl.selectionStart : value.length;
  const end = typeof inputEl.selectionEnd === 'number' ? inputEl.selectionEnd : start;
  voiceInputBase = {
    prefix: value.slice(0, Math.max(0, start)),
    suffix: value.slice(Math.max(0, end)),
  };

  voiceInputActive = true;
  voiceAcceptAfterStop = false;
  voiceRecordingChunks = [];
  syncVoiceInputUi(true, 'recording');
  try{ setStatus('正在听写…'); }catch(_){ }

  try{
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    });
    if(!voiceInputActive){
      try{ for(const track of (stream.getTracks?.() || [])) track.stop(); }catch(_){ }
      return;
    }
    voiceMediaStream = stream;
    const mime = getPreferredVoiceMimeType();
    const recorderOptions = mime ? { mimeType:mime } : undefined;
    const rec = new MediaRecorder(stream, recorderOptions);
    voiceMediaRecorder = rec;
    voiceRecordingStartedAt = Date.now();
    rec.ondataavailable = (event)=>{
      try{
        if(event?.data && event.data.size > 0) voiceRecordingChunks.push(event.data);
      }catch(_){ }
    };
    rec.onerror = (event)=>{
      const msg = String(event?.error?.message || event?.error || '录音失败').trim();
      resetVoiceInputState({ clearStatus:true });
      try{ toast(msg || voiceUiT('voice.recording_failed', null, 'Recording failed.')); }catch(_){ }
    };
    rec.onstop = ()=>{
      handleVoiceRecorderStopped().catch((e)=>{
        resetVoiceInputState({ clearStatus:true });
        try{ toast(String(e?.message || e || voiceUiT('voice.transcription_failed', null, 'Voice transcription failed.'))); }catch(_){ }
      });
    };
    try{ rec.start(250); }catch(e){
      resetVoiceInputState({ clearStatus:true });
      try{ toast(String(e?.message || voiceUiT('voice.recording_start_failed', null, 'Unable to start recording.'))); }catch(_){ }
      return;
    }
    startVoiceMeter(stream);
  }catch(e){
    const name = String(e?.name || '').toLowerCase();
    resetVoiceInputState({ clearStatus:true });
    if(name.includes('notallowed') || name.includes('permission')){
      try{ toast(voiceUiT('voice.microphone_denied', null, 'Microphone permission was denied.')); }catch(_){ }
    }else{
      try{ toast(String(e?.message || voiceUiT('voice.microphone_start_failed', null, 'Unable to start the microphone.'))); }catch(_){ }
    }
  }
}

function refreshVoiceInputAvailability(){
  if(!voiceInputBtn || !composerInputShellEl) return;
  const settings = getVoiceSettings();
  const enabled = !!settings.enabled;
  const supported = isVoiceInputRuntimeSupported(settings.engine);
  const visible = enabled && supported;
  if(!visible && voiceInputActive){
    try{ resetVoiceInputState({ clearStatus:true }); }catch(_){ }
  }
  voiceInputBtn.hidden = !visible;

  // Keep normal composer layout untouched: use a separate voice-ui-ready class
  // instead of has-voice-input, because old has-voice-input CSS changes textarea
  // padding/height and can break the original composer look.
  composerInputShellEl.classList.remove('has-voice-input');
  composerInputShellEl.classList.toggle('voice-ui-ready', visible);
}
function initVoiceInput(){
  if(!voiceInputBtn || !composerInputShellEl) return;
  refreshVoiceInputAvailability();
  syncVoiceInputUi(false);
  if(voiceInputBtn.dataset.voiceBound !== '1'){
    voiceInputBtn.addEventListener('click', startVoiceInput);
    voiceInputBtn.dataset.voiceBound = '1';
  }
  if(voiceInputCancelBtn && voiceInputCancelBtn.dataset.voiceBound !== '1'){
    voiceInputCancelBtn.addEventListener('click', ()=>stopVoiceInput({ accept:false }));
    voiceInputCancelBtn.dataset.voiceBound = '1';
  }
  if(voiceInputAcceptBtn && voiceInputAcceptBtn.dataset.voiceBound !== '1'){
    voiceInputAcceptBtn.addEventListener('click', ()=>stopVoiceInput({ accept:true }));
    voiceInputAcceptBtn.dataset.voiceBound = '1';
  }
}

/* Paste images（保留原功能：Ctrl+V 进待发送预览，可×） */

/* ✅ 待发送附件（文件/图片）：
   - 文件：上传后先进入“待发送”，可×删除；点击发送时才写入会话 messages + system 上下文
   - 图片：Ctrl+V/上传/拖拽都会进入待发送预览（pastedImages 负责真正的多模态发送）
*/
