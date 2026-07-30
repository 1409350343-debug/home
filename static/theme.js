/* 全站固定主题：夏日绿色 */
(function(){
  const SUMMER = {
    name:'夏日绿色',
    bg:'#faf5d8',
    card:'#fffdee',
    card2:'#f5f4d7',
    ink:'#496653',
    ink2:'#6f856f',
    ink3:'#98a98f',
    accent:'#88ad73',
    deep:'#658b59',
    soft:'#e7efcf',
    line:'#dce8cf'
  };
  const FIXED = {scheme:'summer',font:'system'};
  const SCHEMES = {summer:SUMMER};
  const FONTS = {system:{name:'系统默认',css:'-apple-system',face:''}};

  function get(){
    try{
      const saved=JSON.parse(localStorage.getItem('home-theme'))||{};
      if(saved.scheme!==FIXED.scheme||saved.font!==FIXED.font){
        localStorage.setItem('home-theme',JSON.stringify(FIXED));
      }
    }catch(e){
      localStorage.setItem('home-theme',JSON.stringify(FIXED));
    }
    return {...FIXED};
  }

  function apply(){
    get();
    const s=SUMMER;
    const css =
      `:root{--bg:${s.bg}!important;--card:${s.card}!important;--card2:${s.card2}!important;`+
      `--paper:${s.card}!important;--paper2:${s.card2}!important;`+
      `--ink:${s.ink}!important;--ink2:${s.ink2}!important;--ink3:${s.ink3}!important;`+
      `--accent:${s.accent}!important;--deep:${s.deep}!important;--accent-dark:${s.deep}!important;`+
      `--accent-soft:${s.soft}!important;--soft:${s.soft}!important;`+
      `--line:${s.line}!important;--border:${s.line}!important;}`+
      `body,button,input,textarea,select{font-family:"AaCheeseCJK","Oleo Script",-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif!important;}`+
      `body{background-color:#f8f1df!important;`+
      `background-image:url("/static/summer-green-background.png")!important;`+
      `background-position:center bottom!important;background-size:cover!important;`+
      `background-repeat:no-repeat!important;background-attachment:fixed!important;}`;
    let el=document.getElementById('home-theme-style');
    if(!el){
      el=document.createElement('style');
      el.id='home-theme-style';
      document.head.appendChild(el);
    }
    el.textContent=css;
    let meta=document.querySelector('meta[name="theme-color"]');
    if(!meta){
      meta=document.createElement('meta');
      meta.name='theme-color';
      document.head.appendChild(meta);
    }
    meta.setAttribute('content',s.soft);
  }

  function set(){
    localStorage.setItem('home-theme',JSON.stringify(FIXED));
    apply();
  }

  window.HomeTheme={get,set,apply,SCHEMES,FONTS};
  apply();
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply,{once:true});
})();
