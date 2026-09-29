"""Entry point.

Usage (from the repository root)::

    python -m game.main --pid P01                # random condition order
    python -m game.main --pid P01 --balanced     # order from participant no.
    python -m game.main --pid P03 --tts --fullscreen
    python -m game.main --pid TEST --fast 4 --echo     # quick pilot run
"""
import argparse

import pygame

from game import settings
from game.core.logger import EventLogger
from game.core.session import build_session
from game.core.state_machine import BlockController
from game.core.world import World
from game.ui.dialog_panel import DialogPanel
from game.ui.minigame import ScarfKnitting, validate_rows
from game.ui.renderer import Fonts, Renderer
from game.ui.sounds import SoundBank
from game.ui.speech import Voice

INTRO_TEXT = [
    "In this game you are an older person living at home with a helper "
    "robot. Walking is hard for you, so the robot fetches things for you.",
    "Ask the robot for the items on your list with the buttons at the "
    "bottom (mouse or number keys).",
    "At the same time, knit a scarf on the right: pick a yarn colour and "
    "the row knits by itself. Pick the next colour whenever it suits you.",
    "Each part is finished when all items are sorted AND the scarf is "
    "done. A chime tells you when the robot is back or needs you.",
    "We start with a short practice round.",
]

INTRO, BLOCK_INTRO, PLAYING, BLOCK_END, FINISHED = range(5)
ESC_WINDOW_MS = 1500


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Home-care robot game")
    parser.add_argument("--pid", default="P00",
                        help="participant id, e.g. P07")
    parser.add_argument("--order", type=int, default=None,
                        help="force condition order index (0-5)")
    parser.add_argument("--balanced", action="store_true",
                        help="pick the order from the participant number "
                             "instead of at random")
    parser.add_argument("--no-tutorial", action="store_true",
                        help="skip the practice block")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--tts", action="store_true",
                        help="speak robot lines (needs pyttsx3)")
    parser.add_argument("--mute", action="store_true",
                        help="no cue sounds")
    parser.add_argument("--log-dir", default=str(settings.DEFAULT_LOG_DIR))
    parser.add_argument("--echo", action="store_true",
                        help="also print every log row to the console")
    parser.add_argument("--fast", type=float, default=1.0,
                        help="time multiplier for testing (never in study)")
    return parser.parse_args(argv)


