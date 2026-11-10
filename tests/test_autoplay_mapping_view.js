const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const {policySlot, decisionAtFrame, actionLabels} = require('../streaming/web/network.js');
class Node {
  constructor(tag) { this.tag=tag; this.children=[]; this.attrs={}; this.textContent=''; }
  setAttribute(name,value) { this.attrs[name]=String(value); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
  addEventListener() {}
  getContext() { return {clearRect(){}}; }
}
const all=node=>[node,...node.children.flatMap(all)];
const arch=sha256=>({sha256,parameters:434,memory_size:0});
const snapshots=prefix=>[
  {id:'0:start',after_game:0,architecture:arch(prefix+'-initial'),note:prefix+' initial',calls:[]},
  {id:'5:1:0',after_game:5,architecture:arch(prefix+'-old'),note:prefix+' old',calls:[]},
  {id:'10:1:0',after_game:10,architecture:arch(prefix+'-current'),note:prefix+' current',calls:[]},
];
async function check(order, changedAgent) {
  const elements={};
  const context=vm.createContext({console,AbortSignal,policySlot,decisionAtFrame,actionLabels,
    document:{getElementById:id=>elements[id] ||= new Node('div'),createElement:tag=>new Node(tag),
      addEventListener(){},querySelectorAll:()=>[]},
    GameAudio:class {stop(){} async load(){}},attachNetworkTooltips:()=>()=>{},
    agentProgress:()=>'',architectureDiagram:architecture=>{
      const svg=new Node('svg'); svg.architecture=architecture;
      svg.updateActivity=sample=>{svg.sample=sample;}; return svg;
    }});
  const run=code=>vm.runInContext(code,context);
  run(fs.readFileSync('streaming/web/app.js','utf8').split("Promise.all(['/assets")[0]);
  const data={agents:['Astra','Opus 5.5'].map((name,i)=>({agent:{name},snapshots:snapshots(i?'opus':'astra')}))};
  const makeGame=(number,choices)=>({number,player_agents:order,policy_selections:choices,
    networks:order.map(id=>arch((id===1?'astra':'opus')+(choices[id-1] ? '-old':'-current'))),
    frames:[{}],decision_frames:1,activity:[order.map(id=>({action:id===1?12:1}))],audio_url:'fixture.wav'});
  context.data=data;
  context.game=makeGame(50,[null,null]);
  run(`draw=()=>{};updateTally=()=>{};poll=()=>{};
    demo={phase:'playing',paused:true,viewing_game:11,tally:{games:10}};
    autoMode=true; autoSession='fixture'; selected=50; replay=game; frame=1;playing=true;
    let requests=[], deliveries=[];
    post=(path,body)=>{requests.push({path,body});return new Promise(resolve=>deliveries.push(resolve));};
    renderPolicies(data);`);
  const card=i=>elements.replies.children[i];
  const svg=i=>all(card(i)).find(n=>n.tag==='svg');
  const label=i=>all(card(i)).find(n=>n.className==='policy-game').textContent;
  const arrow=(i,direction)=>all(card(i)).find(n=>n.tag==='button' && n.attrs['aria-label']===`${data.agents[i].agent.name}: ${direction} policy update`);
  const other=1-changedAgent, otherHash=svg(other).architecture.sha256;
  assert.equal(label(other),'game 10'); // policy version, never autoplay match 50
  assert.equal(svg(0).sample.action,12);
  assert.equal(svg(1).sample.action,1);
  // A pending training reply may finish while paused. It must not replace the
  // untouched autoplay model or temporarily swap its displayed weights/notes.
  data.agents[other].snapshots.push({id:'11:1:0',after_game:11,
    architecture:arch('newer-training-candidate'),note:'New candidate',calls:[]});
  run('renderPolicies(data)');
  arrow(changedAgent,'previous').onclick();
  assert.equal(run('requests.length'),1);
  const expected=[null,null]; expected[changedAgent]='5:1:0';
  assert.equal(run('JSON.stringify(requests[0].body.policies)'),JSON.stringify(expected));
  assert.equal(svg(other).architecture.sha256,otherHash);
  assert.equal(label(other),'game 10');
  assert.ok(all(card(other)).some(n=>n.textContent===`${other?'opus':'astra'} current`));
  context.response={session:'fixture',game:makeGame(51,expected),tally:{games:0,wins:[0,0],draws:0}};
  run('deliveries[0](response)'); await new Promise(setImmediate);
  assert.equal(svg(other).architecture.sha256,otherHash);
  assert.equal(label(other),'game 10');
  assert.equal(svg(changedAgent).architecture.sha256,(changedAgent?'opus':'astra')+'-old');
  assert.equal(label(changedAgent),'game 5');
  run('frame=1;updatePolicyActivity(1)');
  assert.equal(svg(0).sample.action,12);
  assert.equal(svg(1).sample.action,1);
  // Forward arrow restores only the clicked agent, independent of character slot.
  arrow(changedAgent,'next').onclick();
  assert.equal(run('JSON.stringify(requests[1].body.policies)'),JSON.stringify([null,null]));
  context.response={session:'fixture',game:makeGame(52,[null,null]),tally:{games:0,wins:[0,0],draws:0}};
  run('deliveries[1](response)'); await new Promise(setImmediate);
  assert.equal(svg(other).architecture.sha256,otherHash);
  assert.equal(label(other),'game 10');
  assert.equal(svg(changedAgent).architecture.sha256,(changedAgent?'opus':'astra')+'-current');
}
(async()=>{
  for (const order of [[1,2],[2,1]]) for (const changed of [0,1]) await check(order,changed);
  console.log('Independent history arrows, frozen opponent diagrams, policy labels, and swapped character mapping passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
