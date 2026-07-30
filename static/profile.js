/* 小窝头像：本机浏览器保存、全站同步 */
(function(){
  const KEYS={xiaoyang:'home-avatar-xiaoyang',fufu:'home-avatar-fufu'};
  const FALLBACKS={xiaoyang:'',fufu:'/static/img/fufu/portrait.jpg?v=4'};

  function get(owner){
    try{return localStorage.getItem(KEYS[owner])||FALLBACKS[owner]||''}catch(e){return FALLBACKS[owner]||''}
  }
  const remote={};
  function source(owner){return remote[owner]||get(owner)}
  function apply(root=document){
    root.querySelectorAll('[data-avatar-owner]').forEach(el=>{
      const owner=el.dataset.avatarOwner;
      const src=source(owner);
      if(el.tagName==='IMG'){
        if(src)el.src=src;
      }else{
        if(src){
          el.textContent='';
          el.style.backgroundImage=`url("${src}")`;
          el.style.backgroundSize='cover';
          el.style.backgroundPosition='center';
        }else{
          el.style.backgroundImage='none';
          el.textContent=owner==='xiaoyang'?'🐑':'🦊';
        }
      }
    });
  }
  function resize(file){
    return new Promise((resolve,reject)=>{
      if(!file||!file.type.startsWith('image/'))return reject(new Error('请选择图片文件'));
      const reader=new FileReader();
      reader.onerror=()=>reject(new Error('图片读取失败'));
      reader.onload=()=>{
        const img=new Image();
        img.onerror=()=>reject(new Error('图片无法打开'));
        img.onload=()=>{
          const size=Math.min(img.naturalWidth,img.naturalHeight);
          const sx=(img.naturalWidth-size)/2,sy=(img.naturalHeight-size)/2;
          const canvas=document.createElement('canvas');
          canvas.width=512;canvas.height=512;
          canvas.getContext('2d').drawImage(img,sx,sy,size,size,0,0,512,512);
          resolve(canvas.toDataURL('image/jpeg',.86));
        };
        img.src=reader.result;
      };
      reader.readAsDataURL(file);
    });
  }
  async function save(owner,file){
    const data=await resize(file);
    const blob=await (await fetch(data)).blob();
    const form=new FormData();
    form.append('owner',owner);
    form.append('file',blob,`avatar-${owner}.jpg`);
    const response=await fetch('/api/read/avatar',{method:'POST',body:form});
    if(!response.ok)throw new Error('头像没有同步到服务器');
    const result=await response.json();
    remote[owner]=result.url;
    localStorage.removeItem(KEYS[owner]);
    apply();
    window.dispatchEvent(new CustomEvent('home-avatar-change',{detail:{owner,src:result.url}}));
    return result.url;
  }
  async function clear(owner){
    const response=await fetch('/api/read/avatar/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({owner})});
    if(!response.ok)throw new Error('默认头像恢复失败');
    delete remote[owner];
    localStorage.removeItem(KEYS[owner]);
    apply();
    window.dispatchEvent(new CustomEvent('home-avatar-change',{detail:{owner,src:source(owner)}}));
  }
  async function sync(){
    try{
      const response=await fetch('/api/read/profile?t='+Date.now(),{cache:'no-store'});
      if(!response.ok)return;
      const result=await response.json();
      Object.keys(remote).forEach(owner=>delete remote[owner]);
      Object.assign(remote,result.avatars||{});
      Object.keys(KEYS).forEach(owner=>localStorage.removeItem(KEYS[owner]));
      apply();
    }catch(e){}
  }
  window.HomeProfile={get:source,apply,save,clear,sync};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{apply();sync()},{once:true});
  else{apply();sync()}
})();
