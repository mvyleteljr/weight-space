function architectureDiagram(architecture) {
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  const layers = [{width:architecture.inputs, type:'input'}, ...architecture.layers];
  const width = Math.max(400, layers.length * 125);
  const span = Math.max(160, Math.max(...layers.map(l => l.width)) * 5);
  const height = span + 85;
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.style.minWidth = `${Math.min(width, 400)}px`;
  svg.setAttribute('role', 'group');
  svg.setAttribute('aria-label', 'Policy network: ' + layers.map(l => `${l.width} ${l.type} ${l.activation || ''}`).join(' → '));
  const add = (tag, attrs, text, parent=svg) => {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k,v]) => node.setAttribute(k, String(v)));
    if (text !== undefined) node.textContent = text;
    parent.append(node); return node;
  };
  const xs = layers.map((_,i) => 48 + i * (width-96)/(layers.length-1));
  const y = (layer,id) => 52 + span/2 + (id-(layers[layer].width-1)/2) * Math.min(11, span/Math.max(1,layers[layer].width-1));
  const nodes = [];
  let selection = [layers.length-1, 0];
  // Layer links give an uncluttered overview. Inspect one neuron for actual weights.
  for (let i=1; i<layers.length; i++) {
    add('path',{d:`M ${xs[i-1]+10} ${55+span/2} H ${xs[i]-10}`,stroke:'#384653','stroke-width':1,fill:'none'});
  }
  const edges = add('g', {});
  // Normalize against the entire destination layer, not just the selected neuron.
  const layerMaxima = architecture.layers.map(layer =>
    Math.max(0, ...(layer.connections || []).map(edge => Math.abs(edge.weight))));
  const inspect = (li,id) => {
    selection = [li,id];
    nodes.forEach(({node,layer,index}) => node.setAttribute("aria-pressed", String(layer===li && index===id)));
    edges.replaceChildren();
    architecture.layers.forEach((layer,k) => {
      const to = k+1;
      for (const edge of layer.connections || []) {
        if (!((li === to && edge.to === id) || (li === k && edge.from === id))) continue;
        const brightness = Math.round(70 + 170 * (layerMaxima[k] ? Math.abs(edge.weight) / layerMaxima[k] : 0));
        const d = `M ${xs[k]+4} ${y(k,edge.from)} L ${xs[to]-4} ${y(to,edge.to)}`;
        const label = `L${k} W[${edge.to}][${edge.from}] = ${edge.weight}`;
        const group = add('g', {}, undefined, edges);
        add('path',{d,stroke:`rgb(${brightness}, ${brightness}, ${brightness})`,
          'stroke-width':0.8,fill:'none','pointer-events':'none'}, undefined, group);
        const hit = add('path',{d,stroke:'transparent','stroke-width':6,fill:'none',
          'pointer-events':'stroke','aria-label':label,class:'network-weight-hit'}, undefined, group);
        add('title',{},label,hit);
      }
    });
  };
  layers.forEach((layer,i) => {
    const x=xs[i], output=i===layers.length-1;
    add('text',{x,y:19,'text-anchor':'middle',class:'network-label'},i===0 ? 'Inputs' : output ? 'Actions' : `Layer ${i}`);
    add('text',{x,y:38,'text-anchor':'middle',class:'network-count'},`${layer.width}${i ? ' · '+layer.activation : ''}`);
    for (let id=0; id<layer.width; id++) {
      const circle=add('circle',{cx:x,cy:y(i,id),r:2.5,fill:'currentColor',
        tabindex:0,role:'button','aria-label':i===0 ? (architecture.action_feedback && id===31 ? 'Previous action / 17 (−1 at reset)' : `Input ${id}`) : `Layer ${i-1}, neuron ${id}`,class:'network-neuron'});
      add('title',{},i===0 ? (architecture.action_feedback && id===31 ? 'Previous action / 17 (−1 at reset)' : `Input ${id}`) : `Layer ${i-1}, neuron ${id} · bias ${layer.biases?.[id] ?? 'unavailable'}`,circle);
      nodes.push({node:circle,layer:i,index:id});
      circle.addEventListener('keydown',event=>{if (event.key==='Enter' || event.key===' ') {event.preventDefault();inspect(i,id);}});
      circle.addEventListener('click',()=>inspect(i,id));
    }
    if (layer.type==='recurrent') {
      add('path',{d:`M ${x+8} ${55+span} C ${x+34} ${55+span} ${x+34} 55 ${x+8} 55 l 4 -3 m -4 3 l 4 3`,fill:'none',stroke:'#cb98eb','stroke-width':1});
    }
    add('text',{x,y:height-25,'text-anchor':'middle',class:'network-label'},i ? (layer.type==='recurrent' ? 'Recurrent · memory' : 'Dense') : 'Observation');

  });
  inspect(...selection);
  return svg;
}

if (typeof module !== 'undefined') module.exports = {architectureDiagram};
