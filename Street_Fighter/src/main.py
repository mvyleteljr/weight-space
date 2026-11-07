import argparse
import atexit
import logging
import os
import signal
import math
import pygame
from pygame import mixer
from pygame import font
import sys
from pathlib import Path

if __package__:
    from .fighter import Fighter
    from .arena import Arena, encode_action
    from .streaming import FramePublisher, StreamConfig
    from .scripted_demo import scripted_actions
else:
    from fighter import Fighter
    from arena import Arena, encode_action
    from streaming import FramePublisher, StreamConfig
    from scripted_demo import scripted_actions

def build_parser():
    parser = argparse.ArgumentParser(description="Street Fighter keyboard play, scripted demo and spectator streaming")
    parser.add_argument("--demo", action="store_true", help="Run repeating scripted matches; no AI calls")
    parser.add_argument("--stream", metavar="RTSP_URL", help="Publish video-only HLS via FFmpeg and MediaMTX")
    parser.add_argument("--stream-fps", type=int, choices=(30, 60), default=30)
    parser.add_argument("--headless", action="store_true", help="Run without a desktop or audio device")
    parser.add_argument("--mute", action="store_true", help="Mute local audio")
    parser.add_argument("--size", metavar="WIDTHxHEIGHT", help="Override game dimensions; streaming defaults to 1280x720")
    parser.add_argument("--smoke-test", action="store_true", help="Check game display and exit")
    return parser


def shutdown(signum, frame):
    raise SystemExit(0)


publisher = None


def present():
    pygame.display.update()
    if publisher:
        publisher.capture(screen)


# Helper Function for Bundled Assets
def resource_path(relative_path):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return str(base / relative_path)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    if args.headless:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
    if args.headless or args.mute:
        os.environ["SDL_AUDIODRIVER"] = "dummy"
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    mixer.init()
    pygame.init()

    # Constants
    info = pygame.display.Info()
    SCREEN_WIDTH = info.current_w
    SCREEN_HEIGHT = info.current_h
    if args.stream or args.headless:
        SCREEN_WIDTH, SCREEN_HEIGHT = 1280, 720
    if args.size:
        try:
            SCREEN_WIDTH, SCREEN_HEIGHT = map(int, args.size.lower().split("x"))
            if not (960 <= SCREEN_WIDTH <= 7680 and 600 <= SCREEN_HEIGHT <= 4320):
                raise ValueError
        except ValueError:
            parser.error("--size must be WIDTHxHEIGHT, between 960x600 and 7680x4320")
    FPS = 60
    ROUND_OVER_COOLDOWN = 3000

    # Colors
    RED = (255, 0, 0)
    YELLOW = (255, 255, 0)
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    BLUE = (0, 0, 255)
    GREEN = (0, 255, 0)

    # Initialize Game Window
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
    pygame.display.set_caption("Street Fighter")
    clock = pygame.time.Clock()
    if args.stream:
        try:
            publisher = FramePublisher(StreamConfig(args.stream, args.stream_fps), screen.get_size())
        except (ValueError, RuntimeError) as error:
            parser.error(str(error))
        atexit.register(publisher.close)

    # Load Assets
    bg_image = pygame.image.load(resource_path("assets/images/bg1.jpg")).convert()
    victory_img = pygame.image.load(resource_path("assets/images/victory.png")).convert_alpha()
    warrior_victory_img = pygame.image.load(resource_path("assets/images/warrior.png")).convert_alpha()
    wizard_victory_img = pygame.image.load(resource_path("assets/images/wizard.png")).convert_alpha()

    # Fonts
    menu_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 50)
    menu_font_title = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 100)  # Larger font for title
    count_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 80)
    score_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 30)
    player_label_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 25)

    # Music and Sounds
    pygame.mixer.music.load(resource_path("assets/audio/music.mp3"))
    pygame.mixer.music.set_volume(0.5)
    pygame.mixer.music.play(-1, 0.0, 5000)
    sword_fx = pygame.mixer.Sound(resource_path("assets/audio/sword.wav"))
    sword_fx.set_volume(0.5)
    magic_fx = pygame.mixer.Sound(resource_path("assets/audio/magic.wav"))
    magic_fx.set_volume(0.75)

    # Load Fighter Spritesheets
    warrior_sheet = pygame.image.load(resource_path("assets/images/warrior.png")).convert_alpha()
    wizard_sheet = pygame.image.load(resource_path("assets/images/wizard.png")).convert_alpha()

    # Define Animation Steps
    WARRIOR_ANIMATION_STEPS = [10, 8, 1, 7, 7, 3, 7]
    WIZARD_ANIMATION_STEPS = [8, 8, 1, 8, 8, 3, 7]

    # Fighter Data
    WARRIOR_SIZE = 162
    WARRIOR_SCALE = 4
    WARRIOR_OFFSET = [72, 46]
    WARRIOR_DATA = [WARRIOR_SIZE, WARRIOR_SCALE, WARRIOR_OFFSET]
    WIZARD_SIZE = 250
    WIZARD_SCALE = 3
    WIZARD_OFFSET = [112, 97]
    WIZARD_DATA = [WIZARD_SIZE, WIZARD_SCALE, WIZARD_OFFSET]

    # Game Variables
    score = [0, 0]  # Player Scores: [P1, P2]



