const assert=require('node:assert/strict');
class Node {constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.style={};}setAttribute(k,v){this.attrs[k]=String(v);}append(n){this.children.push(n);}}
global.document={createElementNS:(_,tag)=>new Node(tag)};
const {architectureDiagram}=require('../streaming/web/network.js');
const model={inputs:3,layers:[{width:2,type:'dense',activation:'relu',biases:[0,0],connections:[
  {from:0,to:0,weight:-1},{from:1,to:0,weight:2},{from:2,to:0,weight:.5},
  {from:0,to:1,weight:0},{from:1,to:1,weight:0},{from:2,to:1,weight:-4}]},
  {width:2,type:'dense',activation:'linear',biases:[0,0],connections:[
  {from:0,to:0,weight:1},{from:1,to:0,weight:4},{from:0,to:1,weight:-2},{from:1,to:1,weight:0}]}]};
const svg=architectureDiagram(model);
const all=n=>[n,...n.children.flatMap(all)];
const nodes=all(svg).filter(n=>n.tag==='circle'), edges=all(svg).filter(n=>n.attrs.class==='network-edge');
assert.equal(nodes.length,7);
assert.equal(edges.length,10); // all 3×2 and 2×2 connections, including zero weights
assert.equal(all(svg).filter(n=>n.tag==='path').length,20); // no horizontal filler bars
assert.ok(nodes.every(n=>n.attrs.fill==='rgb(0, 0, 0)'));
const count=all(svg).length;
svg.updateActivity({values:[[0,2,-1],[0,4],[-3,2]],action:1});
assert.equal(all(svg).length,count); // update values without rebuilding the topology
assert.equal(nodes[0].attrs.fill,'rgb(0, 0, 0)');
assert.equal(nodes[1].attrs.fill,'rgb(255, 255, 255)');
assert.equal(nodes[2].attrs.fill,'rgb(140, 140, 140)');
assert.equal(nodes[3].attrs.fill,'rgb(0, 0, 0)'); // inactive ReLU
assert.equal(nodes[4].attrs.fill,'rgb(255, 255, 255)');
assert.equal(nodes[5].attrs.fill,'rgb(0, 0, 0)'); // negative logits no longer look preferred
assert.equal(nodes[6].attrs['stroke-width'],'2'); // chosen action outlined, not recolored
assert.equal(nodes[0].attrs['aria-label'],'Self: Horizontal position');
assert.equal(nodes[5].attrs['aria-label'],'Idle');
assert.equal(nodes[6].attrs['aria-label'],'Move left');
assert.equal(nodes[4].attrs['aria-label'],'Layer 1 neuron 2: 4');
assert.ok(nodes.every(n=>n.children.every(c=>c.tag!=='title'))); // no delayed native tooltips
assert.equal(edges[6].children[0].attrs.stroke,'rgb(32, 32, 32)'); // weight 1 × activation 0
assert.equal(edges[7].children[0].attrs.stroke,'rgb(240, 240, 240)');
assert.match(edges[7].children[1].attrs['aria-label'],/weight|W\[0\]\[1\] = 4/);
assert.match(edges[7].children[1].attrs['aria-label'],/source = 4 · signal = 16/);
svg.updateActivity({values:[[0,0,0],[0,0],[0,0]],action:0});
assert.ok(nodes.every(n=>n.attrs.fill==='rgb(0, 0, 0)'));
assert.ok(edges.every(e=>e.children[0].attrs.stroke==='rgb(32, 32, 32)'));
svg.updateActivity(null);
assert.equal(svg.attrs['data-activity'],'weights');
assert.equal(nodes[0].attrs['aria-label'],'Self: Horizontal position');
assert.equal(nodes[5].attrs['aria-label'],'Idle');
assert.match(nodes[3].attrs['aria-label'],/no current decision/);
console.log('Complete connections and normalized live-activation tests passed.');

const {attachNetworkTooltips, inputLabels, actionLabels}=require('../streaming/web/network.js');
assert.equal(inputLabels.length,33);
assert.equal(inputLabels[3],'Self: Health level');
assert.equal(inputLabels[17],'Opponent: Health level');
assert.equal(actionLabels.length,18);
assert.equal(actionLabels[17],'Move right + Jump + Attack 2');
const feedback=architectureDiagram({...model,action_feedback:true});
assert.equal(all(feedback).filter(n=>n.tag==='circle')[2].attrs['aria-label'],'Previous action');
const handlers={};
const root={addEventListener:(name,fn)=>{handlers[name]=fn;},contains:()=>true};
global.window={innerWidth:800,innerHeight:600,addEventListener:()=>{}};
global.document.createElement=tag=>new Node(tag);
global.document.body=new Node('body');
Node.prototype.getBoundingClientRect=()=>({right:100,bottom:100,width:200,height:25});
Node.prototype.removeAttribute=function(name){delete this.attrs[name];};
Node.prototype.getAttribute=function(name){return this.attrs[name];};
const refresh=attachNetworkTooltips(root), tip=document.body.children[0];
const neuron=nodes[4]; neuron.isConnected=true; neuron.closest=()=>neuron;
handlers.pointerover({target:neuron,clientX:790,clientY:590});
assert.equal(tip.hidden,false); // synchronous: no timer or browser tooltip delay
assert.equal(tip.textContent,neuron.attrs['aria-label']);
assert.equal(tip.style.left,'592px'); // stay in viewport
assert.equal(tip.style.top,'557px');
neuron.setAttribute('aria-label','Layer 1 neuron 2: 0.75'); refresh();
assert.equal(tip.textContent,'Layer 1 neuron 2: 0.75');
handlers.pointerout(); assert.equal(tip.hidden,true);
handlers.focusin({target:neuron}); assert.equal(tip.hidden,false);
handlers.keydown({key:'Escape'}); assert.equal(tip.hidden,true);
handlers.pointerover({target:neuron,clientX:10,clientY:10});
neuron.isConnected=false; refresh(); assert.equal(tip.hidden,true);
console.log('Semantic neuron labels and immediate tooltip tests passed.');

const {policySlot, decisionAtFrame}=require('../streaming/web/network.js');
const recorded={player_agents:[2,1],decision_frames:2,activity_stride:1,
  activity:[[{action:1},{action:12}],[{action:12},{action:1}]]};
assert.equal(policySlot(recorded,1),0); // Opus is Grimes when swapped
assert.equal(policySlot(recorded,0),1);
assert.equal(decisionAtFrame(recorded,1,policySlot(recorded,1)).action,1);
assert.equal(decisionAtFrame(recorded,2,policySlot(recorded,1)).action,12);
assert.equal(decisionAtFrame(recorded,0,0),null); // before first decision
assert.equal(decisionAtFrame(recorded,3,0),null); // death animation is not a decision
assert.equal(decisionAtFrame({...recorded,activity_stride:2},2,0),null);
for(const outputs of [[-100,2],[-100,-1],[2,2]]) {
  const action=outputs.indexOf(Math.max(...outputs));
  svg.updateActivity({values:[[0,0,0],[0,0],outputs],action});
  assert.equal(nodes[5+action].attrs.fill,'rgb(255, 255, 255)');
  assert.equal(nodes[5+action].attrs['data-selected'],'true');
  assert.equal(nodes[5+action].attrs.r,'3.5');
}
console.log('Signed action scores, character swaps and exact frame alignment tests passed.');
