"""Small hands-on interactions for using an item.

When the participant starts an activity, one of these opens in the side
panel. Each takes a few seconds, is paced so it cannot be rushed, and has
no wrong answers: a wrong move simply does nothing.

Types (set per item in items.json under "do"):
  hold      hold the mouse button on the item (drink, pour)
  tap       click the item a few times with a short pause in between
            (take a bite, turn a page)
  drag      drag the item onto yourself (glasses onto face, blanket on)
  sequence  press buttons in the shown order (dial a number, TV remote)
  slider    drag a dial into the marked zone and leave it there (radio)
"""
import math

import pygame

from game import settings
from game.settings import COLORS
from game.ui.speech import wrap_text

TYPES = ("hold", "tap", "drag", "sequence", "slider")
PALETTE = ((214, 140, 96), (120, 160, 214), (150, 196, 132),
           (226, 190, 92), (186, 140, 200))


def make_interaction(spec, rect, fonts, label):
    """Build the interaction described by an item's "do" spec."""
    classes = {"hold": HoldInteraction, "tap": TapInteraction,
               "drag": DragInteraction, "sequence": SequenceInteraction,
               "slider": SliderInteraction}
    return classes[spec["type"]](spec, rect, fonts, label)


def _shade(color, amount):
    return tuple(max(0, min(255, c + amount)) for c in color[:3])


def _ink_for(color):
    r, g, b = color[:3]
    dark = 0.299 * r + 0.587 * g + 0.114 * b < 140
    return (245, 245, 245) if dark else COLORS["text"]


class Interaction:
    """Base class: tracks the mouse, prompt text and finished state."""

    def __init__(self, spec, rect, fonts, label):
        self.spec = spec
        self.rect = pygame.Rect(rect)
        self.fonts = fonts
        self.label = spec.get("object", label)
        if "color" in spec:
            self.color = tuple(spec["color"])
        else:
            self.color = PALETTE[sum(map(ord, self.label)) % len(PALETTE)]
        self.prompt = spec.get("prompt", f"Use the {self.label}")
        self.mouse = self.rect.center
        self.done = False
        self._steps = []

    # -- events and timing
    def handle_event(self, event):
        if hasattr(event, "pos"):
            self.mouse = event.pos
        if not self.done:
            self.on_event(event)

    def on_event(self, event):
        pass

    def update(self, dt):
        pass

    def pop_steps(self):
        """Progress steps since the last call, for the event log."""
        steps, self._steps = self._steps, []
        return steps

    @staticmethod
    def _pressed(event):
        return event.type == pygame.MOUSEBUTTONDOWN and event.button == 1

    @staticmethod
    def _released(event):
        return event.type == pygame.MOUSEBUTTONUP and event.button == 1

    # -- drawing
    def draw(self, surface, t):
        font = self.fonts.body
        if font.size(self.prompt)[0] > self.rect.w:
            font = self.fonts.small
        lines = wrap_text(self.prompt, font, self.rect.w)[:2]
        for i, line in enumerate(lines):
            image = font.render(line, True, COLORS["alt"])
            surface.blit(image, image.get_rect(
                midtop=(self.rect.centerx, self.rect.y + 2 + i * 22)))
        self.draw_body(surface, t)

    def draw_body(self, surface, t):
        pass

    def _draw_object(self, surface, rect, level=None, liquid=None,
                     label=True, label_y=None):
        """Rounded box standing for the item; optional liquid level."""
        pygame.draw.rect(surface, self.color, rect, border_radius=10)
        if level is not None:
            inner = rect.inflate(-14, -14)
            pygame.draw.rect(surface, (250, 250, 250), inner,
                             border_radius=6)
            height = int(inner.h * max(0.0, min(1.0, level)))
            if height > 0:
                fill = pygame.Rect(inner.x, inner.bottom - height, inner.w,
                                   height)
                pygame.draw.rect(surface, liquid or (120, 170, 220), fill,
                                 border_radius=6)
        pygame.draw.rect(surface, _shade(self.color, -50), rect, 2,
                         border_radius=10)
        if label:
            text = self.fonts.small.render(self.label, True, COLORS["text"])
            y = rect.bottom + 6 if label_y is None else label_y
            surface.blit(text, text.get_rect(midtop=(rect.centerx, y)))

    def _ring(self, surface, center, radius, t, active=True):
        if active:
            pulse = (math.sin(t * 5) + 1) / 2
            pygame.draw.circle(surface, COLORS["alt"], center,
                               radius + int(4 * pulse), 3)
        else:
            pygame.draw.circle(surface, COLORS["panel_line"], center,
                               radius, 2)


