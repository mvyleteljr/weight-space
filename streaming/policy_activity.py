"""Reconstruct recorded policy decisions for display; never change game evidence."""
from weight_space.network import forward


def recorded_activity(models, rows, stride=1):
    memory = [None, None]
    samples = []
    for index, row in enumerate(rows):
        decisions = []
        for player, model in enumerate(models):
            trace = forward(model, row['observations'][player], memory=memory[player], return_trace=True)
            memory[player] = trace['memory_after']
            action = max(range(len(trace['outputs'])), key=trace['outputs'].__getitem__)
            if action != row['actions'][player]:
                raise ValueError('Saved policy does not match the recorded action.')
            if index % stride == 0:
                state = row.get('state')
                dx = (state['fighters'][player]['x'] - row['observations'][player][0] * state['width']) if state else 0
                decisions.append({'motion': 'right' if dx > 1e-7 else 'left' if dx < -1e-7 else 'still',
                                  'values': [trace['inputs']] + [layer['outputs'] for layer in trace['layers']],
                                  'action': action})
        if decisions:
            samples.append(decisions)
    return samples
