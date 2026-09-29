"""Concurrent human task: knitting a scarf, one row at a time.

Deliberately calm and low-effort. The participant picks a yarn colour and
the row then knits by itself over ``KNIT_ROW_TIME`` seconds. When a row
is done, they pick the next colour whenever it suits them. There are no
wrong answers and it cannot be sped up, so it does not compete with the
robot for attention and cannot cause frustration of its own. The block
ends only when both the robot's item list and the scarf are complete
(interdependent goal). Knitting pauses while the avatar is walking.
"""
import math

import pygame

from game import settings
from game.settings import COLORS

YARNS = (
    ("red", (212, 92, 86)),
    ("blue", (86, 128, 204)),
    ("yellow", (232, 186, 70)),
    ("green", (104, 170, 110)),
)


def validate_rows(rows):
    if not isinstance(rows, int) or rows < 1:
        raise ValueError(f"scarf_rows must be a positive integer, got {rows}")


class ScarfKnitting:
    """Pick a yarn -> the row knits itself -> pick the next yarn."""

    SCARF_TOP = 34
    SCARF_H = 84
    BALL_R = 24

    def __init__(self, rect, fonts, logger, sounds):
        self.rect = pygame.Rect(rect)
        self.fonts = fonts
        self.logger = logger
        self.sounds = sounds
        self.start_block(1)

    # ------------------------------------------------------------ state
    def start_block(self, rows):
        validate_rows(rows)
        self.rows_needed = rows
        self.rows = []              # colours of finished rows
        self.knitting = None        # colour of the row in progress
        self.progress = 0.0         # 0..1 for the row in progress

    @property
    def complete(self):
        return len(self.rows) >= self.rows_needed

    @property
    def mistakes(self):
        return 0                    # nothing can go wrong in this task

    def _ball_center(self, index):
        spacing = 76
        x0 = self.rect.centerx - spacing * (len(YARNS) - 1) / 2
        return (int(x0 + index * spacing), self.rect.bottom - 34)

    # ------------------------------------------------------------ input
    def handle_event(self, event, enabled):
        """Returns True if the click landed on the knitting panel."""
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1
                or not self.rect.collidepoint(event.pos)):
            return False
        if not enabled or self.complete or self.knitting is not None:
            return True
        for index, (name, color) in enumerate(YARNS):
            cx, cy = self._ball_center(index)
            if math.hypot(event.pos[0] - cx, event.pos[1] - cy) <= \
                    self.BALL_R + 6:
                self.knitting = color
                self.progress = 0.0
                self.logger.log("human", "knit_start",
                                detail=f"row={len(self.rows) + 1};"
                                       f"yarn={name}")
                return True
        return True

    def update(self, dt, active=True):
        """Advance the current row. ``active`` is False while walking."""
        if self.knitting is None or not active:
            return
        self.progress += dt / settings.KNIT_ROW_TIME
        if self.progress >= 1.0:
            self.rows.append(self.knitting)
            self.knitting = None
            self.progress = 0.0
            self.logger.log("human", "knit_row_done",
                            detail=f"row={len(self.rows)}")
            if self.complete:
                self.logger.log("human", "knit_complete",
                                detail=f"rows={len(self.rows)}")
                self.sounds.play("knit_done")
            else:
                self.sounds.play("row_done")

    # ------------------------------------------------------------ drawing
    def draw(self, surface, enabled, t=0.0):
        fonts, x, y = self.fonts, self.rect.x, self.rect.y
        surface.blit(fonts.body.render("Knit a scarf", True, COLORS["text"]),
                     (x, y))
        count = fonts.small.render(
            f"Row {min(len(self.rows) + 1, self.rows_needed)} of "
            f"{self.rows_needed}" if not self.complete else
            f"{self.rows_needed} of {self.rows_needed} rows", True,
            COLORS["text_muted"])
        surface.blit(count, count.get_rect(topright=(self.rect.right, y + 3)))

        self._draw_scarf(surface, t)

        if self.complete:
            status, ink = "Scarf finished!", COLORS["success"]
        elif self.knitting is not None:
            status, ink = "Knitting... (this row knits by itself)", \
                COLORS["text_muted"]
        else:
            status, ink = "Pick a yarn to knit the next row", COLORS["text"]
        text = fonts.body.render(status, True, ink)
        surface.blit(text, text.get_rect(
            center=(self.rect.centerx, y + self.SCARF_TOP + self.SCARF_H
                    + 26)))

        can_pick = enabled and not self.complete and self.knitting is None
        for index, (_, color) in enumerate(YARNS):
            self._draw_ball(surface, self._ball_center(index), color,
                            can_pick)

        if not enabled and not self.complete:
            veil = pygame.Surface(self.rect.size, pygame.SRCALPHA)
            veil.fill((*COLORS["panel"], 200))
            surface.blit(veil, self.rect.topleft)
            image = fonts.large.render("Paused while you walk...", True,
                                       COLORS["text_muted"])
            surface.blit(image, image.get_rect(center=self.rect.center))

    def _draw_scarf(self, surface, t):
        area = pygame.Rect(self.rect.x + 24, self.rect.y + self.SCARF_TOP,
                           self.rect.w - 48, self.SCARF_H)
        stripe_w = min(40, area.w // self.rows_needed)
        scarf_w = stripe_w * self.rows_needed
        left = area.centerx - scarf_w // 2
        # outline of the whole scarf-to-be
        outline = pygame.Rect(left, area.y, scarf_w, area.h)
        pygame.draw.rect(surface, COLORS["button"], outline, border_radius=6)
        pygame.draw.rect(surface, COLORS["panel_line"], outline, 2,
                         border_radius=6)
        for index, color in enumerate(self.rows):
            self._draw_stripe(surface, pygame.Rect(
                left + index * stripe_w, area.y, stripe_w, area.h), color,
                1.0)
        if self.knitting is not None:
            stripe = pygame.Rect(left + len(self.rows) * stripe_w, area.y,
                                 stripe_w, area.h)
            self._draw_stripe(surface, stripe, self.knitting, self.progress)
            # needles at the growing edge
            edge = stripe.y + int(stripe.h * self.progress)
            wobble = int(2 * math.sin(t * 8))
            for dx in (-6, 6):
                pygame.draw.line(surface, COLORS["cane"],
                                 (stripe.centerx + dx - 14, edge - 10),
                                 (stripe.centerx + dx + 14 + wobble,
                                  edge + 10), 3)
        # fringe on both ends
        for end_x in (left - 1, left + scarf_w):
            for i in range(6):
                fy = area.y + 8 + i * (area.h - 16) // 5
                direction = -1 if end_x == left - 1 else 1
                pygame.draw.line(surface, COLORS["pending"], (end_x, fy),
                                 (end_x + direction * 8, fy), 2)

    @staticmethod
    def _draw_stripe(surface, rect, color, fraction):
        filled = pygame.Rect(rect.x, rect.y, rect.w,
                             max(1, int(rect.h * fraction)))
        pygame.draw.rect(surface, color, filled)
        dark = tuple(max(0, c - 40) for c in color)
        # little "v" stitches
        for sy in range(filled.y + 4, filled.bottom - 4, 9):
            for sx in range(rect.x + 4, rect.right - 6, 10):
                pygame.draw.lines(surface, dark, False,
                                  [(sx, sy), (sx + 3, sy + 4), (sx + 6, sy)],
                                  1)

    def _draw_ball(self, surface, center, color, active):
        if not active:
            color = tuple(int(c * 0.35 + 235 * 0.65) for c in color)
        r = self.BALL_R
        pygame.draw.circle(surface, color, center, r)
        dark = tuple(max(0, c - 45) for c in color)
        cx, cy = center
        for offset in (-10, 0, 10):
            arc = pygame.Rect(cx - r + 4, cy - r // 2 + offset, 2 * r - 8, r)
            pygame.draw.arc(surface, dark, arc, 0.3, math.pi - 0.3, 2)
        pygame.draw.circle(surface, dark, center, r, 2)
        if active and pygame.Rect(cx - r, cy - r, 2 * r, 2 * r).collidepoint(
                pygame.mouse.get_pos()):
            pygame.draw.circle(surface, COLORS["alt"], center, r + 4, 3)