class HoldInteraction(Interaction):
    """Hold the mouse on the item; drinking empties it, pouring fills a cup."""

    def __init__(self, spec, rect, fonts, label):
        super().__init__(spec, rect, fonts, label)
        self.seconds = spec.get("seconds", settings.HOLD_SECONDS)
        self.pour = spec.get("mode") == "pour"
        self.liquid = tuple(spec.get("liquid", (120, 170, 220)))
        self.held = 0.0
        self.holding = False
        self.obj = pygame.Rect(0, 0, 84, 96)
        cx = self.rect.centerx - (70 if self.pour else 0)
        self.obj.center = (cx, self.rect.y + 98)
        self.cup = pygame.Rect(0, 0, 64, 70)
        self.cup.midbottom = (self.rect.centerx + 90, self.obj.bottom)

    @property
    def progress(self):
        return min(1.0, self.held / self.seconds)

    def on_event(self, event):
        if self._pressed(event) and self.obj.collidepoint(event.pos):
            self.holding = True
        elif self._released(event):
            self.holding = False

    def update(self, dt):
        if self.holding and self.obj.collidepoint(self.mouse):
            before = self.held
            self.held += dt
            if before < self.seconds / 2 <= self.held:
                self._steps.append("half")
            if self.held >= self.seconds:
                self.done = True

    def draw_body(self, surface, t):
        active = self.holding and self.obj.collidepoint(self.mouse)
        self._ring(surface, self.obj.center, 60, t, not active)
        self._draw_object(surface, self.obj, level=1.0 - self.progress,
                          liquid=self.liquid, label_y=self.obj.centery + 64)
        if self.pour:
            empty = self.color
            self.color = (236, 236, 240)
            self._draw_object(surface, self.cup, level=self.progress,
                              liquid=self.liquid, label=False)
            self.color = empty
            if active:
                pygame.draw.line(surface, self.liquid,
                                 (self.obj.right - 6, self.obj.y + 20),
                                 (self.cup.centerx, self.cup.y + 8), 5)
        text = "Keep holding..." if active else "Press and hold"
        image = self.fonts.small.render(text, True, COLORS["text_muted"])
        surface.blit(image, image.get_rect(midbottom=(self.rect.centerx,
                                                      self.rect.bottom)))


class TapInteraction(Interaction):
    """Click the item a few times; it is only ready again after a pause."""

    def __init__(self, spec, rect, fonts, label):
        super().__init__(spec, rect, fonts, label)
        self.count = spec.get("count", 4)
        self.cooldown = spec.get("cooldown", settings.TAP_COOLDOWN)
        self.flip = spec.get("style") == "flip"     # pages, not bites
        self.taps = 0
        self.wait = 0.0
        self.obj = pygame.Rect(0, 0, 104, 84)
        self.obj.center = (self.rect.centerx, self.rect.y + 96)

    @property
    def progress(self):
        return self.taps / self.count

    def on_event(self, event):
        if (self._pressed(event) and self.wait <= 0
                and self.obj.collidepoint(event.pos)):
            self.taps += 1
            self.wait = self.cooldown
            self._steps.append(f"{self.taps}/{self.count}")
            if self.taps >= self.count:
                self.done = True

    def update(self, dt):
        self.wait = max(0.0, self.wait - dt)

    def draw_body(self, surface, t):
        self._ring(surface, self.obj.center, 60, t, self.wait <= 0)
        obj = self.obj.copy()
        if not self.flip:           # the item gets smaller with each bite
            scale = 1.0 - 0.55 * self.progress
            obj.size = (int(obj.w * scale), int(obj.h * scale))
            obj.center = self.obj.center
        self._draw_object(surface, obj, label=False)
        if self.flip:
            page = self.fonts.body.render(f"page {self.taps + 1}", True,
                                          _ink_for(self.color))
            surface.blit(page, page.get_rect(center=obj.center))
        name = self.fonts.small.render(self.label, True, COLORS["text"])
        surface.blit(name, name.get_rect(midtop=(self.obj.centerx,
                                                 self.obj.centery + 64)))
        # one dot per click still to do
        y = self.rect.bottom - 14
        x0 = self.rect.centerx - (self.count - 1) * 10
        for i in range(self.count):
            color = COLORS["success"] if i < self.taps else \
                COLORS["panel_line"]
            pygame.draw.circle(surface, color, (x0 + i * 20, y), 6)


