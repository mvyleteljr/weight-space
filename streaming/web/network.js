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
    const hit=add('path',{d,fill:'none',stroke:'transparent','stroke-width':3,'pointer-events':'stroke',class:'network-weight-hit'},undefined,group);
    const title=add('title',{},'',hit);
    return {...edge,line,hit,title};
  }));
  const nodes=layers.map((layer,i) => {
    const x=xs[i], output=i===layers.length-1;
    add('text',{x,y:19,'text-anchor':'middle',class:'network-label'},i===0 ? 'Inputs' : output ? 'Actions' : `Layer ${i}`);
    add('text',{x,y:38,'text-anchor':'middle',class:'network-count'},`${layer.width}${i ? ' · '+layer.activation : ''}`);
    const circles=[];
    for (let id=0;id<layer.width;id++) {
      const label=i===0 ? (architecture.action_feedback && id===architecture.inputs-1 ? 'Previous action / 17 (−1 at reset)' : `Input ${id}`) : output ? `Action ${id} logit` : `Layer ${i} neuron ${id}`;
      const circle=add('circle',{cx:x,cy:y(i,id),r:2.5,fill:'#000',stroke:'#888','stroke-width':.7,tabindex:0,role:'img',class:'network-neuron'});
      const title=add('title',{},'',circle);
      circles.push({circle,title,label});
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
      layer.forEach(({circle,title,label},id) => {
        const value=values?.[k]?.[id];
        const brightness=value && scale ? Math.round(24+231*Math.abs(value)/scale) : 0;
        circle.setAttribute('fill',gray(brightness));
        const selected=k===nodes.length-1 && activity?.action===id;
        circle.setAttribute('stroke',selected ? '#fff' : '#888');
        circle.setAttribute('stroke-width',selected ? 1.5 : .7);
        const description=`${label}: ${value === undefined ? 'no current decision' : value}${selected ? ' · selected action' : ''}`;
        circle.setAttribute('aria-label',description); title.textContent=description;
      });
    });
    edges.forEach((layer,k) => {
      const signals=layer.map(edge => values ? values[k][edge.from]*edge.weight : edge.weight);
      const scale=maximum(signals);
      layer.forEach((edge,index) => {
        const brightness=Math.round(32+208*(scale ? Math.abs(signals[index])/scale : 0));
        edge.line.setAttribute('stroke',gray(brightness));
        const label=`L${k+1} W[${edge.to}][${edge.from}] = ${edge.weight}` + (values ? ` · source = ${values[k][edge.from]} · signal = ${signals[index]}` : ' · weight only');
        edge.hit.setAttribute('aria-label',label); edge.title.textContent=label;
      });
    });
  };
  svg.updateActivity(null);
  return svg;
}
if (typeof module !== 'undefined') module.exports = {architectureDiagram};
