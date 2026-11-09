// Order matches Street_Fighter.src.arena.FIELDS / OBSERVATION_NAMES / ACTIONS.
const fighterInputLabels = ['Horizontal position', 'Vertical position', 'Vertical speed',
  'Health level', 'Facing right', 'On the ground', 'Attacking', 'Attack type',
  'Attack cooldown', 'Hit reaction', 'Animation', 'Animation frame', 'Animation tick', 'Character'];
const inputLabels = [...fighterInputLabels.map(name => `Self: ${name}`),
  ...fighterInputLabels.map(name => `Opponent: ${name}`),
  'Opponent horizontal offset', 'Opponent vertical offset', 'Time remaining',
  'Own health cube available', 'Opponent health cube available'];
const actionLabels = ['Idle'];
for (const move of [-1, 0, 1]) for (const jump of [false, true]) for (const attack of [0, 1, 2]) {
  if (!move && !jump && !attack) continue;
  actionLabels.push([move ? `Move ${move < 0 ? 'left' : 'right'}` : '', jump ? 'Jump' : '',
    attack ? `Attack ${attack}` : ''].filter(Boolean).join(' + '));
}

// Shared by the viewer and tests: character slots never follow screen position.
function policySlot(replay, agentIndex) {
  return (replay?.player_agents || [1, 2]).indexOf(agentIndex + 1);
}
function decisionAtFrame(replay, frameIndex, slot) {
  if (!replay || slot < 0 || frameIndex < 1 || frameIndex > replay.decision_frames) return null;
  const stride = replay.activity_stride || 1;
  // Never present a preceding decision as the current one (including older servers).
  if ((frameIndex - 1) % stride !== 0) return null;
  return replay.activity?.[(frameIndex - 1) / stride]?.[slot] || null;
}

// Native SVG titles have a browser-controlled delay. Use the same small tooltip style,
// shown immediately, and keep its text current while live activations change.
function attachNetworkTooltips(root) {
  const tip = document.createElement('div');
  tip.className = 'network-tooltip'; tip.id = 'network-tooltip';
  tip.setAttribute('role', 'tooltip'); tip.hidden = true;
  document.body.append(tip);
  let target = null, point = null;
  function hide() {
    if (target) target.removeAttribute('aria-describedby');
    target = null; tip.hidden = true;
  }
  function refresh() {
    if (!target) return;
    if (!target.isConnected) { hide(); return; }
    tip.textContent = target.getAttribute('aria-label'); tip.hidden = false;
    const rect = target.getBoundingClientRect();
    const x = point ? point.x : rect.right, y = point ? point.y : rect.bottom;
    const box = tip.getBoundingClientRect();
    tip.style.left = `${Math.max(8, Math.min(x + 12, window.innerWidth - box.width - 8))}px`;
    tip.style.top = `${Math.max(8, y + 12 + box.height > window.innerHeight - 8 ? y - box.height - 8 : y + 12)}px`;
  }
  function show(event, keyboard=false) {
    const node = event.target.closest('[data-network-tooltip]');
    if (!node || !root.contains(node)) { hide(); return; }
    if (target !== node) hide();
    target = node; point = keyboard ? null : {x:event.clientX, y:event.clientY};
    target.setAttribute('aria-describedby', tip.id); refresh();
  }
  root.addEventListener('pointerover', event => show(event));
  root.addEventListener('pointermove', event => show(event));
  root.addEventListener('pointerout', hide);
  root.addEventListener('focusin', event => show(event, true));
  root.addEventListener('focusout', hide);
  root.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
  window.addEventListener('scroll', hide, true);
  window.addEventListener('blur', hide);
  return refresh;
}

