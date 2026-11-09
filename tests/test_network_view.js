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
assert.equal(nodes[5].attrs.fill,'rgb(255, 255, 255)'); // signed logits retain magnitude
assert.equal(nodes[6].attrs['stroke-width'],'1.5'); // chosen action outlined, not recolored
assert.match(nodes[5].attrs['aria-label'],/-3/);
assert.equal(edges[6].children[0].attrs.stroke,'rgb(32, 32, 32)'); // weight 1 × activation 0
assert.equal(edges[7].children[0].attrs.stroke,'rgb(240, 240, 240)');
assert.match(edges[7].children[1].attrs['aria-label'],/weight|W\[0\]\[1\] = 4/);
assert.match(edges[7].children[1].attrs['aria-label'],/source = 4 · signal = 16/);
svg.updateActivity({values:[[0,0,0],[0,0],[0,0]],action:0});
assert.ok(nodes.every(n=>n.attrs.fill==='rgb(0, 0, 0)'));
assert.ok(edges.every(e=>e.children[0].attrs.stroke==='rgb(32, 32, 32)'));
svg.updateActivity(null);
assert.equal(svg.attrs['data-activity'],'weights');
assert.ok(nodes.every(n=>/no current decision/.test(n.attrs['aria-label'])));
console.log('Complete connections and normalized live-activation tests passed.');
