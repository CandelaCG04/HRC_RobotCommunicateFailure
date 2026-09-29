"""Bottom panel with the multiple-choice dialog buttons."""
import math

import pygame

from game.settings import COLORS


class DialogPanel:
    """Shows a prompt and up to 9 buttons (mouse or number keys)."""

    COLS = 3
    MARGIN = 16
    GAP = 10
    BUTTON_H = 40

    def __init__(self, rect, fonts):
        self.rect = pygame.Rect(rect)
        self.fonts = fonts
        self.prompt = ""
        self.options = []
        self.buttons = []           # list of (rect, key)

    def set_options(self, prompt, options):
        """Update the prompt and buttons; cheap if nothing changed."""
        options = list(options)
        if prompt == self.prompt and options == self.options:
            return
        self.prompt, self.options = prompt, options
        width = self.rect.w - 2 * self.MARGIN
        button_w = (width - (self.COLS - 1) * self.GAP) // self.COLS
        top = self.rect.y + 34
        self.buttons = []
        for index, (_, key) in enumerate(self.options):
            row, col = divmod(index, self.COLS)
            rect = pygame.Rect(
                self.rect.x + self.MARGIN + col * (button_w + self.GAP),
                top + row * (self.BUTTON_H + self.GAP),
                button_w, self.BUTTON_H)
            self.buttons.append((rect, key))

    def handle_event(self, event):
        """Return the action key of a clicked/pressed button, else None."""
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1):
            for rect, key in self.buttons:
                if rect.collidepoint(event.pos):
                    return key
        elif event.type == pygame.KEYDOWN and event.unicode.isdigit():
            index = int(event.unicode) - 1
            if 0 <= index < len(self.buttons):
                return self.buttons[index][1]
        return None

    def draw(self, surface, attention=False, t=0.0):
        """``attention`` makes the panel pulse to show input is needed."""
        surface.fill(COLORS["panel"], self.rect)
        color = COLORS["text"] if self.options else COLORS["text_muted"]
        if attention:
            pulse = (math.sin(t * 5) + 1) / 2
            glow = tuple(int(a + (b - a) * pulse) for a, b in
                         zip(COLORS["panel_line"], COLORS["alt"]))
            pygame.draw.rect(surface, glow, self.rect.inflate(-4, -4), 4,
                             border_radius=6)
            color = COLORS["alt"]
        prompt = self.fonts.body.render(self.prompt, True, color)
        surface.blit(prompt, (self.rect.x + self.MARGIN, self.rect.y + 8))

        mouse = pygame.mouse.get_pos()
        for number, ((rect, _), (label, _)) in enumerate(
                zip(self.buttons, self.options), start=1):
            hover = rect.collidepoint(mouse)
            fill = COLORS["button_hover"] if hover else COLORS["button"]
            pygame.draw.rect(surface, fill, rect, border_radius=8)
            pygame.draw.rect(surface, COLORS["button_border"], rect, 2,
                             border_radius=8)
            text = f"{number}.  {label}"
            font = self.fonts.body
            if font.size(text)[0] > rect.w - 20:
                font = self.fonts.small      # long labels: smaller font
            while font.size(text)[0] > rect.w - 20 and len(text) > 4:
                text = text[:-4] + "..."
            image = font.render(text, True, COLORS["text"])
            surface.blit(image, image.get_rect(
                midleft=(rect.x + 12, rect.centery)))