class DragInteraction(Interaction):
    """Drag the item onto the marked spot on yourself."""

    ZONES = {"face": (0, 66), "ear": (24, 66), "body": (0, 132),
             "feet": (0, 196)}
    SNAP = 48
    SETTLE = 0.8

    def __init__(self, spec, rect, fonts, label):
        super().__init__(spec, rect, fonts, label)
        self.person_x = self.rect.right - 130
        dx, dy = self.ZONES[spec.get("target", "body")]
        self.zone = (self.person_x + dx, self.rect.y + dy)
        self.home = (self.rect.x + 120, self.rect.y + 130)
        self.obj = pygame.Rect(0, 0, 92, 54)
        self.obj.center = self.home
        self.dragging = False
        self.offset = (0, 0)
        self.placed = False
        self.settle = 0.0

    @property
    def progress(self):
        if self.placed:
            return 0.5 + 0.5 * min(1.0, self.settle / self.SETTLE)
        return 0.0

    def on_event(self, event):
        if self.placed:
            return
        if self._pressed(event) and self.obj.collidepoint(event.pos):
            self.dragging = True
            self.offset = (event.pos[0] - self.obj.centerx,
                           event.pos[1] - self.obj.centery)
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.obj.center = (event.pos[0] - self.offset[0],
                               event.pos[1] - self.offset[1])
        elif self._released(event) and self.dragging:
            self.dragging = False
            if math.dist(self.obj.center, self.zone) <= self.SNAP:
                self.placed = True
                self.obj.size = (60, 34)
                self.obj.center = self.zone
                self._steps.append("placed")
            else:
                self.obj.center = self.home     # no penalty, try again

    def update(self, dt):
        if self.placed:
            self.settle += dt
            if self.settle >= self.SETTLE:
                self.done = True

    def draw_body(self, surface, t):
        x, top = self.person_x, self.rect.y
        body = pygame.Rect(0, 0, 76, 86)
        body.midtop = (x, top + 92)
        pygame.draw.ellipse(surface, COLORS["cardigan"], body)
        for side in (-1, 1):
            foot = pygame.Rect(0, 0, 30, 16)
            foot.center = (x + side * 18, top + 196)
            pygame.draw.ellipse(surface, (110, 100, 96), foot)
        pygame.draw.circle(surface, COLORS["skin"], (x, top + 66), 26)
        pygame.draw.circle(surface, COLORS["hair"], (x, top + 60), 26,
                           draw_top_left=True, draw_top_right=True)
        if not self.placed:
            self._ring(surface, self.zone, 26, t)
            pygame.draw.line(surface, COLORS["panel_line"],
                             (self.home[0] + 60, self.home[1]),
                             (self.zone[0] - 40, self.zone[1]), 2)
        self._draw_object(surface, self.obj, label=not self.placed)


class SequenceInteraction(Interaction):
    """Press the buttons in the order shown; other presses do nothing."""

    def __init__(self, spec, rect, fonts, label):
        super().__init__(spec, rect, fonts, label)
        self.sequence = [str(s) for s in spec["sequence"]]
        names = spec.get("buttons") or sorted(set(self.sequence))
        self.index = 0
        self.flash = None           # (button label, colour, seconds left)
        self.buttons = self._layout([str(b) for b in names])

    def _layout(self, names):
        font, gap, height = self.fonts.body, 8, 38
        widths = [max(52, font.size(n)[0] + 26) for n in names]
        rows, row, row_w = [], [], 0
        for name, width in zip(names, widths):
            if row and row_w + gap + width > self.rect.w - 40:
                rows.append(row)
                row, row_w = [], 0
            row.append((name, width))
            row_w += width + (gap if len(row) > 1 else 0)
        rows.append(row)
        buttons = []
        y = self.rect.y + 96
        for row in rows:
            total = sum(w for _, w in row) + gap * (len(row) - 1)
            x = self.rect.centerx - total // 2
            for name, width in row:
                buttons.append((name, pygame.Rect(x, y, width, height)))
                x += width + gap
            y += height + gap
        return buttons

    @property
    def progress(self):
        return self.index / len(self.sequence)

    def on_event(self, event):
        if not self._pressed(event):
            return
        for name, rect in self.buttons:
            if rect.collidepoint(event.pos):
                if name == self.sequence[self.index]:
                    self.index += 1
                    self.flash = (name, COLORS["success"], 0.3)
                    self._steps.append(name)
                    if self.index >= len(self.sequence):
                        self.done = True
                else:
                    self.flash = (name, COLORS["panel_line"], 0.3)
                return

    def update(self, dt):
        if self.flash:
            name, color, left = self.flash
            self.flash = (name, color, left - dt) if left > dt else None

    def draw_body(self, surface, t):
        font = self.fonts.body
        # the code to enter, done parts in green
        boxes = []
        for symbol in self.sequence:
            boxes.append(max(40, font.size(symbol)[0] + 20))
        total = sum(boxes) + 8 * (len(boxes) - 1)
        x = self.rect.centerx - total // 2
        for i, (symbol, width) in enumerate(zip(self.sequence, boxes)):
            box = pygame.Rect(x, self.rect.y + 46, width, 36)
            if i < self.index:
                fill, border, ink = COLORS["success"], COLORS["success"], \
                    (255, 255, 255)
            elif i == self.index:
                fill, border, ink = COLORS["highlight"], COLORS["alt"], \
                    COLORS["text"]
            else:
                fill, border, ink = COLORS["button"], COLORS["panel_line"], \
                    COLORS["text_muted"]
            pygame.draw.rect(surface, fill, box, border_radius=6)
            pygame.draw.rect(surface, border, box, 2, border_radius=6)
            image = font.render(symbol, True, ink)
            surface.blit(image, image.get_rect(center=box.center))
            x += width + 8
        # the item's buttons
        mouse_over = None
        for name, rect in self.buttons:
            if rect.collidepoint(self.mouse):
                mouse_over = name
        for name, rect in self.buttons:
            fill = self.color
            if self.flash and self.flash[0] == name:
                fill = self.flash[1]
            elif name == mouse_over:
                fill = _shade(self.color, 25)
            pygame.draw.rect(surface, fill, rect, border_radius=8)
            pygame.draw.rect(surface, _shade(self.color, -50), rect, 2,
                             border_radius=8)
            image = font.render(name, True, _ink_for(fill))
            surface.blit(image, image.get_rect(center=rect.center))
        label = self.fonts.small.render(self.label, True,
                                        COLORS["text_muted"])
        surface.blit(label, label.get_rect(midbottom=(self.rect.centerx,
                                                      self.rect.bottom)))


