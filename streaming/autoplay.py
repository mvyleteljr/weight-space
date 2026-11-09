"""Frozen-policy exhibition games. This module never imports or calls an LLM."""
import json
from pathlib import Path
import secrets
import shutil

from weight_space.game import match
from weight_space.network import load, save
from weight_space.checkpoint import current_models


class Autoplay:
    def __init__(self, directory, status):
        from streaming.server import ReplayStore
        self.directory = Path(directory) / ('autoplay-' + secrets.token_hex(6))
        self.directory.mkdir()
        self.id = self.directory.name
        self.default_models = [load(path) for path in current_models(directory, status)]
        for i, model in enumerate(self.default_models, 1):
            save(self.directory / f'agent-{i}.json', model)
        self.history = ReplayStore(directory)
        self.selections = [None, None]
        self.store = ReplayStore(self.directory)
        self.status = {'games': [], 'tally': {'wins': [0, 0], 'draws': 0, 'games': 0}}
        self.number = 0
        self.latest = None

    def next(self, after, policies=None):
        if type(after) is not int or after < 0:
            raise ValueError('Invalid autoplay game number.')
        if policies is not None and (not isinstance(policies, list) or len(policies) != 2 or any(
            p is not None and (not isinstance(p, str) or len(p) > 100) for p in policies
        )):
            raise ValueError('Supply two policy selections.')
        if self.latest and after == self.number - 1:
            if policies is not None and policies != self.selections:
                raise ValueError('Policy selection is out of sequence.')
            return self.latest  # Network retries must not skip games.
        if after != self.number:
            raise ValueError('Autoplay game is out of sequence.')
        if policies is not None:
            if self.latest and policies == self.selections:
                return self.latest
            # Resolve and validate both before changing either network.
            latest = current_models(self.history.directory, self.history.status())
            models = [load(self.directory / f'agent-{i+1}.json') if selection == self.selections[i]
                      else load(latest[i]) if selection is None else self.history.policy_model(i, selection)
                      for i, selection in enumerate(policies)]
            for i, model in enumerate(models, 1):
                save(self.directory / f'agent-{i}.json', model)
            self.selections = list(policies)
        tally = self.status['tally']
        if self.number and policies is None:
            previous = self.status['games'][-1]
            winner = previous['result']['winner']
            if winner is None:
                tally['draws'] += 1
            else:
                tally['wins'][previous['player_agents'][winner-1]-1] += 1
            tally['games'] += 1
        number = self.number + 1
        name = {1:'before', 2:'after'}.get(number, f'game-{number}')
        # An arrow click restarts this matchup; it doesn't score an unfinished game.
        order = (self.latest['game']['player_agents'] if policies is not None and self.latest
                 else [2,1] if secrets.randbits(1) else [1,2])
        result = match(*(self.directory / f'agent-{i}.json' for i in order), self.directory / name, max_steps=1800)
        self.status['games'].append({'number':number,'result':result,'player_agents':order})
        (self.directory / 'demo.json').write_text(json.dumps(self.status))
        data = self.store.game(number)
        data['policy_selections'] = list(self.selections)
        data['audio_url'] = f'/api/autoplay/audio.wav?session={self.id}&game={number}'
        self.latest = {'session':self.id,'game':data,'tally':json.loads(json.dumps(tally))}
        self.number = number
        # Keep disk and RAM bounded for indefinitely running exhibitions.
        if number > 2:
            old = number - 2
            shutil.rmtree(self.directory / {1:'before',2:'after'}.get(old,f'game-{old}'))
            self.store.cache.pop(old, None)
            self.status['games'] = self.status['games'][-2:]
        return self.latest
