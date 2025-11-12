// static/tools_receipt.js
(function(){
  const $ = (s)=>document.querySelector(s);
  const txt = $('#txt');
  const btn = $('#analyze');
  const result = $('#result');

  function show(obj){
    result.textContent = typeof obj === 'string' ? obj : JSON.stringify(obj, null, 2);
  }

  btn.addEventListener('click', async ()=>{
    const text = txt.value || '';
    if(!text.trim()){
      show('Pegá el texto del ticket primero.');
      return;
    }
    try{
      const res = await fetch('/tools/receipt-analyzer/api', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ text })
      });
      const data = await res.json();
      show(data);
    }catch(e){
      show('Error: ' + e);
    }
  });
})();
