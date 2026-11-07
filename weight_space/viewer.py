"""View saved Street Fighter matches. No model code or provider calls run here."""

import atexit
import logging
import os
import signal
import argparse
import json
from pathlib import Path
import textwrap
import time

import pygame

from Street_Fighter.src.arena import FighterState, ANIMATION_STEPS
from Street_Fighter.src.fighter import Fighter
from Street_Fighter.src.streaming import FramePublisher, StreamConfig


def read_json(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", type=Path, required=True)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--paused", action="store_true", help="Wait for Space before playback.")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--stream", metavar="RTSP_URL", help="Broadcast this weight-editing viewer to spectators")
    parser.add_argument("--stream-fps", type=int, choices=(30, 60), default=30)
    parser.add_argument("--headless", action="store_true", help="Render without a desktop window")
    args = parser.parse_args()
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    def shutdown(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1000, 780))
    pygame.display.set_caption("Weight Space | Match viewer")
    stage = pygame.Surface((1000, 600))
    clock = pygame.time.Clock()
    publisher = None
    if args.stream:
        try:
            publisher = FramePublisher(StreamConfig(args.stream, args.stream_fps), screen.get_size())
        except (ValueError, RuntimeError) as error:
            parser.error(str(error))
        atexit.register(publisher.close)
    assets = Path(__file__).resolve().parent.parent / "Street_Fighter/assets"
    background = pygame.transform.smoothscale(pygame.image.load(str(assets / "images/bg1.jpg")), (1000, 600))
    fonts = {size: pygame.font.Font(None, size) for size in (22, 26, 32, 44)}
    fighters = [Fighter(FighterState(1, 200, 310, False), [162, 4, [72, 46]],
                        pygame.image.load(str(assets / "images/warrior.png")).convert_alpha(), ANIMATION_STEPS[0], None),
                Fighter(FighterState(2, 700, 310, True), [250, 3, [112, 97]],
                        pygame.image.load(str(assets / "images/wizard.png")).convert_alpha(), ANIMATION_STEPS[1], None)]
    phase, frame, playing, speed = "before", 0.0, not args.paused, 1.0
    cache, status, poll_time, edit_elapsed = {}, {}, -1000, 0.0
    frames_drawn, screenshot_saved = 0, False

    def label(text, x, y, size=26, color=(235, 240, 248), surface=screen):
        surface.blit(fonts[size].render(str(text), True, color), (x, y))

    def load_replay(name):
        directory = args.demo / name
        if name not in cache and (directory / "result.json").exists():
            cache[name] = {"manifest": read_json(directory / "manifest.json"),
                           "result": read_json(directory / "result.json"),
                           "frames": [read_json_line(line) for line in (directory / "steps.jsonl").read_text().splitlines()]}
        return cache.get(name)

    running = True
    while running:
        dt = min(clock.tick(60) / 1000, 0.1)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    playing = not playing
                elif event.key in (pygame.K_1, pygame.K_r):
                    phase, frame, playing = "before", 0.0, True
                elif event.key == pygame.K_2 and load_replay("after"):
                    phase, frame, playing = "after", 0.0, True
                elif event.key == pygame.K_e:
                    phase, edit_elapsed = "edits", 0.0
                    playing = False
                elif event.key == pygame.K_RIGHT:
                    speed = min(4.0, speed * 2)
                elif event.key == pygame.K_LEFT:
                    speed = max(0.25, speed / 2)
        now = pygame.time.get_ticks()
        if now - poll_time >= 500:
            poll_time = now
            if (args.demo / "demo.json").exists():
                status = read_json(args.demo / "demo.json")
                pygame.display.set_caption("Weight Space | " + " vs ".join(a["name"] for a in status.get("agents", [])))
        screen.fill((15, 20, 32))
        replay = load_replay(phase) if phase in ("before", "after") else None
        if replay:
            rows = replay["frames"]
            index = min(int(frame), len(rows))
            state = replay["manifest"]["initial_state"] if index == 0 else rows[index - 1]["state"]
            stage.blit(background, (0, 0))
            for i, fighter in enumerate(fighters):
                fighter.state = FighterState(**state["fighters"][i])
                fighter.draw(stage)
                x = 24 if i == 0 else 666
                pygame.draw.rect(stage, (35, 35, 45), (x, 52, 310, 20))
                pygame.draw.rect(stage, (70, 190, 230) if i == 0 else (215, 115, 230),
                                 (x, 52, 310 * fighter.health / 100, 20))
                names = [agent["name"] for agent in status.get("agents", [])]
                label(names[i].upper() if i < len(names) else f"PLAYER {i + 1}", x, 20, 32, surface=stage)
                label(f"HP {fighter.health}", x, 78, 22, surface=stage)
            remaining = max(0, (state["max_steps"] - state["step"]) / 60)
            label(f"{remaining:04.1f}s", 450, 30, 32, surface=stage)
            screen.blit(stage, (0, 0))
            title = "GAME 1 | Identical random weights" if phase == "before" else "GAME 2 | After direct weight edits"
            label(title, 24, 620, 32)
            if state["done"]:
                winner = state["winner"]
                outcome = "DRAW" if winner is None else names[winner - 1].upper() + " WINS"
                label(f"{outcome} | {state['reason'].replace('_', ' ')}", 24, 658, 26)
                if phase == "before" and playing:
                    frame += dt * 60
                    if frame >= len(rows) + 120:
                        phase, edit_elapsed = "edits", 0.0
            else:
                label("Both policies use the same game state. Only validated network data is accepted.", 24, 658, 22)
                if playing:
                    frame = min(len(rows), frame + dt * 60 * speed)
        elif phase == "edits":
            label("DIRECT WEIGHT EDITS", 24, 28, 44)
            label("Each agent can inspect game 1, edit weights, and test inputs before submission.", 24, 78, 22)
            for index, agent in enumerate(status.get("agents", [])):
                x = 24 + index * 490
                pygame.draw.rect(screen, (28, 37, 55), (x, 120, 462, 495), border_radius=12)
                label(agent["name"], x + 16, 140, 32)
                agent_status = "WAITING FOR RESPONSE" if agent["status"] in ("editing", "request_pending") else agent["status"].upper().replace("_", " ")
                label(agent_status, x + 16, 182, 26, (100, 210, 180))
                if "changed_parameters" in agent:
                    label(f"{agent['changed_parameters']} / {agent['total_parameters']} parameters changed", x + 16, 218, 22)
                if "tool_calls" in agent:
                    label(f"Revision {agent.get('revision', 0)} | Calls {agent['tool_calls']} | Tests {agent.get('test_cases', 0)}", x + 16, 252, 22)
                    detail = "Last tool: " + agent.get("last_tool", "none")
                    if agent["status"] == "request_pending":
                        elapsed = max(0, int(time.time() - agent["request_started_at"]))
                        detail = f"Reply {agent.get('turn', 1)} | Waiting {elapsed}s / {agent['reply_timeout']:.0f}s limit"
                    label(detail, x + 16, 282, 22)
                reason = agent.get("reason", agent.get("error", "Waiting for the agent's submission..."))
                for line_index, line in enumerate(textwrap.wrap(reason, 48)[:10]):
                    label(line, x + 16, 322 + line_index * 26, 22)
            label("Input tests show actions and activations. They do not use an opponent.", 24, 640, 22)
            if status.get("phase") == "complete" and playing:
                edit_elapsed += dt
                label(f"Game 2 starts in {max(0, 12 - int(edit_elapsed))}s. Space pauses.", 24, 676, 26)
                if edit_elapsed >= 12:
                    phase, frame = "after", 0.0
            elif status.get("phase") == "failed":
                label("Submission failed. Game 1 can still be replayed.", 24, 676, 26)
        else:
            label("Preparing the shared initial network...", 24, 280, 32)
        label(f"Space: pause | 1: game 1 | 2: game 2 | E: edits | R: restart | arrows: speed {speed:g}x", 24, 728, 22)
        label("REPLAY OF RECORDED GAME STATES" + (" | PAUSED" if not playing else ""), 24, 756, 22, (150, 165, 185))
        pygame.display.flip()
        if publisher:
            publisher.capture(screen)
        frames_drawn += 1
        if args.screenshot and not screenshot_saved and replay:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(screen, str(args.screenshot))
            screenshot_saved = True
        if args.smoke_test and frames_drawn >= 3:
            running = False
    if publisher:
        publisher.close()
    pygame.quit()


def read_json_line(line):
    return json.loads(line)


if __name__ == "__main__":
    main()