def draw_text(text, font, color, x, y):
    img = font.render(text, True, color)
    screen.blit(img, (x, y))


def blur_bg(image):
    small = pygame.transform.smoothscale(image, (max(1, image.get_width() // 12),
                                                max(1, image.get_height() // 12)))
    return pygame.transform.smoothscale(small, image.get_size())


_background_cache = {}


def draw_bg(image, is_game_started=False):
    key = (id(image), is_game_started)
    if key not in _background_cache:
        scaled = pygame.transform.smoothscale(image, (SCREEN_WIDTH, SCREEN_HEIGHT))
        _background_cache[key] = scaled if is_game_started else blur_bg(scaled)
    screen.blit(_background_cache[key], (0, 0))


def draw_button(text, font, text_col, button_col, x, y, width, height):
    pygame.draw.rect(screen, button_col, (x, y, width, height))
    pygame.draw.rect(screen, WHITE, (x, y, width, height), 2)
    text_img = font.render(text, True, text_col)
    text_rect = text_img.get_rect(center=(x + width // 2, y + height // 2))
    screen.blit(text_img, text_rect)
    return pygame.Rect(x, y, width, height)


def victory_screen(winner_img):
    start_time = pygame.time.get_ticks()
    while pygame.time.get_ticks() - start_time < ROUND_OVER_COOLDOWN:

        resized_victory_img = pygame.transform.scale(victory_img, (victory_img.get_width() * 2, victory_img.get_height() * 2))
        screen.blit(resized_victory_img, (SCREEN_WIDTH // 2 - resized_victory_img.get_width() // 2,
                                          SCREEN_HEIGHT // 2 - resized_victory_img.get_height() // 2 - 50))

        if winner_img is not None:
            screen.blit(winner_img, (SCREEN_WIDTH // 2 - winner_img.get_width() // 2,
                                     SCREEN_HEIGHT // 2 - winner_img.get_height() // 2 + 100))
        else:
            draw_text("DRAW", menu_font_title, WHITE, SCREEN_WIDTH // 2 - 140,
                      SCREEN_HEIGHT // 2 + 100)

        present()
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()


def draw_gradient_text(text, font, x, y, colors):
    """
    Draws a gradient text by layering multiple text surfaces with slight offsets.
    """
    offset = 2
    for i, color in enumerate(colors):
        img = font.render(text, True, color)
        screen.blit(img, (x + i * offset, y + i * offset))


def main_menu():
    animation_start_time = pygame.time.get_ticks()

    while True:
        draw_bg(bg_image, is_game_started=False)

        elapsed_time = (pygame.time.get_ticks() - animation_start_time) / 1000
        scale_factor = 1 + 0.05 * math.sin(elapsed_time * 2 * math.pi)  # Slight scaling
        scaled_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), int(100 * scale_factor))

        title_text = "STREET FIGHTER"
        colors = [BLUE, GREEN, YELLOW]
        shadow_color = BLACK
        title_x = SCREEN_WIDTH // 2 - scaled_font.size(title_text)[0] // 2
        title_y = SCREEN_HEIGHT // 6

        shadow_offset = 5
        draw_text(title_text, scaled_font, shadow_color, title_x + shadow_offset, title_y + shadow_offset)
        draw_gradient_text(title_text, scaled_font, title_x, title_y, colors)

        button_width = 280
        button_height = 60
        button_spacing = 30

        start_button_y = SCREEN_HEIGHT // 2 - (button_height + button_spacing) * 2 + 50
        controls_button_y = SCREEN_HEIGHT // 2 - (button_height + button_spacing) * 1 + 50
        scores_button_y = SCREEN_HEIGHT // 2 + (button_height + button_spacing) * 0 + 50
        exit_button_y = SCREEN_HEIGHT // 2 + (button_height + button_spacing) * 1 + 50

        start_button = draw_button("START GAME", menu_font, BLACK, GREEN, SCREEN_WIDTH // 2 - button_width // 2,
                                   start_button_y, button_width, button_height)
        controls_button = draw_button("CONTROLS", menu_font, BLACK, GREEN, SCREEN_WIDTH // 2 - button_width // 2,
                                     controls_button_y, button_width, button_height)
        scores_button = draw_button("SCORES", menu_font, BLACK, GREEN, SCREEN_WIDTH // 2 - button_width // 2,
                                    scores_button_y, button_width, button_height)
        exit_button = draw_button("EXIT", menu_font, BLACK, GREEN, SCREEN_WIDTH // 2 - button_width // 2,
                                  exit_button_y, button_width, button_height)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if start_button.collidepoint(event.pos):
                    return "START"
                if controls_button.collidepoint(event.pos):
                    return "CONTROLS"
                if scores_button.collidepoint(event.pos):
                    return "SCORES"
                if exit_button.collidepoint(event.pos):
                    pygame.quit()
                    exit()

        present()
        clock.tick(FPS)


def scores_screen():
    while True:
        draw_bg(bg_image)

        scores_title = "SCORES"
        draw_text(scores_title, menu_font_title, RED, SCREEN_WIDTH // 2 - menu_font_title.size(scores_title)[0] // 2, 50)

        score_font_large = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 60)  # Increased size for scores
        p1_text = f"P1: {score[0]}"
        p2_text = f"P2: {score[1]}"
        shadow_offset = 5

        p1_text_x = SCREEN_WIDTH // 2 - score_font_large.size(p1_text)[0] // 2
        p1_text_y = SCREEN_HEIGHT // 2 - 50
        draw_text(p1_text, score_font_large, BLACK, p1_text_x + shadow_offset, p1_text_y + shadow_offset)  # Shadow
        draw_gradient_text(p1_text, score_font_large, p1_text_x, p1_text_y, [BLUE, GREEN])  # Gradient

        p2_text_x = SCREEN_WIDTH // 2 - score_font_large.size(p2_text)[0] // 2
        p2_text_y = SCREEN_HEIGHT // 2 + 50
        draw_text(p2_text, score_font_large, BLACK, p2_text_x + shadow_offset, p2_text_y + shadow_offset)  # Shadow
        draw_gradient_text(p2_text, score_font_large, p2_text_x, p2_text_y, [RED, YELLOW])  # Gradient

        return_button = draw_button("RETURN TO MAIN MENU", menu_font, BLACK, GREEN, SCREEN_WIDTH // 2 - 220, SCREEN_HEIGHT - 80, 500, 50)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if return_button.collidepoint(event.pos):
                    return

        present()
        clock.tick(FPS)


def controls_screen():
    while True:
        draw_bg(bg_image)

        # Title
        controls_title = "CONTROLS GUIDE"
        draw_text(controls_title, menu_font_title, GREEN, SCREEN_WIDTH // 2 - menu_font_title.size(controls_title)[0] // 2, 50)

        # Controls information
        controls_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 35)
        small_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 25)

        draw_text("P1 - WARRIOR", controls_font, BLUE, 100, 150)
        draw_text("A / D - Move left / right", small_font, WHITE, 100, 200)
        draw_text("W - Jump", small_font, WHITE, 100, 240)
        draw_text("R - Attack 1", small_font, RED, 100, 280)
        draw_text("T - Attack 2", small_font, RED, 100, 320)

        draw_text("P2 - WIZARD", controls_font, (255, 100, 0), 500, 150)
        draw_text("Left / Right arrows - Move", small_font, WHITE, 500, 200)
        draw_text("Up arrow - Jump", small_font, WHITE, 500, 240)
        draw_text("K - Attack 1", small_font, RED, 500, 280)
        draw_text("L - Attack 2", small_font, RED, 500, 320)

        draw_text("Two players share one keyboard", small_font, YELLOW, 100, 410)
        draw_text("60 seconds. Highest health wins at timeout.", small_font, WHITE, 100, 450)

        # Return button
        return_button = draw_button("RETURN TO MAIN MENU", menu_font, BLACK, GREEN, SCREEN_WIDTH // 2 - 220, 550, 500, 50)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if return_button.collidepoint(event.pos):
                    return

        present()
        clock.tick(FPS)


def reset_game():
    global arena, fighter_1, fighter_2
    arena = Arena(SCREEN_WIDTH, SCREEN_HEIGHT)
    fighter_1 = Fighter(arena.fighters[0], WARRIOR_DATA, warrior_sheet, WARRIOR_ANIMATION_STEPS, sword_fx)
    fighter_2 = Fighter(arena.fighters[1], WIZARD_DATA, wizard_sheet, WIZARD_ANIMATION_STEPS, magic_fx)


def keyboard_action(keys, player):
    controls = ((pygame.K_a, pygame.K_d, pygame.K_w, pygame.K_r, pygame.K_t)
                if player == 1 else
                (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_k, pygame.K_l))
    left, right, jump, first, second = controls
    move = 1 if keys[right] else -1 if keys[left] else 0
    attack = 2 if keys[second] else 1 if keys[first] else 0
    return encode_action(move, bool(keys[jump]), attack)


def draw_health_bar(health, x, y):
    pygame.draw.rect(screen, BLACK, (x, y, 200, 20))
    if health > 0:
        pygame.draw.rect(screen, RED, (x, y, health * 2, 20))
    pygame.draw.rect(screen, WHITE, (x, y, 200, 20), 2)


def countdown():
    countdown_font = pygame.font.Font(resource_path("assets/fonts/turok.ttf"), 100)
    countdown_texts = ["3", "2", "1", "FIGHT!"]

    for text in countdown_texts:
        draw_bg(bg_image, is_game_started=True)

        text_img = countdown_font.render(text, True, RED)
        text_width = text_img.get_width()
        x_pos = (SCREEN_WIDTH - text_width) // 2

        draw_text(text, countdown_font, RED, x_pos, SCREEN_HEIGHT // 2 - 50)

        present()
        deadline = pygame.time.get_ticks() + 1000
        while pygame.time.get_ticks() < deadline:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise SystemExit(0)
            present()
            clock.tick(FPS)


def game_loop():
    global score
    reset_game()
    round_over = False
    winner_img = None
    game_started = True

    countdown()

    while True:
        draw_bg(bg_image, is_game_started=game_started)

        draw_text(f"P1: {score[0]}", score_font, RED, 20, 20)
        draw_text(f"P2: {score[1]}", score_font, RED, SCREEN_WIDTH - 220, 20)

        # Add player identification labels
        draw_text("PLAYER 1", player_label_font, BLUE, 20, 85)
        draw_text("PLAYER 2", player_label_font, (255, 100, 0), SCREEN_WIDTH - 220, 85)

        if args.demo:
            draw_text("SCRIPTED DEMO", score_font, YELLOW, SCREEN_WIDTH // 2 - 100, 130)

        draw_health_bar(fighter_1.health, 20, 50)
        draw_health_bar(fighter_2.health, SCREEN_WIDTH - 220, 50)

        remaining = (arena.max_steps - arena.steps + FPS - 1) // FPS
        draw_text(str(remaining), score_font, WHITE, SCREEN_WIDTH // 2 - 20, 90)

        exit_button = draw_button("MAIN MENU", menu_font, BLACK, YELLOW, SCREEN_WIDTH // 2 - 150, 20, 300, 50)

        if not round_over:
            keys = pygame.key.get_pressed()
            actions = (scripted_actions(arena) if args.demo else
                       [keyboard_action(keys, 1), keyboard_action(keys, 2)])
            result = arena.step(actions)
            for player in result["attacks_started"]:
                (fighter_1 if player == 1 else fighter_2).attack_sound.play()
            if result["done"]:
                round_over = True
                if result["winner"] is not None:
                    score[result["winner"] - 1] += 1
                winner_img = (warrior_victory_img if result["winner"] == 1 else
                              wizard_victory_img if result["winner"] == 2 else None)
        else:
            victory_screen(winner_img)
            return

        fighter_1.draw(screen)
        fighter_2.draw(screen)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                exit()
            if event.type == pygame.MOUSEBUTTONDOWN:
                if exit_button.collidepoint(event.pos):
                    return

        present()
        clock.tick(FPS)


if __name__ == "__main__":
    if args.smoke_test:
        reset_game()
        for _ in range(10):
            arena.step([0, 0])
            draw_bg(bg_image, is_game_started=True)
            fighter_1.draw(screen)
            fighter_2.draw(screen)
        draw_bg(bg_image)
        pygame.quit()
        print("Game display smoke test passed.")
    else:
        while True:
            menu_selection = "START" if args.demo else main_menu()

            if menu_selection == "START":
                game_loop()
            elif menu_selection == "CONTROLS":
                controls_screen()
            elif menu_selection == "SCORES":
                scores_screen()
