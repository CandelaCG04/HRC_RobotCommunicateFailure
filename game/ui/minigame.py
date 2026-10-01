"""Concurrent human task: doing something with each item the robot brings.

Every item on the list unlocks one activity ("Put on your reading
glasses", "Drink the tea"). An activity stays locked until the participant
actually has the item: brought by the robot, replaced by the robot's
alternative (the activity changes to match, e.g. "Put on the spare
glasses"), or fetched themselves. If they give up on an item, its activity
is skipped. Once unlocked, one click starts it and it takes
``ACTIVITY_TIME`` seconds, one activity at a time.

So the human's part depends directly on the robot's deliveries, it cannot
be rushed ahead of them, and it needs very little attention. A block ends
when every item is resolved and every unlocked activity is done.
Activities pause while the avatar is walking.
"""
import pygame

from game import settings
from game.settings import COLORS

LOCKED, READY, ACTIVE, DONE, SKIPPED = (
    "locked", "ready", "active", "done", "skipped")


class Activity:
    def __init__(self, item):
        self.item = item
        self.text = item.use
        self.state = LOCKED
        self.progress = 0.0


class ActivityList:
    """One row per item: locked -> ready (click) -> active -> done."""

    TOP = 32
    ROW_H = 34
    ROW_GAP = 4

    def __init__(self, rect, fonts, logger, sounds):
        self.rect = pygame.Rect(rect)
        self.fonts = fonts
        self.logger = logger
        self.sounds = sounds
        self.start_block([])

    # ------------------------------------------------------------ state
    def start_block(self, items):
        self.activities = [Activity(item) for item in items]

    @property
    def complete(self):
        return all(a.state in (DONE, SKIPPED) for a in self.activities)

    @property
    def done_count(self):
        return sum(a.state == DONE for a in self.activities)

    @property
    def active(self):
        return next((a for a in self.activities if a.state == ACTIVE), None)

    def item_resolved(self, item, status):
        """Called by the block controller when an item is resolved."""
        activity = next(a for a in self.activities if a.item is item)
        if status == "gave_up":
            activity.state = SKIPPED
            self._log("activity_skipped", activity)
            return
        if status == "alternative":
            activity.text = item.failure.alternative.use
        activity.state = READY
        self._log("activity_unlocked", activity, actor="system")

    def _log(self, action, activity, actor="human"):
        self.logger.log(actor, action, item=activity.item.item_id,
                        detail=activity.text)

    def _row_rect(self, index):
        return pygame.Rect(self.rect.x,
                           self.rect.y + self.TOP
                           + index * (self.ROW_H + self.ROW_GAP),
                           self.rect.w, self.ROW_H)

    # ------------------------------------------------------------ input
    def handle_event(self, event, enabled):
        """Returns True if the click landed on the activity panel."""
        if (event.type != pygame.MOUSEBUTTONDOWN or event.button != 1
                or not self.rect.collidepoint(event.pos)):
            return False
        if not enabled or self.active:
            return True
        for index, activity in enumerate(self.activities):
            if (activity.state == READY
                    and self._row_rect(index).collidepoint(event.pos)):
                activity.state = ACTIVE
                activity.progress = 0.0
                self._log("activity_start", activity)
                return True
        return True

    def update(self, dt, active=True):
        """Advance the running activity. ``active`` is False while walking."""
        activity = self.active
        if activity is None or not active:
            return
        activity.progress += dt / settings.ACTIVITY_TIME
        if activity.progress >= 1.0:
            activity.state = DONE
            self._log("activity_done", activity)
            if self.complete:
                self.sounds.play("all_done")
            else:
                self.sounds.play("activity_done")

    # ------------------------------------------------------------ drawing
    def draw(self, surface, enabled, t=0.0):
        fonts, x, y = self.fonts, self.rect.x, self.rect.y
        surface.blit(fonts.body.render("Things to do with your items", True,
                                       COLORS["text"]), (x, y))
        count = fonts.small.render(
            f"{self.done_count} of {len(self.activities)} done", True,
            COLORS["text_muted"])
        surface.blit(count, count.get_rect(topright=(self.rect.right, y + 3)))

        mouse = pygame.mouse.get_pos()
        can_start = enabled and self.active is None
        for index, activity in enumerate(self.activities):
            self._draw_row(surface, self._row_rect(index), activity,
                           can_start, mouse)

        if not enabled and not self.complete:
            veil = pygame.Surface(self.rect.size, pygame.SRCALPHA)
            veil.fill((*COLORS["panel"], 200))
            surface.blit(veil, self.rect.topleft)
            image = fonts.large.render("Paused while you walk...", True,
                                       COLORS["text_muted"])
            surface.blit(image, image.get_rect(center=self.rect.center))

    def _draw_row(self, surface, row, activity, can_start, mouse):
        fonts = self.fonts
        state = activity.state
        clickable = state == READY and can_start
        fill = COLORS["button"]
        border = COLORS["panel_line"]
        if clickable:
            border = COLORS["alt"]
            if row.collidepoint(mouse):
                fill = COLORS["button_hover"]
        elif state == ACTIVE:
            border = COLORS["alt"]
        pygame.draw.rect(surface, fill, row, border_radius=7)
        pygame.draw.rect(surface, border, row, 2, border_radius=7)

        dot = {LOCKED: "pending", READY: "alt", ACTIVE: "alt",
               DONE: "success", SKIPPED: "gave_up"}[state]
        pygame.draw.circle(surface, COLORS[dot], (row.x + 16, row.centery), 7)
        ink = COLORS["text"] if state in (READY, ACTIVE) else \
            COLORS["text_muted"]
        label = fonts.body.render(activity.text, True, ink)
        label_rect = label.get_rect(midleft=(row.x + 32, row.centery))
        surface.blit(label, label_rect)
        if state == SKIPPED:
            pygame.draw.line(surface, COLORS["text_muted"],
                             (label_rect.x, label_rect.centery),
                             (label_rect.right, label_rect.centery), 2)

        right = pygame.Rect(row.right - 150, row.y + 6, 140, row.h - 12)
        if state == ACTIVE:
            pygame.draw.rect(surface, COLORS["panel_line"], right,
                             border_radius=5)
            filled = right.copy()
            filled.w = max(4, int(right.w * min(1.0, activity.progress)))
            pygame.draw.rect(surface, COLORS["alt"], filled,
                             border_radius=5)
            return
        text = {LOCKED: "waiting for item", READY: "Start",
                DONE: "done", SKIPPED: "skipped"}[state]
        if state == READY:
            color = COLORS["alt"] if can_start else COLORS["text_muted"]
            image = fonts.body.render(text, True, color)
        else:
            color = COLORS["success"] if state == DONE else \
                COLORS["text_muted"]
            image = fonts.small.render(text, True, color)
        surface.blit(image, image.get_rect(midright=(right.right,
                                                     right.centery)))