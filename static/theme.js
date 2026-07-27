/* 全站主题：色系 + 字体，存 localStorage，页面加载时套用
   用法：页面引入本文件即可；设置面板调用 window.HomeTheme.set({scheme,font}) */
(function(){
  const SCHEMES = {
    blue:  {name:'湖水蓝', bg:'#edf3fa', card:'#ffffff', card2:'#f4f8fd', ink:'#1c3350', ink2:'#4c6a8c', ink3:'#8aa3bd', accent:'#2f7dc4', deep:'#1d5a96', soft:'#d9e9f8', line:'#dbe6f2'},
    cream: {name:'奶油杏', bg:'#f6f1e6', card:'#fdfaf2', card2:'#f4eede', ink:'#4a3a28', ink2:'#7c6a52', ink3:'#a99878', accent:'#c07a3d', deep:'#9c5c24', soft:'#f3e3cd', line:'#e6d9c2'},
    pink:  {name:'蜜桃粉', bg:'#fbeff2', card:'#fffafb', card2:'#f9edf1', ink:'#4a2b38', ink2:'#8c5c70', ink3:'#c096a8', accent:'#d46b8e', deep:'#b04a6e', soft:'#f7dde6', line:'#efd8e0'},
    green: {name:'苔原绿', bg:'#eef5ee', card:'#fbfdfb', card2:'#f0f6f0', ink:'#243b2a', ink2:'#557a5f', ink3:'#8fac96', accent:'#3f8c5a', deep:'#2c6b42', soft:'#dcefe2', line:'#dce8de'},
    night: {name:'深夜蓝', bg:'#0f1c2b', card:'#16283c', card2:'#122234', ink:'#dbe8f5', ink2:'#9db8d2', ink3:'#5f7a96', accent:'#5aa4e0', deep:'#7ab8ec', soft:'#1c3550', line:'#22374e'},
    creamdog: {name:'奶油绿·小狗', bg:'#eef2e4', card:'#fdfcf5', card2:'#f3f2e6', ink:'#5f5a48', ink2:'#7c7660', ink3:'#a3a08c', accent:'#8aa87e', deep:'#6d8f60', soft:'#dce5cc', line:'#dfe3d0'},
    olive:   {name:'橄榄军绿', bg:'#eceada', card:'#faf9f0', card2:'#f0eedd', ink:'#232211', ink2:'#6a6944', ink3:'#a3a471', accent:'#6a6944', deep:'#4a4930', soft:'#e3e1c6', line:'#d1cfa6'},
    rose:    {name:'云粉玫瑰', bg:'#f3e7e4', card:'#fbf4f1', card2:'#f0e1dd', ink:'#4e3a42', ink2:'#836871', ink3:'#a37e84', accent:'#a37e84', deep:'#836871', soft:'#ebd7ce', line:'#dbc4c2'},
    iceteal: {name:'冰海蓝', bg:'#eaf6f9', card:'#fbfeff', card2:'#e4f4f8', ink:'#0c3846', ink2:'#2a7387', ink3:'#5eb0c8', accent:'#2a7387', deep:'#0c3846', soft:'#c9e8f1', line:'#9fd3e3'},
    seasalt: {name:'海盐蓝绿', bg:'#e9f4f4', card:'#fbfefe', card2:'#e3f2fd', ink:'#3e5a5e', ink2:'#6e9598', ink3:'#8ab8b8', accent:'#6fa7ab', deep:'#4d8286', soft:'#c7e4e4', line:'#a3d6e0'},
    mocha:   {name:'复古奶咖', bg:'#ede7d5', card:'#f7f3e8', card2:'#e8e1cd', ink:'#5c4444', ink2:'#7d6360', ink3:'#a08a86', accent:'#7fa6a1', deep:'#5f8781', soft:'#d3e4e1', line:'#d9d1bc'},
  };
  const FONTS = {
    yozai:  {name:'悠哉圆体', css:"'Yozai'", face:"@font-face{font-family:'Yozai';src:url('/static/yozai.woff2') format('woff2');font-display:swap}"},
    nailao: {name:'小可奶酪体', css:"'NaiLao'", face:"@font-face{font-family:'NaiLao';src:url('/static/nailao.woff2') format('woff2');font-display:swap}"},
    system: {name:'系统默认', css:'-apple-system', face:''},
  };

  function get(){
    try{ return JSON.parse(localStorage.getItem('home-theme'))||{}; }catch(e){ return {}; }
  }
  function apply(){
    const cfg = get();
    const s = SCHEMES[cfg.scheme] || SCHEMES.blue;
    let css = '';
    if(s){
      css += `:root{--bg:${s.bg}!important;--card:${s.card}!important;--card2:${s.card2}!important;`+
             `--paper:${s.card}!important;--paper2:${s.card2}!important;`+
             `--ink:${s.ink}!important;--ink2:${s.ink2}!important;--ink3:${s.ink3}!important;`+
             `--accent:${s.accent}!important;--deep:${s.deep}!important;--accent-dark:${s.deep}!important;`+
             `--accent-soft:${s.soft}!important;--soft:${s.soft}!important;`+
             `--line:${s.line}!important;--border:${s.line}!important;`+
             `--bg-img:${s.bgimg ? `url('${s.bgimg}')` : 'none'}!important;}`;
      if(s.bgimg){
        css += `body{background:${s.bg} url('${s.bgimg}') center/cover fixed!important;}`;
      }else{
        // 无背景图的主题：铺一层同色系柔和渐变（浅→底→次卡色）
        css += `body{background:linear-gradient(180deg, ${s.soft} 0%, ${s.bg} 45%, ${s.card2} 100%) fixed!important;}`;
      }
    }
    const f = FONTS[cfg.font];
    if(f && cfg.font!=='system'){
      css += f.face + `body,button,input,textarea{font-family:${f.css},-apple-system,"PingFang SC","Microsoft YaHei",sans-serif!important}`;
    }
    // 磨砂玻璃跟主题走：深色主题换深玻璃+柔光团调暗，浅色主题只微调玻璃底色
    if(cfg.scheme === 'night'){
      css += `.card,.room-card,.group,.nav,#bar,header,.meta-row .mini,.post-card,.back-btn,.usage-block,.bar-chart-section,.model-card,.status-bar,.today-card,.calendar-card,.fu-status{background:rgba(18,34,54,0.55)!important;border-color:rgba(255,255,255,0.12)!important}`+
             `.blob{opacity:0.3!important}`+
             `.card.tinted-pink,.card.tinted-blue{background:rgba(24,40,62,0.55)!important}`;
    }
    let el = document.getElementById('home-theme-style');
    if(!el){ el = document.createElement('style'); el.id='home-theme-style'; document.head.appendChild(el); }
    el.textContent = css;
    // 顶部状态栏颜色（iOS safari 的 theme-color）跟着主题走
    let meta = document.querySelector('meta[name="theme-color"]');
    if(!meta){ meta = document.createElement('meta'); meta.name = 'theme-color'; document.head.appendChild(meta); }
    meta.setAttribute('content', s.soft);
  }
  function set(patch){
    const cfg = Object.assign(get(), patch);
    localStorage.setItem('home-theme', JSON.stringify(cfg));
    apply();
  }
  window.HomeTheme = {get, set, apply, SCHEMES, FONTS};
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', apply);
  else apply();
})();
