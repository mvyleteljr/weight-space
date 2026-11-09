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
from .tool_loop import game_directory
from .transcript import read_replies, reply_lines


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
    parser.add_argument("--game", type=int, default=1, choices=range(1, 10))
    parser.add_argument("--edits", action="store_true", help="Open the latest edit round.")
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
    fighters = [Fighter(FighterState(1, 200, 310, False), [500, 648 / 500, [144 * 500 / 324, 92 * 500 / 324]],
                        pygame.image.load(str(assets / "images/grimes-sprites-large.png")).convert_alpha(), ANIMATION_STEPS[0], None),
                Fighter(FighterState(2, 700, 310, True), [500, 1.5, [224, 194]],
                        pygame.image.load(str(assets / "images/shoggoth-sprites-large.png")).convert_alpha(), ANIMATION_STEPS[1], None)]
    selected_game, edit_after = args.game, 1
    phase, frame, playing, speed = game_directory(selected_game), 0.0, not args.paused, 1.0
    if args.edits:
        phase, playing = "edits", False
    cache, status, poll_time, edit_elapsed = {}, {}, -1000, 0.0
    frames_drawn, screenshot_saved = 0, False
    transcripts, scroll = [[], []], [None, None]
    visible_offsets = [0, 0]
    transcript_round = None

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
            elif event.type == pygame.MOUSEWHEEL and phase == "edits":
                index = 0 if pygame.mouse.get_pos()[0] < 514 else 1
                scroll[index] = max(0, visible_offsets[index] - event.y * 3)
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    playing = not playing
                elif pygame.K_1 <= event.key <= pygame.K_9 or event.key == pygame.K_r:
                    number = 1 if event.key == pygame.K_r else event.key - pygame.K_1 + 1
                    if load_replay(game_directory(number)):
                        selected_game = number
                        phase, frame, playing = game_directory(number), 0.0, True
                elif event.key == pygame.K_e:
                    phase, edit_elapsed = "edits", 0.0
                    edit_after = status.get("editing_after_game", 1)
                    playing = False
                elif event.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET) and phase == "edits":
                    edit_after = max(1, min(status.get("editing_after_game", 1),
                                           edit_after + (1 if event.key == pygame.K_RIGHTBRACKET else -1)))
                    playing, edit_elapsed = False, 0.0
                elif event.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN) and phase == "edits":
                    scroll = [max(0, offset + (-8 if event.key == pygame.K_PAGEUP else 8)) for offset in visible_offsets]
                elif event.key == pygame.K_END and phase == "edits":
                    scroll = [None, None]
                elif event.key == pygame.K_RIGHT:
                    speed = min(4.0, speed * 2)
                elif event.key == pygame.K_LEFT:
                    speed = max(0.25, speed / 2)
        now = pygame.time.get_ticks()
        if now - poll_time >= 500:
            poll_time = now
            if (args.demo / "demo.json").exists():
                status = read_json(args.demo / "demo.json")
                if frames_drawn == 0 and args.edits:
                    edit_after = status.get("editing_after_game", 1)
                pygame.display.set_caption("Weight Space | " + " vs ".join(a["name"] for a in status.get("agents", [])))
            if phase == "edits":
                if transcript_round != edit_after:
                    scroll, transcript_round = [None, None], edit_after
                directory = args.demo if edit_after == 1 else args.demo / f"edit-{edit_after}"
                transcripts = [reply_lines(read_replies(directory / f"lab-{i + 1}")) for i in range(2)]
        screen.fill((15, 20, 32))
        replay = load_replay(phase) if phase != "edits" else None
        if replay:
            game_info = next((g for g in status.get("games", []) if g["number"] == selected_game), {})
            order = game_info.get("player_agents", [1, 2])
            agent_names = [agent["name"] for agent in status.get("agents", [])]
            names = [agent_names[i - 1] if i <= len(agent_names) else f"PLAYER {i}" for i in order]
            rows = replay["frames"]
            index = min(int(frame), len(rows))
            state = replay["manifest"]["initial_state"] if index == 0 else rows[index - 1]["state"]
            stage.blit(background, (0, 0))
            for i in (1, 0):
                fighter = fighters[i]
                fighter.state = FighterState(**state["fighters"][i])
                fighter.draw(stage)
                x = 24 if i == 0 else 666
                pygame.draw.rect(stage, (35, 35, 45), (x, 52, 310, 20))
                pygame.draw.rect(stage, (70, 190, 230) if i == 0 else (215, 115, 230),
                                 (x, 52, 310 * fighter.health / 100, 20))
                label(names[i].upper() if i < len(names) else f"PLAYER {i + 1}", x, 20, 32, surface=stage)
                label(f"HP {fighter.health}", x, 78, 22, surface=stage)
            remaining = max(0, (state["max_steps"] - state["step"]) / 60)
            label(f"{remaining:04.1f}s", 450, 30, 32, surface=stage)
            screen.blit(stage, (0, 0))
            title = "GAME 1 | Identical random weights" if selected_game == 1 else f"GAME {selected_game} | After direct weight edits"
            if status.get("swap_sides"):
                revision = (selected_game - 1) // 2 if status.get("paired_games", True) else selected_game - 1
                title = f"GAME {selected_game} | Revision {revision} | " + ("Swapped characters" if selected_game % 2 == 0 else "First assignment")
            label(title, 24, 620, 32)
            if state["done"]:
                winner = state["winner"]
                outcome = "DRAW" if winner is None else names[winner - 1].upper() + " WINS"
                label(f"{outcome} | {state['reason'].replace('_', ' ')}", 24, 658, 26)
                if selected_game < status.get("games_requested", 2) and playing:
                    frame += dt * 60
                    if frame >= len(rows) + 120:
                        if status.get("swap_sides") and status.get("paired_games", True) and selected_game % 2:
                            if load_replay(game_directory(selected_game + 1)):
                                selected_game += 1
                                phase, frame = game_directory(selected_game), 0.0
                        else:
                            phase, edit_elapsed, edit_after = "edits", 0.0, selected_game
            else:
                label("Both policies use the same game state. Only validated network data is accepted.", 24, 658, 22)
                if playing:
                    frame = min(len(rows), frame + dt * 60 * speed)
        elif phase == "edits":
            label(f"WEIGHT EDITS | After game {edit_after}", 24, 28, 44)
            label("Each agent can inspect the last game, edit weights, and test inputs.", 24, 78, 22)
            edit_agents = next((entry["agents"] for entry in status.get("edit_rounds", [])
                                if entry["after_game"] == edit_after), status.get("agents", []))
            for index, agent in enumerate(edit_agents):
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
                lines = transcripts[index] or [agent.get("reason", "Waiting for the first reply...")]
                if agent.get("error"):
                    lines = lines + ["ERROR: " + agent["error"]]
                wrapped = [part for line in lines for part in (textwrap.wrap(line, 47) or [""])]
                limit = max(0, len(wrapped) - 12)
                offset = limit if scroll[index] is None else min(scroll[index], limit)
                visible_offsets[index] = offset
                for line_index, line in enumerate(wrapped[offset:offset + 12]):
                    label(line, x + 16, 318 + line_index * 22, 22)
                label(f"Lines {offset + 1}-{min(len(wrapped), offset + 12)} / {len(wrapped)} | Wheel: scroll", x + 16, 590, 22, (150, 165, 185))
                # Follow new replies only when the user has not scrolled away from the end.
                if scroll[index] is not None and scroll[index] >= limit:
                    scroll[index] = None
            label("Reply notes and tool results | [ ]: edit round | PgUp/PgDn: scroll | End: latest", 24, 640, 22)
            if load_replay(game_directory(edit_after + 1)) and playing:
                edit_elapsed += dt
                label(f"Game {edit_after + 1} starts in {max(0, 12 - int(edit_elapsed))}s. Space pauses.", 24, 676, 26)
                if edit_elapsed >= 12:
                    selected_game = edit_after + 1
                    phase, frame = game_directory(selected_game), 0.0
            elif status.get("phase") == "failed":
                label("Submission failed. Completed games can still be replayed.", 24, 676, 26)
        else:
            label("Preparing the shared initial network...", 24, 280, 32)
        label(f"Space: pause | 1-9: select game | E: edits | R: restart | arrows: speed {speed:g}x", 24, 728, 22)
        footer = "REPLY NOTES UPDATE AFTER EACH RESPONSE" if phase == "edits" else "REPLAY OF RECORDED GAME STATES"
        label(footer + (" | PAUSED" if not playing else ""), 24, 756, 22, (150, 165, 185))
        pygame.display.flip()
        if publisher:
            publisher.capture(screen)
        frames_drawn += 1
        if args.screenshot and not screenshot_saved and (replay or phase == "edits"):
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
