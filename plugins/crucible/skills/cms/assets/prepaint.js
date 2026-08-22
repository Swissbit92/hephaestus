/* Before first paint, deliberately. Setting the theme after the stylesheet has
   painted shows the wrong one for a frame — the flash people notice and nobody
   can un-see. Dark stays the default when nothing is stored. */
(function(){
  try{
    var t=localStorage.getItem('arch-theme');
    if(!t) t=matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
    document.documentElement.setAttribute('data-theme',t);
  }catch(e){document.documentElement.setAttribute('data-theme','dark');}
})();
