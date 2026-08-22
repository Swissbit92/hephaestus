(function(){
  var doc=document.documentElement;
  /* One iteration helper. NodeList.forEach and Array.prototype.forEach.call were
     both in use here; picking one keeps the intent obvious. */
  function each(xs,fn){Array.prototype.forEach.call(xs,fn);}

  /* theme toggle */
  var t=document.getElementById('th');
  function paint(){
    var light=doc.getAttribute('data-theme')==='light';
    t.textContent=light?'\u25D1 DARK':'\u25D1 LIGHT';
    t.setAttribute('aria-label',light?'Switch to dark theme':'Switch to light theme');
  }
  paint();
  t.addEventListener('click',function(){
    var next=doc.getAttribute('data-theme')==='light'?'dark':'light';
    doc.setAttribute('data-theme',next);
    try{localStorage.setItem('arch-theme',next);}catch(e){}
    paint();
  });

  /* pause. The animation is CSS keyframes, so a class is the whole mechanism.
     The SVG animation-pause API this used to call drives SMIL, which no diagram
     on this page uses — it was a no-op dressed up as a feature. */
  var b=document.getElementById('pz'),p=false;
  b.addEventListener('click',function(){
    p=!p;document.body.classList.toggle('paused',p);
    b.setAttribute('aria-pressed',String(p));
    b.textContent=p?'\u25B6 RESUME':'\u23F8 PAUSE';
  });

  /* copy buttons */
  each(document.querySelectorAll('[data-copy]'),function(btn){
    btn.addEventListener('click',function(){
      var code=btn.parentNode.querySelector('code');
      if(!code) return;
      var done=function(){
        btn.textContent='copied';btn.setAttribute('data-done','');
        setTimeout(function(){btn.textContent='copy';btn.removeAttribute('data-done');},1400);
      };
      /* navigator.clipboard needs a secure context, and this page is opened
         from file:// as often as over https. Fall back rather than fail. */
      if(navigator.clipboard&&navigator.clipboard.writeText){
        navigator.clipboard.writeText(code.textContent).then(done,function(){});
      }else{
        var r=document.createRange();r.selectNodeContents(code);
        var s=getSelection();s.removeAllRanges();s.addRange(r);
        try{document.execCommand('copy');done();}catch(e){}
        s.removeAllRanges();
      }
    });
  });

  /* node inspector + tour — on every diagram, flow or not */
  each(document.querySelectorAll('.inspect'),function(box){
    var svg=document.getElementById(box.getAttribute('data-inspect'));
    if(!svg) return;
    var hint=box.querySelector('.ins-hint'), body=box.querySelector('.ins-body'),
        t=box.querySelector('.ins-t'), k=box.querySelector('.ins-k'),
        tech=box.querySelector('.ins-tech'), s=box.querySelector('.ins-s'),
        links=box.querySelector('.ins-links'),
        gotoEl=box.querySelector('.ins-goto'),
        tour=document.querySelector('.tour[data-tour="'+svg.id+'"]'),
        order=tour?tour.getAttribute('data-order').split(','):[],
        at=-1;

    function show(g,quiet){
      each(svg.querySelectorAll('[data-node].picked'),function(o){o.classList.remove('picked');});
      g.classList.add('picked');
      t.textContent=g.getAttribute('data-label')||'';
      k.textContent=g.getAttribute('data-kind')||'';
      var tv=g.getAttribute('data-tech'); tech.textContent=tv?'['+tv+']':'';
      /* Purpose first. A node with no authored note says so rather than
         showing a sentence assembled out of its own metadata. */
      var note=g.getAttribute('data-note'), sub=g.getAttribute('data-sub');
      if(note){ s.textContent=note; s.className='ins-s'; }
      else if(sub){ s.textContent=sub; s.className='ins-s'; }
      else { s.textContent='No description written for this one yet.';
              s.className='ins-s ins-none'; }
      links.textContent=g.getAttribute('data-links')||'';
      /* A node that stands for another repo is a dead end without this: the
         diagram names the neighbour and then offers no way to reach it. */
      var goto_=g.getAttribute('data-goto')||'';
      if(goto_){gotoEl.href=goto_;
        gotoEl.textContent='→ open '+(g.getAttribute('data-label')||'');
        gotoEl.hidden=false;}
      else{gotoEl.hidden=true;}
      hint.hidden=true; body.hidden=false;
      if(!quiet){
        var idx=order.indexOf(g.getAttribute('data-node'));
        if(idx>=0) at=idx;
        pos();
      }
      var ctl=document.querySelector('.flowctl[data-view="'+svg.id+'"]');
      if(ctl&&ctl.__jump) ctl.__jump(g.getAttribute('data-node'));
    }
    function nodeAt(i){
      return svg.querySelector('[data-node="'+
        (typeof CSS!=='undefined'&&CSS.escape?CSS.escape(order[i]):order[i])+'"]');
    }
    function pos(){
      if(!tour) return;
      tour.querySelector('[data-tour-pos]').textContent =
        at<0 ? '—' : (at+1)+' / '+order.length;
      tour.querySelector('[data-tour-prev]').disabled = at<=0;
      tour.querySelector('[data-tour-next]').disabled = at>=order.length-1;
    }
    each(svg.querySelectorAll('[data-node]'),function(g){
      g.addEventListener('click',function(){show(g);});
      g.addEventListener('keydown',function(e){
        if(e.key==='Enter'||e.key===' '){e.preventDefault();show(g);}
      });
    });
    if(tour){
      tour.querySelector('[data-tour-next]').addEventListener('click',function(){
        if(at<order.length-1){at++;var g=nodeAt(at); if(g) show(g,true); pos();}
      });
      tour.querySelector('[data-tour-prev]').addEventListener('click',function(){
        if(at>0){at--;var g=nodeAt(at); if(g) show(g,true); pos();}
      });
      tour.querySelector('[data-tour-clear]').addEventListener('click',function(){
        each(svg.querySelectorAll('[data-node].picked'),function(o){o.classList.remove('picked');});
        at=-1; hint.hidden=false; body.hidden=true; pos();
      });
      /* If a flow walks this view, the tour is that flow — say so. */
      var ctl=document.querySelector('.flowctl[data-view="'+svg.id+'"]');
      if(ctl) tour.querySelector('[data-tour-lbl]').innerHTML=
        'Tour<span class="tourwhy"> &middot; or pick a flow below</span>';
      pos();
    }
  });

  /* flow walker */
  each(document.querySelectorAll('.flowctl'),function(ctl){
    var svg=document.getElementById(ctl.getAttribute('data-view'));
    if(!svg) return;
    var flows;
    try{flows=JSON.parse(ctl.getAttribute('data-flows'));}catch(e){return;}
    if(!flows||!flows.length) return;

    var list=ctl.querySelector('.flowlist'),
        cap=ctl.querySelector('[data-flow-cap]'),
        pos=ctl.querySelector('[data-flow-pos]'),
        prev=ctl.querySelector('[data-flow-prev]'),
        next=ctl.querySelector('[data-flow-next]'),
        clear=ctl.querySelector('[data-flow-clear]'),
        cur=-1,step=0;

    function marks(){
      each(svg.querySelectorAll('.on-path,.at-step'),function(el){
        el.classList.remove('on-path','at-step');
        el.removeAttribute('aria-current');
      });
    }
    function q(v){return typeof CSS!=='undefined'&&CSS.escape?CSS.escape(v):v;}
    function find(s){
      return s.t==='node'
        ? svg.querySelector('[data-node="'+q(s.k)+'"]')
        : svg.querySelector('[data-edge-from="'+q(s.f)+'"][data-edge-to="'+q(s.to)+'"]');
    }
    function draw(){
      marks();
      if(cur<0){
        svg.classList.remove('flowing');
        each(list.querySelectorAll('li'),function(li){li.setAttribute('aria-selected','false');});
        cap.textContent='Select a flow to trace it through the diagram.';
        pos.textContent='\u2014';
        prev.disabled=next.disabled=true;
        return;
      }
      var f=flows[cur];
      svg.classList.add('flowing');
      each(list.querySelectorAll('li'),function(li,k){
        li.setAttribute('aria-selected',String(k===cur));
      });
      each(f.steps,function(s){
        var el=find(s); if(el) el.classList.add('on-path');
      });
      var at=f.steps[step],el=at&&find(at);
      if(el){el.classList.add('at-step');el.setAttribute('aria-current','step');}
      pos.textContent='step '+(step+1)+' / '+f.steps.length;
      /* One whole-text write, not an append — partial updates get dropped. */
      cap.textContent=(at&&at.note)?at.note:f.label;
      prev.disabled=step<=0;
      next.disabled=step>=f.steps.length-1;
      try{
        history.replaceState(null,'','#flow='+encodeURIComponent(f.id)+'&step='+(step+1));
      }catch(e){}
    }
    function pick(k,s){cur=k;step=s||0;draw();}

    /* Clicking a box on the diagram jumps the walk to the step that uses it.
       Searches the selected flow first so an id appearing in two flows does not
       yank you out of the one you are reading. */
    ctl.__jump=function(nodeId){
      var order=[]; if(cur>=0) order.push(cur);
      flows.forEach(function(_,j){ if(j!==cur) order.push(j); });
      for(var a=0;a<order.length;a++){
        var j=order[a], st=flows[j].steps;
        for(var i=0;i<st.length;i++){
          if(st[i].t==='node'&&st[i].k===nodeId){ pick(j,i); return true; }
        }
      }
      return false;                          /* not on any flow: inspect only */
    };

    list.addEventListener('click',function(e){
      var li=e.target.closest('li'); if(!li) return;
      pick(Array.prototype.indexOf.call(list.children,li),0);
    });
    list.addEventListener('keydown',function(e){
      var k=e.key;
      if(k==='ArrowDown'||k==='ArrowRight'){e.preventDefault();pick(Math.min((cur<0?-1:cur)+1,flows.length-1),0);}
      else if(k==='ArrowUp'||k==='ArrowLeft'){e.preventDefault();pick(Math.max((cur<0?flows.length:cur)-1,0),0);}
      else if(k==='Home'){e.preventDefault();pick(0,0);}
      else if(k==='End'){e.preventDefault();pick(flows.length-1,0);}
      else if(k==='Escape'){e.preventDefault();cur=-1;draw();}
    });
    prev.addEventListener('click',function(){if(step>0){step--;draw();}});
    next.addEventListener('click',function(){if(cur>=0&&step<flows[cur].steps.length-1){step++;draw();}});
    clear.addEventListener('click',function(){cur=-1;draw();});

    function fromHash(){
      var m=/flow=([^&]+)(?:&step=(\d+))?/.exec(location.hash||'');
      if(!m) return false;
      var id=decodeURIComponent(m[1]),k=-1;
      each(flows,function(f,j){if(f.id===id)k=j;});
      if(k<0) return false;                       /* unknown id: stay neutral */
      var s=Math.max(0,Math.min((parseInt(m[2],10)||1)-1,flows[k].steps.length-1));
      pick(k,s);
      return true;
    }
    window.addEventListener('hashchange',fromHash);
    if(!fromHash()) draw();
  });
})();