function architectureDiagram(architecture) {
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  const layers = [{width:architecture.inputs, type:'input'}, ...architecture.layers];
  const width = Math.max(400, layers.length * 130);
  const span = Math.max(180, Math.max(...layers.map(l => l.width)) * 7);
  const height = span + 110;
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.style.minWidth = `${layers.length * 85}px`;
  svg.setAttribute('role', 'group');
  svg.setAttribute('aria-label', 'Policy network: ' + layers.map(l => `${l.width} ${l.type} ${l.activation || ''}`).join(' → '));
  const add = (tag, attrs, text, parent=svg) => {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k,v]) => node.setAttribute(k, String(v)));
    if (text !== undefined) node.textContent = text;
    parent.append(node); return node;
  };
  const xs = layers.map((_,i) => 48 + i * (width-96)/(layers.length-1));
  const y = (layer,id) => 52 + span/2 + (id-(layers[layer].width-1)/2) * Math.min(13, span/Math.max(1,layers[layer].width-1));
  const gray = value => `rgb(${value}, ${value}, ${value})`;
  const maximum = values => values.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
  const edges = architecture.layers.map((layer,k) => (layer.connections || []).map(edge => {
    const group=add('g',{class:'network-edge'});
    const d=`M ${xs[k]+3} ${y(k,edge.from)} L ${xs[k+1]-3} ${y(k+1,edge.to)}`;
    const line=add('path',{d,fill:'none','stroke-width':.55,'pointer-events':'none'},undefined,group);
    const hit=add('path',{d,fill:'none',stroke:'transparent','stroke-width':3,'pointer-events':'stroke',class:'network-weight-hit','data-network-tooltip':''},undefined,group);
    return {...edge,line,hit};
  }));
  const nodes=layers.map((layer,i) => {
    const x=xs[i], output=i===layers.length-1;
    add('text',{x,y:19,'text-anchor':'middle',class:'network-label'},i===0 ? 'Inputs' : output ? 'Actions' : `Layer ${i}`);
    add('text',{x,y:38,'text-anchor':'middle',class:'network-count'},`${layer.width}${i ? ' · '+layer.activation : ''}`);
    const circles=[];
    for (let id=0;id<layer.width;id++) {
      const label=i===0 ? (architecture.action_feedback && id===architecture.inputs-1 ? 'Previous action' : inputLabels[id] || `Input ${id}`) : output ? actionLabels[id] || `Action ${id}` : `Layer ${i} neuron ${id + 1}`;
      const circle=add('circle',{cx:x,cy:y(i,id),r:2.5,fill:'#000',stroke:'#888','stroke-width':.7,tabindex:0,role:'img',class:'network-neuron','data-network-tooltip':''});
      circles.push({circle,label});
    }
    if (layer.type==='recurrent') {
      const loop=add('path',{d:`M ${x+8} ${55+span} C ${x+34} ${55+span} ${x+34} 55 ${x+8} 55 l 4 -3 m -4 3 l 4 3`,fill:'none',stroke:'#777','stroke-width':1});
      add('title',{},'Recurrent memory; neuron values include its contribution.',loop);
    }
    add('text',{x,y:height-25,'text-anchor':'middle',class:'network-label'},i ? (layer.type==='recurrent' ? 'Recurrent · memory' : 'Dense') : 'Observation');
    return circles;
  });
  svg.updateActivity = activity => {
    const values=activity?.values;
    svg.setAttribute('data-activity',values ? 'live' : 'weights');
    nodes.forEach((layer,k) => {
      const scale=values ? maximum(values[k]) : 0;
      const output=k===nodes.length-1;
      const low=values && output ? Math.min(...values[k]) : 0;
      const high=values && output ? Math.max(...values[k]) : 0;
      layer.forEach(({circle,label},id) => {
        const value=values?.[k]?.[id];
        // Action scores are signed: a large negative logit must not look preferred.
        const brightness=output ? (value === undefined ? 0 : high > low ?
          Math.round(255*(value-low)/(high-low)) : value === 0 ? 0 : 255) :
          value && scale ? Math.round(24+231*Math.abs(value)/scale) : 0;
        circle.setAttribute('fill',gray(brightness));
        const selected=k===nodes.length-1 && activity?.action===id;
        circle.setAttribute('stroke',selected ? '#fff' : '#888');
        circle.setAttribute('stroke-width',selected ? 2 : .7);
        circle.setAttribute('r',selected ? 3.5 : 2.5);
        circle.setAttribute('data-selected',String(selected));
        const description=k===0 || k===nodes.length-1 ? label :
          `${label}: ${value === undefined ? 'no current decision' : value}`;
        circle.setAttribute('aria-label',description);
      });
    });
    edges.forEach((layer,k) => {
      const signals=layer.map(edge => values ? values[k][edge.from]*edge.weight : edge.weight);
      const scale=maximum(signals);
      layer.forEach((edge,index) => {
        const brightness=Math.round(32+208*(scale ? Math.abs(signals[index])/scale : 0));
        edge.line.setAttribute('stroke',gray(brightness));
        const label=`L${k+1} W[${edge.to}][${edge.from}] = ${edge.weight}` + (values ? ` · source = ${values[k][edge.from]} · signal = ${signals[index]}` : ' · weight only');
        edge.hit.setAttribute('aria-label',label);
      });
    });
  };
  svg.updateActivity(null);
  return svg;
}
if (typeof module !== 'undefined') module.exports = {architectureDiagram, attachNetworkTooltips, inputLabels, actionLabels, policySlot, decisionAtFrame};
