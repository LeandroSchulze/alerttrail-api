// static/tools_qr.js
(function(){
  const $ = (s)=>document.querySelector(s);
  const out = $('#out');
  const video = $('#cam');
  const btnStart = $('#btnStart');
  const file = $('#file');
  const actions = $('#actions');
  const openLink = $('#openLink');
  const copyLink = $('#copyLink');

  let stream = null;
  let detector = null;

  function show(text){
    out.textContent = text || '—';
  }

  function setResult(url){
    show(url);
    if(url && /^https?:\/\//i.test(url)){
      actions.style.display = 'flex';
      openLink.href = url;
    }else{
      actions.style.display = 'none';
      openLink.removeAttribute('href');
    }
  }

  async function detectFromBitmap(bitmap){
    if(!detector){ return null; }
    try{
      const codes = await detector.detect(bitmap);
      if(codes && codes.length){
        return codes[0].rawValue || codes[0].rawValue || '';
      }
    }catch(e){}
    return null;
  }

  async function startCamera(){
    if(!('BarcodeDetector' in window)){
      show('Tu navegador no soporta BarcodeDetector. Usá "Subir imagen".');
      return;
    }
    detector = new window.BarcodeDetector({ formats: ['qr_code'] });
    if(stream){
      // ya iniciado
      return;
    }
    try{
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
      video.srcObject = stream;
      await video.play();

      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');

      async function tick(){
        if(video.readyState >= 2){
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
          ctx.drawImage(video, 0, 0);
          const bitmap = await createImageBitmap(canvas);
          const val = await detectFromBitmap(bitmap);
          bitmap.close();
          if(val){
            stopCamera();
            setResult(val);
            if(window.toast) toast.success('QR detectado');
            return;
          }
        }
        requestAnimationFrame(tick);
      }
      requestAnimationFrame(tick);
      show('Escaneando… apuntá el QR a la cámara.');
    }catch(err){
      show('No se pudo acceder a la cámara: ' + err);
    }
  }

  function stopCamera(){
    try{
      if(stream){
        stream.getTracks().forEach(t=>t.stop());
      }
    }catch(e){}
    stream = null;
  }

  file.addEventListener('change', async (ev)=>{
    const f = ev.target.files && ev.target.files[0];
    if(!f){ return; }
    try{
      if(!('BarcodeDetector' in window)){
        show('BarcodeDetector no disponible en este navegador.');
        return;
      }
      detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      const bitmap = await createImageBitmap(f);
      const val = await detectFromBitmap(bitmap);
      bitmap.close();
      if(val){
        setResult(val);
        if(window.toast) toast.success('QR detectado desde imagen');
      }else{
        setResult('No se detectó QR en la imagen.');
      }
    }catch(err){
      show('Error al procesar imagen: ' + err);
    }
  });

  copyLink.addEventListener('click', async ()=>{
    const txt = out.textContent || '';
    try{
      await navigator.clipboard.writeText(txt);
      if(window.toast) toast.success('Copiado al portapapeles');
    }catch(e){
      if(window.toast) toast.error('No se pudo copiar');
    }
  });

  btnStart.addEventListener('click', startCamera);
  window.addEventListener('beforeunload', stopCamera);
})();
