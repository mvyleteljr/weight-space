const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const elements={};
const element=id=>elements[id] ||= {textContent:'',disabled:false,setAttribute(){},listeners:{},addEventListener(name,fn){this.listeners[name]=fn;},replaceChildren(){},getContext:()=>({clearRect(){}})};
class Audio {unlock(){} stop(){} reset(){} async load(){} sync(){}}
const context=vm.createContext({document:{getElementById:element,addEventListener(){}},GameAudio:Audio,
 attachNetworkTooltips:()=>()=>{},console,AbortSignal});
const run=code=>vm.runInContext(code,context);
run(fs.readFileSync('streaming/web/app.js','utf8').split("Promise.all(['/assets")[0]);
run(`const realPoll=poll; poll=()=>{}; draw=()=>{}; renderPolicies=()=>{}; updateTally=()=>{};
 runToken='test'; demo={phase:'ready',paused:false};canStart=true;syncControls();`);
assert.equal(elements.start.textContent,'Start training');
assert.equal(elements.autoplay.disabled,true);
assert.equal(elements.autoplay.textContent,'Start autoplay');
run(`demo={phase:'playing',paused:false}; syncControls();`);
assert.equal(elements.start.textContent,'Pause training');
assert.equal(elements.autoplay.disabled,true);
(async()=>{
 run(`post=async(path)=>({run:'run'});`);
 await run(`control('/api/pause')`);
 assert.equal(elements.start.textContent,'Start training');
 assert.equal(elements.autoplay.disabled,false);
 run(`replay={number:5,audio_url:'training.wav'};selected=5;frame=123;playing=true;
 post=async(path)=>({session:'auto',tally:{games:0,wins:[0,0],draws:0},game:{number:1,audio_url:'auto.wav'}});`);
 await run('autoplayGame()');
 assert.equal(run('autoMode'),true);
 assert.equal(run('demo.paused'),true);
 assert.equal(run('replay.number'),1);
 assert.equal(elements.autoplay.disabled,false);
 assert.equal(elements.autoplay.textContent,'Stop autoplay');
 // Stop returns to the paused training frame and releases only this session.
 run(`let stoppedSessions=[];post=async(path,body)=>{if(path==='/api/autoplay-stop')stoppedSessions.push(body.session);return {};};`);
 elements.autoplay.listeners.click();
 assert.equal(run('autoMode'),false);
 assert.equal(run('demo.paused'),true);
 assert.equal(run('frame'),123);
 assert.equal(run('replay.number'),5);
 assert.equal(run('stoppedSessions[0]'),'auto');
 assert.equal(elements.autoplay.textContent,'Start autoplay');
 assert.equal(elements.autoplay.disabled,false);
 run(`post=async()=>({session:'auto-2',tally:{games:0,wins:[0,0],draws:0},game:{number:1,audio_url:'auto.wav'}});`);
 await run('autoplayGame()');
 run(`post=async(path)=>({run:'run'});`);
 await run(`control('/api/resume')`);
 assert.equal(run('autoMode'),false);
 assert.equal(run('frame'),123);
 assert.equal(run('replay.number'),5);
 assert.equal(elements.start.textContent,'Pause training');
 assert.equal(elements.autoplay.disabled,true);
 // Stop works while the first game is still being generated, and ignores its late reply.
 await run(`control('/api/pause')`);
 run(`let finishStart;post=()=>new Promise(resolve=>{finishStart=resolve});`);
 const starting=run('autoplayGame()');
 assert.equal(elements.autoplay.disabled,false);
 assert.equal(elements.autoplay.textContent,'Stop autoplay');
 elements.autoplay.listeners.click();
 run(`post=async(path,body)=>{if(path==='/api/autoplay-stop')stoppedSessions.push(body.session);return {};};
   finishStart({session:'stopped-during-start',game:{number:99}});`);
 await starting;
 assert.equal(run('autoMode'),false);
 assert.equal(run('frame'),123);
 assert.equal(run('replay.number'),5);
 assert.equal(run('stoppedSessions.at(-1)'),'stopped-during-start');
 // Reset during an in-flight autoplay response must not revive autoplay.
 await run(`control('/api/pause')`);
 run(`let deliver; post=()=>new Promise(resolve=>{deliver=resolve});`);
 const pending=run('autoplayGame()');
 run(`post=async()=>({run:'new-run'});`);
 await run(`control('/api/reset')`);
 run(`deliver({session:'late',game:{number:99},tally:{games:99}});`);
 await pending;
 assert.equal(run('autoMode'),false);
 assert.equal(run('replay'),null);
 assert.equal(run('autoSession'),null);
 assert.equal(elements.autoplay.disabled,true);
 // Completed sessions used to strand both controls in the disabled state.
 run(`demo={phase:'complete',paused:false}; canStart=true; syncControls();`);
 assert.equal(elements.start.textContent,'Start training');
 assert.equal(elements.start.disabled,false);
 assert.equal(elements.autoplay.disabled,false);
 run(`post=async()=>({session:'finished-auto',tally:{games:0,wins:[0,0],draws:0},game:{number:1,audio_url:'auto.wav'}});`);
 await run('autoplayGame()');
 assert.equal(run('autoMode'),true);
 run(`post=async()=>({run:'same-run'});`);
 await run(`control('/api/runs')`);
 assert.equal(run('autoMode'),false);
 assert.equal(elements.start.textContent,'Pause training');
 assert.equal(elements.autoplay.disabled,true);
 // History arrows outside autoplay are view-only.
 run(`let requests=[]; post=async(path,body)=>{requests.push({path,body});}; selectPolicy(0,'0:start');`);
 assert.equal(run('requests.length'),0);
 // During autoplay, rapid clicks are serialized and the final pair wins.
 run(`demo={phase:'complete',paused:false};canStart=true;
   post=async()=>({session:'history-auto',game:{number:1,audio_url:'auto.wav',policy_selections:[null,null]},tally:{games:0,wins:[0,0],draws:0}});`);
 await run('autoplayGame()');
 run(`let deliveries=[]; requests=[];
   post=(path,body)=>{requests.push({path,body});return new Promise(resolve=>deliveries.push(resolve));};
   selectPolicy(0,'1:1:0');selectPolicy(0,'0:start');selectPolicy(1,'0:start');`);
 assert.equal(run('requests.length'),1);
 assert.equal(run('requests[0].path'),'/api/autoplay-policies');
 assert.equal(run('playing'),false);
 run(`deliveries[0]({session:'history-auto',game:{number:2,audio_url:'old.wav',policy_selections:['1:1:0',null]}});`);
 await new Promise(setImmediate);
 assert.equal(run('requests.length'),2);
 assert.equal(run('requests[1].body.after'),2);
 assert.equal(run('JSON.stringify(requests[1].body.policies)'),JSON.stringify(['0:start','0:start']));
 run(`deliveries[1]({session:'history-auto',game:{number:3,audio_url:'selected.wav',policy_selections:['0:start','0:start']},tally:{games:0,wins:[0,0],draws:0}});`);
 await new Promise(setImmediate);
 assert.equal(run('replay.number'),3);
 assert.equal(run('playing'),true);
 run(`selectPolicy(0,null);`);
 assert.equal(run('JSON.stringify(requests[2].body.policies)'),JSON.stringify([null,'0:start']));
 // Reset while an arrow change is pending cannot revive that game.
 run(`post=async()=>({run:'new-run'});`);
 await run(`control('/api/reset')`);
 run(`deliveries[2]({session:'history-auto',game:{number:4}});`);
 await new Promise(setImmediate);
 assert.equal(run('autoMode'),false);
 assert.equal(run('replay'),null);
 assert.equal(run('JSON.stringify(historySelection)'),JSON.stringify([null,null]));
 // A continued run must load its next live game, even if the last finished
 // game remains on screen with playback stopped.
 run(`activeRun='same-run'; selected=7; replay={number:7}; playing=false;
   get=async(url)=>url==='/api/run' ? {run:'same-run',run_token:'test',can_start:false,
     demo:{phase:'playing',viewing_game:8,games:[{number:8}]}} : {};
   selectGame=async(number,autoplay)=>{selected=number;playing=autoplay;};`);
 await run('realPoll()');
 assert.equal(run('selected'),8);
 assert.equal(run('playing'),true);
 console.log('Training/autoplay controls, frame preservation, and reset race tests passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
