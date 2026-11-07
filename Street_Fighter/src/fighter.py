"""Pygame presentation for a fighter in the shared arena."""

import pygame


class Fighter:
    def __init__(self, state, data, sprite_sheet, animation_steps, sound):
        self.state = state
        self.size, self.image_scale, self.offset = data
        self.animation_list = self.load_images(sprite_sheet, animation_steps)
        self.attack_sound = sound

    def __getattr__(self, name):
        return getattr(self.state, name)

    def load_images(self, sprite_sheet, animation_steps):
        animations = []
        for row, count in enumerate(animation_steps):
            frames = []
            for column in range(count):
                image = sprite_sheet.subsurface(column * self.size, row * self.size, self.size, self.size)
                frames.append(pygame.transform.scale(
                    image, (self.size * self.image_scale, self.size * self.image_scale)))
            animations.append(frames)
        return animations

    def draw(self, surface):
        image = self.animation_list[self.state.action][self.state.frame_index]
        image = pygame.transform.flip(image, self.state.flip, False)
        surface.blit(image, (self.state.x - self.offset[0] * self.image_scale,
                             self.state.y - self.offset[1] * self.image_scale))