class SliderInteraction(Interaction):
    """Drag a dial into the marked zone and leave it there for a moment."""

    def __init__(self, spec, rect, fonts, label):
        super().__init__(spec, rect, fonts, label)
        self.target = spec.get("target", 0.72)
        self.zone = spec.get("zone", 0.08)
        self.dwell_needed = spec.get("dwell", 1.2)
        self.value = 0.1
        self.dragging = False
        self.dwell = 0.0
        self.track = pygame.Rect(self.rect.x + 60, self.rect.y + 130,
                                 self.rect.w - 120, 10)

    @property
    def progress(self):
        return min(1.0, self.dwell / self.dwell_needed)

    @property
    def in_zone(self):
        return abs(self.value - self.target) <= self.zone

    def _knob(self):
        return (int(self.track.x + self.value * self.track.w),
                self.track.centery)

    def _set_from(self, x):
        self.value = max(0.0, min(1.0, (x - self.track.x) / self.track.w))

    def on_event(self, event):
        if self._pressed(event):
            near_knob = math.dist(event.pos, self._knob()) <= 24
            on_track = self.track.inflate(0, 30).collidepoint(event.pos)
            if near_knob or on_track:
                self.dragging = True
                self._set_from(event.pos[0])
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self._set_from(event.pos[0])
        elif self._released(event):
            self.dragging = False

    def update(self, dt):
        if self.in_zone:
            self.dwell += dt
            if self.dwell >= self.dwell_needed:
                self._steps.append("tuned")
                self.done = True
        else:
            self.dwell = 0.0

    def draw_body(self, surface, t):
        panel = pygame.Rect(self.rect.x + 30, self.rect.y + 52,
                            self.rect.w - 60, 140)
        pygame.draw.rect(surface, self.color, panel, border_radius=14)
        pygame.draw.rect(surface, _shade(self.color, -50), panel, 2,
                         border_radius=14)
        screen = pygame.Rect(0, 0, 220, 34)
        screen.midtop = (panel.centerx, panel.y + 14)
        pygame.draw.rect(surface, COLORS["robot_screen"], screen,
                         border_radius=6)
        if self.in_zone:
            text, ink = "clear signal", COLORS["robot_face"]
        else:
            text, ink = "~ ~ static ~ ~", (150, 160, 175)
        image = self.fonts.body.render(text, True, ink)
        surface.blit(image, image.get_rect(center=screen.center))

        pygame.draw.rect(surface, (245, 245, 245), self.track,
                         border_radius=5)
        zone = pygame.Rect(0, 0, int(2 * self.zone * self.track.w),
                           self.track.h + 10)
        zone.center = (int(self.track.x + self.target * self.track.w),
                       self.track.centery)
        pygame.draw.rect(surface, COLORS["success"], zone, border_radius=5)
        knob = self._knob()
        pygame.draw.circle(surface, (255, 255, 255), knob, 15)
        pygame.draw.circle(surface, COLORS["robot_outline"], knob, 15, 3)
        if self.dwell > 0:
            arc = pygame.Rect(0, 0, 40, 40)
            arc.center = knob
            pygame.draw.arc(surface, COLORS["success"], arc, math.pi / 2,
                            math.pi / 2 + 2 * math.pi * self.progress, 4)
        label = self.fonts.small.render(self.label, True, COLORS["text"])
        surface.blit(label, label.get_rect(midbottom=(panel.centerx,
                                                      panel.bottom - 8)))