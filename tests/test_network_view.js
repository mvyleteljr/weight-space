const assert=require('node:assert/strict');
class Node {constructor(tag){this.tag=tag;this.attrs={};this.children=[];this.style={};this.events={};}setAttribute(k,v){this.attrs[k]=v;}append(n){this.children.push(n);}replaceChildren(){this.children=[];}addEventListener(k,f){this.events[k]=f;}}
global.document={createElementNS:(_,tag)=>new Node(tag)};
const {architectureDiagram}=require('../streaming/web/network.js');
const model={inputs:3,layers:[{width:2,type:'dense',activation:'relu',biases:[0,0],parameters:8,connections:[{from:0,to:0,weight:-1},{from:1,to:0,weight:2},{from:2,to:1,weight:0}]},{width:2,type:'recurrent',activation:'linear',biases:[0,0],parameters:10,connections:[{from:0,to:0,weight:1},{from:1,to:0,weight:4}]}]};
const svg=architectureDiagram(model);
const all=n=>[n,...n.children.flatMap(all)];
let nodes=all(svg).filter(n=>n.tag==='circle');
assert.equal(nodes.length,7); // every neuron, including both recurrent outputs
assert.equal(nodes.filter(n=>n.attrs['aria-pressed']==='true').length,1);
assert.ok(all(svg).some(n=>n.attrs['aria-label']==='L1 W[0][1] = 4'));
nodes[3].events.click();
assert.equal(nodes[3].attrs['aria-pressed'],'true');
assert.ok(all(svg).some(n=>n.attrs['aria-label']==='L0 W[0][0] = -1'));
assert.ok(all(svg).some(n=>n.attrs.stroke==='rgb(240, 240, 240)'));
assert.ok(!svg.events.mouseleave); // selection stays while inspecting a line
console.log('Network view tests passed.');