class App:
    """Screens, main loop and block sequencing."""

    def __init__(self, args):
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        flags = pygame.FULLSCREEN | pygame.SCALED if args.fullscreen else 0
        self.screen = pygame.display.set_mode(
            (settings.SCREEN_W, settings.SCREEN_H), flags)
        pygame.display.set_caption("Home helper robot")
        self.clock = pygame.time.Clock()
        self.speed = args.fast

        self.world = World()
        if args.order is not None:
            assignment = "forced"
        else:
            assignment = "balanced" if args.balanced else "random"
        self.blocks, order_index, order = build_session(
            args.pid, args.order, include_tutorial=not args.no_tutorial,
            assignment=assignment)
        self._validate_spots()

        self.logger = EventLogger(args.log_dir, args.pid, echo=args.echo)
        self.logger.set_context(order=order_index)
        self.logger.log("system", "session_start",
                        detail=(f"order={'/'.join(order)};"
                                f"assignment={assignment};fast={args.fast}"))

        self.fonts = Fonts()
        self.renderer = Renderer(self.screen, self.world, self.fonts)
        band = pygame.Rect(settings.ROBOT_RECT)
        self.dialog = DialogPanel(
            (band.x, band.y + 100, band.w, band.h - 100), self.fonts)
        self.sounds = SoundBank(settings.SOUND_ENABLED and not args.mute)
        self.side_panel = pygame.Rect(settings.SIDE_TASK_RECT)
        self.minigame = ScarfKnitting(
            self.side_panel.inflate(-32, -18), self.fonts, self.logger,
            self.sounds)
        self.voice = Voice(args.tts or settings.USE_TTS)

        self.mode = INTRO
        self.block_index = -1
        self.controller = None
        self.end_delay = 0.0
        self.t = 0.0
        self.last_esc = -ESC_WINDOW_MS
        self.running = True

    def _validate_spots(self):
        """Fail at start-up, not mid-session, if a config names a bad spot."""
        for block in self.blocks:
            for item in block.items:
                self.world.spot(item.spot)
                if item.failure:
                    self.world.spot(item.failure.stop_spot)
                    if item.failure.alternative.fetch_spot:
                        self.world.spot(item.failure.alternative.fetch_spot)
            validate_rows(block.scarf_rows)

    # ------------------------------------------------------------ loop
    def run(self):
        while self.running:
            dt = self.clock.tick(settings.FPS) / 1000.0 * self.speed
            self.step(dt, pygame.event.get())
            pygame.display.flip()
        self.shutdown()

    def step(self, dt, events):
        """One frame; separated from ``run`` so tests can drive it."""
        self.t += dt
        for event in events:
            self.handle_event(event)
        self.update(dt)
        self.draw()

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.abort("window_closed")
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            now = pygame.time.get_ticks()
            if now - self.last_esc < ESC_WINDOW_MS or self.mode == FINISHED:
                self.abort("escape")
            self.last_esc = now
            return

        key = getattr(event, "key", None)
        if self.mode == INTRO and key == pygame.K_SPACE:
            self._next_block()
        elif self.mode == BLOCK_INTRO and key == pygame.K_SPACE:
            self._start_block()
        elif self.mode == BLOCK_END and key in (pygame.K_RETURN,
                                                pygame.K_KP_ENTER):
            self._next_block()
        elif self.mode == FINISHED and key in (pygame.K_SPACE,
                                               pygame.K_RETURN):
            self.running = False
        elif self.mode == PLAYING:
            ctrl = self.controller
            if settings.MINIGAME_ENABLED and self.minigame.handle_event(
                    event, ctrl.hands_free):
                return
            action = self.dialog.handle_event(event)
            if action and ctrl.accepts_input:
                ctrl.handle_action(action)

    @property
    def side_task_done(self):
        return not settings.MINIGAME_ENABLED or self.minigame.complete

    def update(self, dt):
        if self.mode != PLAYING:
            return
        self.controller.update(dt)
        self.minigame.update(dt, self.controller.hands_free)
        for cue in self.controller.pop_cues():
            self.sounds.play(cue)
            self.logger.log("system", "cue", detail=cue)
        # A block ends only when the list AND the organiser are complete
        if self.controller.done and self.side_task_done:
            self.end_delay += dt
            if self.end_delay >= settings.BLOCK_END_DELAY:
                self._finish_block()

    def draw(self):
        if self.mode == INTRO:
            self.renderer.draw_message("Welcome!", INTRO_TEXT,
                                       "Press SPACE to begin")
        elif self.mode == BLOCK_INTRO:
            block = self.current_block
            label = self._block_label(block)
            title = label if label == block.title else \
                f"{label}: {block.title}"
            self.renderer.draw_message(
                title,
                [block.goal,
                 "Get everything on your list with the robot's help and knit "
                 "the scarf. Both must be done to finish."],
                "Press SPACE to start")
        elif self.mode == PLAYING:
            ctrl = self.controller
            self.renderer.draw_scene(ctrl, self.t)
            self.renderer.draw_info_panel(
                ctrl, self._block_label(self.current_block), self.t)
            self.renderer.draw_robot_band(ctrl, self.side_task_done, self.t)
            prompt, options = ctrl.dialog_content()
            if ctrl.done and not self.side_task_done:
                prompt = "Your list is done. Finish the scarf to continue."
            self.dialog.set_options(prompt, options)
            self.dialog.draw(self.screen, ctrl.waiting_for_user, self.t)
            self.renderer.fill_panel(self.side_panel)
            if settings.MINIGAME_ENABLED:
                self.minigame.draw(self.screen, ctrl.hands_free, self.t)
        elif self.mode == BLOCK_END:
            block = self.current_block
            if block.is_tutorial:
                title, text = "Practice complete", \
                    "Well done! The researcher will tell you when to go on."
            else:
                title, text = f"{self._block_label(block)} complete", \
                    "Please fill in the questionnaire for this part now."
            self.renderer.draw_message(title, [text],
                                       "Researcher: press ENTER to continue")
        elif self.mode == FINISHED:
            self.renderer.draw_message(
                "All done!", ["Thank you for taking part."],
                "Researcher: press SPACE to close")

    # ------------------------------------------------------------ blocks
    @property
    def current_block(self):
        return self.blocks[self.block_index]

    def _block_label(self, block):
        if block.is_tutorial:
            return "Practice"
        parts = [b for b in self.blocks if not b.is_tutorial]
        return f"Part {parts.index(block) + 1} of {len(parts)}"

    def _next_block(self):
        self.block_index += 1
        if self.block_index >= len(self.blocks):
            self.logger.set_context(block_index="", block_id="",
                                    condition="")
            self.logger.log("system", "session_end")
            self.mode = FINISHED
            return
        block = self.current_block
        self.logger.set_context(block_index=block.index,
                                block_id=block.block_id,
                                condition=block.condition)
        self.controller = BlockController(block, self.world, self.logger,
                                          self.voice)
        self.minigame.start_block(block.scarf_rows)
        self.end_delay = 0.0
        self.mode = BLOCK_INTRO

    def _start_block(self):
        self.logger.log("system", "block_start",
                        detail=self.current_block.title)
        self.mode = PLAYING

    def _finish_block(self):
        ctrl = self.controller
        counts = {}
        for status in ctrl.status.values():
            counts[status] = counts.get(status, 0) + 1
        summary = ";".join(f"{k}={v}" for k, v in sorted(counts.items()))
        self.logger.log("system", "block_end",
                        detail=(f"{summary};scarf_rows="
                                f"{len(self.minigame.rows)};"
                                f"duration={ctrl.elapsed:.1f}"))
        self.mode = BLOCK_END

    # ------------------------------------------------------------ exit
    def abort(self, reason):
        if self.mode != FINISHED:
            self.logger.log("system", "session_aborted", detail=reason)
        self.running = False

    def shutdown(self):
        self.voice.close()
        self.logger.close()
        pygame.quit()


def main(argv=None):
    App(parse_args(argv)).run()


if __name__ == "__main__":
    main()
