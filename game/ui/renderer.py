"""All drawing of the house, agents, side panel and message screens."""
import math

import pygame

from game.settings import (COLORS, INFO_RECT, MAP_H, MAP_W, ROBOT_RECT,
                           SCREEN_H, SCREEN_W, TILE)
from game.ui.speech import wrap_text

# status -> (label on the checklist, colour key)
STATUS_STYLE = {
    "pending": ("to do", "pending"),
    "delivered": ("brought", "success"),
    "alternative": ("alternative", "alt"),
    "self": ("got it myself", "self"),
    "gave_up": ("skipped", "gave_up"),
}


def shade(color, amount):
    return tuple(max(0, min(255, c + amount)) for c in color[:3])


def is_dark(color):
    r, g, b = color[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b < 140


class Fonts:
    def __init__(self):
        self.tiny = pygame.font.Font(None, 18)
        self.small = pygame.font.Font(None, 22)
        self.body = pygame.font.Font(None, 26)
        self.large = pygame.font.Font(None, 32)
        self.title = pygame.font.Font(None, 54)


class Renderer:
    ROBOT_RADIUS = int(TILE * 0.62)

    def __init__(self, screen, world, fonts):
        self.screen = screen
        self.world = world
        self.fonts = fonts
        self.map_surface = self._build_map()

    # ------------------------------------------------------------ helpers
    def _text(self, text, font, color, pos, anchor="topleft"):
        image = font.render(text, True, color)
        rect = image.get_rect(**{anchor: pos})
        self.screen.blit(image, rect)
        return rect

    # ------------------------------------------------------------ static map
    def _build_map(self):
        surface = pygame.Surface((MAP_W, MAP_H))
        world = self.world
        for y in range(world.rows):
            for x in range(world.cols):
                rect = pygame.Rect(x * TILE, y * TILE, TILE, TILE)
                if (x, y) in world.walls:
                    surface.fill(COLORS["wall"], rect)
                    continue
                room = world.room_at((x, y))
                color = COLORS[room.color_key] if room else COLORS["door"]
                surface.fill(color, rect)
                pygame.draw.rect(surface, shade(color, -10), rect, 1)

        for room in world.rooms:
            image = self.fonts.body.render(room.name, True,
                                           shade(COLORS[room.color_key], -70))
            center = world.tile_center(room.label_tile)
            surface.blit(image, image.get_rect(center=center))

        for piece in world.furniture:
            rect = pygame.Rect(piece.x * TILE + 3, piece.y * TILE + 3,
                               piece.w * TILE - 6, piece.h * TILE - 6)
            pygame.draw.rect(surface, piece.color, rect, border_radius=6)
            pygame.draw.rect(surface, shade(piece.color, -45), rect, 2,
                             border_radius=6)
            if piece.label:
                ink = (245, 245, 245) if is_dark(piece.color) else (50, 50, 55)
                image = self.fonts.tiny.render(piece.label, True, ink)
                if image.get_width() < rect.w - 4:
                    surface.blit(image, image.get_rect(center=rect.center))
        return surface

    # ------------------------------------------------------------ scene
    def draw_scene(self, ctrl, t):
        self.screen.blit(self.map_surface, (0, 0))
        self._draw_avatar(ctrl.avatar)
        if ctrl.waiting_for_user:
            pulse = (math.sin(t * 5) + 1) / 2
            radius = self.ROBOT_RADIUS + 5 + int(4 * pulse)
            pygame.draw.circle(self.screen, COLORS["alt"],
                               (int(ctrl.robot.pos.x), int(ctrl.robot.pos.y)),
                               radius, 3)
        self._draw_robot(ctrl.robot, t)
        if ctrl.robot_speech:
            self._draw_bubble(ctrl.robot_speech, ctrl.robot.pos)

    def _draw_avatar(self, avatar):
        x, y = int(avatar.pos.x), int(avatar.pos.y)
        k = TILE / 36           # drawn at 36 px tiles, scaled from there
        body = pygame.Rect(0, 0, int(24 * k), int(18 * k))
        body.center = (x, y + int(5 * k))
        pygame.draw.ellipse(self.screen, COLORS["cardigan"], body)
        pygame.draw.ellipse(self.screen, shade(COLORS["cardigan"], -50),
                            body, 2)
        head = (x, y - int(8 * k))
        radius = int(9 * k)
        pygame.draw.circle(self.screen, COLORS["skin"], head, radius)
        pygame.draw.circle(self.screen, COLORS["hair"],
                           (x, head[1] - int(2 * k)), radius,
                           draw_top_left=True, draw_top_right=True)
        pygame.draw.circle(self.screen, (90, 80, 70), head, radius, 1)
        if avatar.walking:
            pygame.draw.line(self.screen, COLORS["cane"],
                             (x + int(13 * k), y - int(2 * k)),
                             (x + int(16 * k), y + int(16 * k)), 3)
        if avatar.carrying:
            self._draw_badge(avatar.carrying, x, y + int(16 * k))

    def _draw_robot(self, robot, t):
        x, y = int(robot.pos.x), int(robot.pos.y)
        r = self.ROBOT_RADIUS
        pygame.draw.circle(self.screen, COLORS["robot_body"], (x, y), r)
        pygame.draw.circle(self.screen, COLORS["robot_outline"], (x, y), r, 2)
        screen_rect = pygame.Rect(0, 0, int(r * 1.35), int(r * 0.95))
        screen_rect.center = (x, y)
        pygame.draw.rect(self.screen, COLORS["robot_screen"], screen_rect,
                         border_radius=5)
        self.draw_face(self.screen, screen_rect, robot.face, t)
        if robot.working:
            lit = int(t * 3) % 3
            for i in range(3):
                color = COLORS["text"] if i <= lit else COLORS["pending"]
                pygame.draw.circle(self.screen, color,
                                   (x - 10 + 10 * i, y - r - 9), 4)
        if robot.carrying:
            self._draw_badge(robot.carrying, x, y + r + 4)

    def draw_face(self, surface, rect, face, t=0.0):
        """Draw the robot's LCD face into ``rect`` (any size)."""
        color = COLORS["robot_face"]
        cx, cy = rect.center
        w, h = rect.w, rect.h
        eye_r = max(2, int(h * 0.11))
        eye_dx = int(w * 0.2)
        eye_y = cy - int(h * 0.14)
        line = max(2, int(h * 0.08))
        mouth_w, mouth_h = int(w * 0.38), int(h * 0.36)
        look = 0
        if face == "thinking":
            eye_y -= int(h * 0.06)
            look = int(w * 0.05 * math.sin(t * 3))
        for side in (-1, 1):
            pygame.draw.circle(surface, color,
                               (cx + side * eye_dx + look, eye_y), eye_r)
        if face == "happy":
            box = pygame.Rect(cx - mouth_w // 2, cy - mouth_h // 3,
                              mouth_w, mouth_h)
            pygame.draw.arc(surface, color, box, math.pi, 2 * math.pi, line)
        elif face == "sad":
            box = pygame.Rect(cx - mouth_w // 2, cy + int(h * 0.14),
                              mouth_w, mouth_h)
            pygame.draw.arc(surface, color, box, 0, math.pi, line)
        elif face == "thinking":
            y = cy + int(h * 0.22)
            pygame.draw.line(surface, color, (cx - mouth_w // 6, y),
                             (cx + mouth_w // 2, y - int(h * 0.05)), line)
        else:
            y = cy + int(h * 0.22)
            pygame.draw.line(surface, color, (cx - mouth_w // 2, y),
                             (cx + mouth_w // 2, y), line)

    def _draw_badge(self, text, center_x, top_y):
        image = self.fonts.tiny.render(text, True, COLORS["text"])
        rect = image.get_rect(midtop=(center_x, top_y + 3)).inflate(10, 6)
        pygame.draw.rect(self.screen, COLORS["badge"], rect, border_radius=5)
        pygame.draw.rect(self.screen, COLORS["self"], rect, 1,
                         border_radius=5)
        self.screen.blit(image, image.get_rect(center=rect.center))

    def _draw_bubble(self, text, anchor):
        font, pad = self.fonts.body, 10
        lines = wrap_text(text, font, 300)
        line_h = font.get_linesize()
        width = max(font.size(line)[0] for line in lines) + 2 * pad
        height = len(lines) * line_h + 2 * pad
        ax, ay = int(anchor.x), int(anchor.y)
        x = max(6, min(ax - width // 2, MAP_W - width - 6))
        y = ay - self.ROBOT_RADIUS - 16 - height
        above = y >= 6
        if not above:
            y = ay + self.ROBOT_RADIUS + 16
        rect = pygame.Rect(x, y, width, height)
        tip_x = max(rect.left + 14, min(ax, rect.right - 14))
        if above:
            tail = [(tip_x - 8, rect.bottom - 2), (tip_x + 8, rect.bottom - 2),
                    (ax, ay - self.ROBOT_RADIUS - 2)]
        else:
            tail = [(tip_x - 8, rect.top + 2), (tip_x + 8, rect.top + 2),
                    (ax, ay + self.ROBOT_RADIUS + 2)]
        pygame.draw.polygon(self.screen, COLORS["bubble"], tail)
        pygame.draw.polygon(self.screen, COLORS["robot_outline"], tail, 2)
        pygame.draw.rect(self.screen, COLORS["bubble"], rect,
                         border_radius=10)
        pygame.draw.rect(self.screen, COLORS["robot_outline"], rect, 2,
                         border_radius=10)
        # hide the tail's outline where it meets the bubble
        seam_y = rect.bottom - 2 if above else rect.top + 1
        pygame.draw.line(self.screen, COLORS["bubble"],
                         (tip_x - 6, seam_y), (tip_x + 6, seam_y), 3)
        for i, line in enumerate(lines):
            self.screen.blit(font.render(line, True, COLORS["text"]),
                             (rect.x + pad, rect.y + pad + i * line_h))

    # ------------------------------------------------------------ info panel
    def draw_info_panel(self, ctrl, block_label, t):
        """Right of the map: part, timer, goal, robot screen, item list."""
        panel = pygame.Rect(INFO_RECT)
        self.screen.fill(COLORS["panel"], panel)
        pygame.draw.line(self.screen, COLORS["panel_line"], panel.topleft,
                         panel.bottomleft, 2)
        x = panel.x + 18
        self._text(block_label, self.fonts.small, COLORS["text_muted"],
                   (x, 16))
        self._text(ctrl.block.title, self.fonts.large, COLORS["text"],
                   (x, 36))
        left = ctrl.time_left
        if left > 0:
            minutes, seconds = divmod(int(math.ceil(left)), 60)
            timer = f"Time left  {minutes}:{seconds:02d}"
            color = COLORS["warning"] if left < 30 else COLORS["text"]
        else:
            timer, color = "Running late!", COLORS["warning"]
        self._text(timer, self.fonts.body, color, (x, 72))

        lcd = pygame.Rect(panel.right - 150, 16, 130, 78)
        pygame.draw.rect(self.screen, COLORS["robot_outline"],
                         lcd.inflate(8, 8), border_radius=10)
        pygame.draw.rect(self.screen, COLORS["robot_screen"], lcd,
                         border_radius=8)
        self.draw_face(self.screen, lcd, ctrl.robot.face, t)
        self._text("robot", self.fonts.tiny, COLORS["text_muted"],
                   (lcd.centerx, lcd.bottom + 6), anchor="midtop")

        y = 122
        for line in wrap_text(ctrl.block.goal, self.fonts.small,
                              panel.w - 36)[:2]:
            self._text(line, self.fonts.small, COLORS["text"], (x, y))
            y += 20

        y = max(y + 14, 176)
        self._text("Your list", self.fonts.body, COLORS["text"], (x, y))
        y += 30
        for item in ctrl.block.items:
            status = ctrl.status[item.item_id]
            label, color_key = STATUS_STYLE[status]
            row = pygame.Rect(x - 8, y - 5, panel.w - 20, 30)
            if ctrl.current is item:
                pygame.draw.rect(self.screen, COLORS["highlight"], row,
                                 border_radius=6)
            pygame.draw.circle(self.screen, COLORS[color_key],
                               (x + 7, y + 9), 7)
            ink = COLORS["text"] if status == "pending" else \
                COLORS["text_muted"]
            name = item.name[0].upper() + item.name[1:]
            self._text(name, self.fonts.body, ink, (x + 22, y))
            self._text(label, self.fonts.small, COLORS["text_muted"],
                       (row.right - 10, y + 2), anchor="topright")
            y += 32

    def fill_panel(self, rect):
        """Plain panel background with a separator on the top and left."""
        rect = pygame.Rect(rect)
        self.screen.fill(COLORS["panel"], rect)
        pygame.draw.line(self.screen, COLORS["panel_line"], rect.topleft,
                         rect.topright, 2)
        pygame.draw.line(self.screen, COLORS["panel_line"], rect.topleft,
                         rect.bottomleft, 2)

    # ------------------------------------------------------------ robot band
    def draw_robot_band(self, ctrl, side_task_done, t):
        """Bottom-left band: robot status and what the robot just said.

        The answer buttons (DialogPanel) are drawn below this, in the same
        band, right next to the side task.
        """
        band = pygame.Rect(ROBOT_RECT)
        self.screen.fill(COLORS["panel"], band)
        pygame.draw.line(self.screen, COLORS["panel_line"], band.topleft,
                         band.topright, 2)
        strip = pygame.Rect(band.x + 14, band.y + 10, band.w - 28, 32)
        self.draw_status_strip(ctrl, strip, side_task_done, t)
        if ctrl.robot_speech:
            lines = wrap_text(f"Robot: \u201c{ctrl.robot_speech}\u201d",
                              self.fonts.body, band.w - 40)[:2]
            for i, line in enumerate(lines):
                self._text(line, self.fonts.body, COLORS["text"],
                           (band.x + 20, band.y + 52 + i * 24))

    # ------------------------------------------------------------ cue strip
    STRIP_TEXT = {
        "back": "The robot is back!",
        "waiting_answer": "The robot is waiting for your answer",
        "waiting_request": "The robot is ready for a new request",
        "busy": "The robot is busy...",
        "self": "You are walking...",
    }

    def draw_status_strip(self, ctrl, rect, side_task_done, t):
        """Robot status next to the side task, where the eyes are."""
        phase = ctrl.phase
        if phase == "done":
            if side_task_done:
                return
            text = "Your list is done: finish your activities!"
        else:
            text = self.STRIP_TEXT[phase]
        pulse = (math.sin(t * 5) + 1) / 2
        fill, border, ink = COLORS["button"], COLORS["panel_line"], \
            COLORS["text_muted"]
        if phase == "back":
            flash = ctrl.seconds_since("robot_back") < 1.5 and pulse > 0.5
            fill = (255, 226, 130) if flash else COLORS["badge"]
            border, ink = COLORS["self"], COLORS["text"]
        elif phase in ("waiting_answer", "waiting_request"):
            fill = tuple(int(a + (b - a) * pulse) for a, b in
                         zip(COLORS["button"], COLORS["highlight"]))
            border, ink = COLORS["alt"], COLORS["text"]
        elif phase == "done":
            border, ink = COLORS["success"], COLORS["text"]
        pygame.draw.rect(self.screen, fill, rect, border_radius=8)
        pygame.draw.rect(self.screen, border, rect, 2, border_radius=8)
        lcd = pygame.Rect(rect.x + 6, rect.y + 4, 34, rect.h - 8)
        pygame.draw.rect(self.screen, COLORS["robot_screen"], lcd,
                         border_radius=4)
        self.draw_face(self.screen, lcd, ctrl.robot.face, t)
        self._text(text, self.fonts.body, ink, (lcd.right + 10, rect.centery),
                   anchor="midleft")

    # ------------------------------------------------------------ screens
    def draw_message(self, title, paragraphs, footer):
        """Centered card that grows to fit its text."""
        self.screen.fill(COLORS["bg"])
        font, line_h, gap = self.fonts.body, 28, 14
        width = 820
        wrapped = [wrap_text(p, font, width - 120) for p in paragraphs]
        n_lines = sum(len(lines) for lines in wrapped)
        # long instructions read better left-aligned, short notes centered
        centered = n_lines <= 3
        text_h = n_lines * line_h + gap * (len(wrapped) - 1)
        card = pygame.Rect(0, 0, width, 120 + text_h + 90)
        card.height = min(card.height, SCREEN_H - 20)
        card.center = (SCREEN_W // 2, SCREEN_H // 2)
        pygame.draw.rect(self.screen, COLORS["panel"], card, border_radius=16)
        self._text(title, self.fonts.title, COLORS["text"],
                   (card.centerx, card.y + 56), anchor="center")
        y = card.y + 104
        for lines in wrapped:
            for line in lines:
                if centered:
                    self._text(line, font, COLORS["text"],
                               (card.centerx, y), anchor="midtop")
                else:
                    self._text(line, font, COLORS["text"], (card.x + 60, y))
                y += line_h
            y += gap
        self._text(footer, font, COLORS["text_muted"],
                   (card.centerx, card.bottom - 40), anchor="center")