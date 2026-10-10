"""经典坦克大战：方向键/WASD 移动，空格射击，R 重开。"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, List, Optional, Sequence, Tuple

import pygame

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
TILE = 32
COLS, ROWS = 13, 13
HUD_H = 48
WIDTH, HEIGHT = COLS * TILE, ROWS * TILE + HUD_H
FPS = 60

DIR_UP, DIR_RIGHT, DIR_DOWN, DIR_LEFT = 0, 1, 2, 3
VEC = ((0, -1), (1, 0), (0, 1), (-1, 0))

PLAYER_SPEED = 2.2
ENEMY_SPEED = 1.35
BULLET_SPEED = 6.0
PLAYER_COOLDOWN = 280
ENEMY_COOLDOWN = 900
PLAYER_LIVES = 3
ENEMIES_TO_SPAWN = 12
MAX_ENEMIES_ON_MAP = 4
SPAWN_INTERVAL_MS = 2500

COLOR_BG = (18, 18, 18)
COLOR_HUD = (28, 28, 32)
COLOR_TEXT = (230, 230, 230)
COLOR_BRICK = (176, 82, 48)
COLOR_BRICK_LINE = (120, 48, 28)
COLOR_STEEL = (168, 176, 184)
COLOR_STEEL_LINE = (90, 98, 108)
COLOR_WATER = (32, 96, 176)
COLOR_GRASS = (40, 140, 56)
COLOR_BASE = (220, 200, 80)
COLOR_PLAYER = (70, 180, 70)
COLOR_ENEMY = (190, 70, 70)
COLOR_ENEMY_FAST = (220, 140, 40)
COLOR_BULLET_P = (255, 230, 90)
COLOR_BULLET_E = (255, 120, 80)


class Cell(IntEnum):
    EMPTY = 0
    BRICK = 1
    STEEL = 2
    WATER = 3
    GRASS = 4
    BASE = 5


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: int
    color: Tuple[int, int, int]
    size: int


# 13x13 关卡：B 砖块 S 钢块 W 水 G 草 E 基地 P 玩家出生点 . 空
LEVEL = [
    ".............",
    ".BBB...BBB...",
    ".B.B...B.B...",
    ".BBB.S.BBB...",
    ".....S.......",
    ".WWW...WWW...",
    ".W.W.G.W.W...",
    ".WWW...WWW...",
    ".....S.......",
    ".BBB.S.BBB...",
    ".B.B...B.B...",
    ".BBB...BBEBB.",
    "......P......",
]


def parse_level(rows: Sequence[str]) -> Tuple[List[List[int]], Tuple[int, int], List[Tuple[int, int]], Tuple[int, int]]:
    grid = [[Cell.EMPTY for _ in range(COLS)] for _ in range(ROWS)]
    player = (6 * TILE, (ROWS - 1) * TILE)
    enemy_spawns = [(0, 0), (6 * TILE, 0), (12 * TILE, 0)]
    base = (6 * TILE, 11 * TILE)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == "B":
                grid[y][x] = Cell.BRICK
            elif ch == "S":
                grid[y][x] = Cell.STEEL
            elif ch == "W":
                grid[y][x] = Cell.WATER
            elif ch == "G":
                grid[y][x] = Cell.GRASS
            elif ch == "E":
                grid[y][x] = Cell.BASE
                base = (x * TILE, y * TILE)
            elif ch == "P":
                player = (x * TILE, y * TILE)
    return grid, player, enemy_spawns, base


class Tank:
    def __init__(
        self,
        x: float,
        y: float,
        color: Tuple[int, int, int],
        speed: float,
        cooldown: int,
        is_player: bool = False,
        fast: bool = False,
    ) -> None:
        self.x = float(x)
        self.y = float(y)
        self.dir = DIR_UP if is_player else DIR_DOWN
        self.color = color
        self.speed = speed
        self.cooldown = cooldown
        self.last_shot = -99999
        self.is_player = is_player
        self.fast = fast
        self.alive = True
        self.ai_timer = 0
        self.size = TILE - 4

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x) + 2, int(self.y) + 2, self.size, self.size)

    def center(self) -> Tuple[float, float]:
        return self.x + TILE / 2, self.y + TILE / 2

    def muzzle(self) -> Tuple[float, float]:
        cx, cy = self.center()
        dx, dy = VEC[self.dir]
        return cx + dx * (self.size / 2 + 4), cy + dy * (self.size / 2 + 4)


class Bullet:
    def __init__(self, x: float, y: float, direction: int, from_player: bool) -> None:
        self.x = x
        self.y = y
        self.dir = direction
        self.from_player = from_player
        self.alive = True
        self.r = 4

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x - self.r), int(self.y - self.r), self.r * 2, self.r * 2)


class Game:
    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("坦克大战")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("microsoftyahei,simhei,arial", 22)
        self.big = pygame.font.SysFont("microsoftyahei,simhei,arial", 42, bold=True)
        self.reset()

    def reset(self) -> None:
        self.grid, spawn, self.enemy_spawns, self.base_pos = parse_level(LEVEL)
        self.player = Tank(*spawn, COLOR_PLAYER, PLAYER_SPEED, PLAYER_COOLDOWN, is_player=True)
        self.enemies: List[Tank] = []
        self.bullets: List[Bullet] = []
        self.particles: List[Particle] = []
        self.lives = PLAYER_LIVES
        self.score = 0
        self.remaining = ENEMIES_TO_SPAWN
        self.last_spawn = 0
        self.state = "play"  # play / win / lose
        self.message = ""
        self.spawn_enemy(pygame.time.get_ticks())

    def cells_for_rect(self, rect: pygame.Rect) -> Iterable[Tuple[int, int]]:
        x0 = max(0, rect.left // TILE)
        y0 = max(0, rect.top // TILE)
        x1 = min(COLS - 1, (rect.right - 1) // TILE)
        y1 = min(ROWS - 1, (rect.bottom - 1) // TILE)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                yield x, y

    def blocked(self, rect: pygame.Rect, ignore_water: bool = False) -> bool:
        if rect.left < 0 or rect.top < 0 or rect.right > COLS * TILE or rect.bottom > ROWS * TILE:
            return True
        for x, y in self.cells_for_rect(rect):
            cell = self.grid[y][x]
            if cell in (Cell.BRICK, Cell.STEEL, Cell.BASE):
                return True
            if cell == Cell.WATER and not ignore_water:
                return True
        return False

    def try_move(self, tank: Tank, dx: float, dy: float) -> None:
        nx, ny = tank.x + dx, tank.y + dy
        probe = pygame.Rect(int(nx) + 2, int(ny) + 2, tank.size, tank.size)
        if not self.blocked(probe):
            others = [self.player] + self.enemies
            for other in others:
                if other is tank or not other.alive:
                    continue
                if probe.colliderect(other.rect.inflate(-6, -6)):
                    return
            tank.x, tank.y = nx, ny

    def spawn_enemy(self, now: int) -> None:
        if self.remaining <= 0 or len([e for e in self.enemies if e.alive]) >= MAX_ENEMIES_ON_MAP:
            return
        random.shuffle(self.enemy_spawns)
        for sx, sy in self.enemy_spawns:
            probe = pygame.Rect(sx + 2, sy + 2, TILE - 4, TILE - 4)
            occupied = probe.colliderect(self.player.rect)
            occupied = occupied or any(e.alive and probe.colliderect(e.rect) for e in self.enemies)
            if occupied:
                continue
            fast = random.random() < 0.28
            color = COLOR_ENEMY_FAST if fast else COLOR_ENEMY
            speed = ENEMY_SPEED * 1.45 if fast else ENEMY_SPEED
            self.enemies.append(Tank(sx, sy, color, speed, ENEMY_COOLDOWN, fast=fast))
            self.remaining -= 1
            self.last_spawn = now
            return

    def shoot(self, tank: Tank, now: int) -> None:
        if not tank.alive or now - tank.last_shot < tank.cooldown:
            return
        mx, my = tank.muzzle()
        self.bullets.append(Bullet(mx, my, tank.dir, tank.is_player))
        tank.last_shot = now

    def explode(self, x: float, y: float, color: Tuple[int, int, int], n: int = 14) -> None:
        for _ in range(n):
            ang = random.random() * math.tau
            spd = random.uniform(0.6, 3.4)
            self.particles.append(
                Particle(
                    x,
                    y,
                    math.cos(ang) * spd,
                    math.sin(ang) * spd,
                    random.randint(12, 26),
                    color,
                    random.randint(2, 5),
                )
            )

    def hit_map(self, bullet: Bullet) -> None:
        r = bullet.rect
        for x, y in self.cells_for_rect(r):
            cell = self.grid[y][x]
            if cell == Cell.BRICK:
                self.grid[y][x] = Cell.EMPTY
                bullet.alive = False
                self.explode(bullet.x, bullet.y, COLOR_BRICK, 10)
                return
            if cell == Cell.STEEL:
                bullet.alive = False
                self.explode(bullet.x, bullet.y, COLOR_STEEL, 6)
                return
            if cell == Cell.BASE:
                self.grid[y][x] = Cell.EMPTY
                bullet.alive = False
                self.explode(bullet.x, bullet.y, COLOR_BASE, 28)
                self.lose("基地被摧毁")
                return

    def lose(self, msg: str) -> None:
        self.state = "lose"
        self.message = msg
        self.player.alive = False

    def win_if_cleared(self) -> None:
        if self.remaining == 0 and not any(e.alive for e in self.enemies):
            self.state = "win"
            self.message = "全歼敌军！"

    def respawn_player(self) -> None:
        self.lives -= 1
        if self.lives <= 0:
            self.lose("坦克被击毁")
            return
        _, spawn, _, _ = parse_level(LEVEL)
        self.player.x, self.player.y = spawn
        self.player.dir = DIR_UP
        self.player.alive = True

    def handle_player(self, now: int) -> None:
        if not self.player.alive or self.state != "play":
            return
        keys = pygame.key.get_pressed()
        dx = dy = 0.0
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            self.player.dir = DIR_LEFT
            dx = -self.player.speed
        elif keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            self.player.dir = DIR_RIGHT
            dx = self.player.speed
        elif keys[pygame.K_UP] or keys[pygame.K_w]:
            self.player.dir = DIR_UP
            dy = -self.player.speed
        elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
            self.player.dir = DIR_DOWN
            dy = self.player.speed
        if dx or dy:
            self.try_move(self.player, dx, dy)
        if keys[pygame.K_SPACE]:
            self.shoot(self.player, now)

    def handle_enemies(self, now: int) -> None:
        if self.state != "play":
            return
        px, py = self.player.center()
        bx, by = self.base_pos[0] + TILE / 2, self.base_pos[1] + TILE / 2
        for e in self.enemies:
            if not e.alive:
                continue
            e.ai_timer -= 1
            if e.ai_timer <= 0:
                e.ai_timer = random.randint(18, 55)
                target_x, target_y = (px, py) if random.random() < 0.55 else (bx, by)
                ex, ey = e.center()
                choices = []
                if abs(target_x - ex) > abs(target_y - ey):
                    choices.append(DIR_RIGHT if target_x > ex else DIR_LEFT)
                    choices.append(DIR_DOWN if target_y > ey else DIR_UP)
                else:
                    choices.append(DIR_DOWN if target_y > ey else DIR_UP)
                    choices.append(DIR_RIGHT if target_x > ex else DIR_LEFT)
                choices.append(random.randint(0, 3))
                e.dir = choices[0]
            dx, dy = VEC[e.dir]
            old = (e.x, e.y)
            self.try_move(e, dx * e.speed, dy * e.speed)
            if (e.x, e.y) == old:
                e.dir = random.randint(0, 3)
                e.ai_timer = 8
            if random.random() < 0.018 or (abs(e.x - self.player.x) < 8 and e.dir in (DIR_UP, DIR_DOWN)):
                self.shoot(e, now)
            if random.random() < 0.012:
                self.shoot(e, now)

        if now - self.last_spawn > SPAWN_INTERVAL_MS:
            self.spawn_enemy(now)

    def handle_bullets(self) -> None:
        for b in self.bullets:
            if not b.alive:
                continue
            dx, dy = VEC[b.dir]
            b.x += dx * BULLET_SPEED
            b.y += dy * BULLET_SPEED
            if b.x < 0 or b.y < 0 or b.x > COLS * TILE or b.y > ROWS * TILE:
                b.alive = False
                continue
            self.hit_map(b)
            if not b.alive:
                continue
            if b.from_player:
                for e in self.enemies:
                    if e.alive and e.rect.collidepoint(b.x, b.y):
                        e.alive = False
                        b.alive = False
                        self.score += 200 if e.fast else 100
                        self.explode(b.x, b.y, e.color, 18)
                        self.win_if_cleared()
                        break
            else:
                if self.player.alive and self.player.rect.collidepoint(b.x, b.y):
                    b.alive = False
                    self.explode(b.x, b.y, COLOR_PLAYER, 18)
                    self.respawn_player()
            for other in self.bullets:
                if other is b or not other.alive:
                    continue
                if other.from_player != b.from_player and other.rect.colliderect(b.rect):
                    other.alive = False
                    b.alive = False
                    self.explode(b.x, b.y, (240, 240, 240), 8)
                    break
        self.bullets = [b for b in self.bullets if b.alive]
        self.enemies = [e for e in self.enemies if e.alive]

    def update_particles(self) -> None:
        for p in self.particles:
            p.x += p.vx
            p.y += p.vy
            p.life -= 1
        self.particles = [p for p in self.particles if p.life > 0]

    def draw_tank(self, tank: Tank) -> None:
        r = tank.rect
        pygame.draw.rect(self.screen, tank.color, r, border_radius=4)
        pygame.draw.rect(self.screen, (20, 20, 20), r, 2, border_radius=4)
        cx, cy = r.center
        dx, dy = VEC[tank.dir]
        barrel = pygame.Rect(0, 0, 8, 18)
        barrel.center = (cx + dx * 10, cy + dy * 10)
        if tank.dir in (DIR_LEFT, DIR_RIGHT):
            barrel.size = (18, 8)
            barrel.center = (cx + dx * 10, cy + dy * 10)
        pygame.draw.rect(self.screen, (30, 30, 30), barrel, border_radius=2)
        pygame.draw.circle(self.screen, (40, 40, 40), (cx, cy), 6)

    def draw_cell(self, x: int, y: int, cell: int) -> None:
        rx, ry = x * TILE, y * TILE
        rect = pygame.Rect(rx, ry, TILE, TILE)
        if cell == Cell.BRICK:
            pygame.draw.rect(self.screen, COLOR_BRICK, rect)
            for i in range(0, TILE, 8):
                pygame.draw.line(self.screen, COLOR_BRICK_LINE, (rx, ry + i), (rx + TILE, ry + i), 1)
            pygame.draw.line(self.screen, COLOR_BRICK_LINE, (rx + TILE // 2, ry), (rx + TILE // 2, ry + TILE), 1)
        elif cell == Cell.STEEL:
            pygame.draw.rect(self.screen, COLOR_STEEL, rect)
            pygame.draw.rect(self.screen, COLOR_STEEL_LINE, rect, 3)
            pygame.draw.line(self.screen, COLOR_STEEL_LINE, (rx, ry), (rx + TILE, ry + TILE), 1)
        elif cell == Cell.WATER:
            pygame.draw.rect(self.screen, COLOR_WATER, rect)
            t = pygame.time.get_ticks() / 250
            pygame.draw.arc(self.screen, (90, 170, 230), rect.inflate(-6, -6), t, t + 2, 2)
        elif cell == Cell.GRASS:
            pygame.draw.rect(self.screen, COLOR_GRASS, rect)
            pygame.draw.circle(self.screen, (70, 180, 80), (rx + 8, ry + 10), 6)
            pygame.draw.circle(self.screen, (28, 110, 40), (rx + 22, ry + 18), 7)
        elif cell == Cell.BASE:
            pygame.draw.rect(self.screen, (90, 40, 40), rect)
            pygame.draw.polygon(
                self.screen,
                COLOR_BASE,
                [(rx + 16, ry + 4), (rx + 28, ry + 26), (rx + 4, ry + 26)],
            )
            pygame.draw.rect(self.screen, (180, 40, 40), (rx + 13, ry + 18, 6, 10))

    def draw(self) -> None:
        self.screen.fill(COLOR_BG)
        grass: List[Tuple[int, int]] = []
        for y in range(ROWS):
            for x in range(COLS):
                cell = self.grid[y][x]
                if cell == Cell.GRASS:
                    grass.append((x, y))
                    pygame.draw.rect(self.screen, (42, 42, 42), (x * TILE, y * TILE, TILE, TILE), 1)
                elif cell != Cell.EMPTY:
                    self.draw_cell(x, y, cell)
                else:
                    pygame.draw.rect(self.screen, (42, 42, 42), (x * TILE, y * TILE, TILE, TILE), 1)

        if self.player.alive:
            self.draw_tank(self.player)
        for e in self.enemies:
            self.draw_tank(e)
        for b in self.bullets:
            color = COLOR_BULLET_P if b.from_player else COLOR_BULLET_E
            pygame.draw.circle(self.screen, color, (int(b.x), int(b.y)), b.r)
        for gx, gy in grass:
            self.draw_cell(gx, gy, Cell.GRASS)
        for p in self.particles:
            pygame.draw.rect(self.screen, p.color, (int(p.x), int(p.y), p.size, p.size))

        hud = pygame.Rect(0, ROWS * TILE, WIDTH, HUD_H)
        pygame.draw.rect(self.screen, COLOR_HUD, hud)
        left = f"生命 {self.lives}    分数 {self.score}    敌军剩余 {self.remaining + sum(1 for e in self.enemies if e.alive)}"
        self.screen.blit(self.font.render(left, True, COLOR_TEXT), (12, ROWS * TILE + 12))
        hint = "方向键/WASD 移动  空格射击  R重开"
        self.screen.blit(self.font.render(hint, True, (160, 160, 170)), (WIDTH - 330, ROWS * TILE + 12))

        if self.state != "play":
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            self.screen.blit(overlay, (0, 0))
            title = "胜利" if self.state == "win" else "失败"
            t = self.big.render(title, True, (255, 220, 80) if self.state == "win" else (255, 90, 90))
            m = self.font.render(self.message + "    按 R 重新开始", True, COLOR_TEXT)
            self.screen.blit(t, t.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 24)))
            self.screen.blit(m, m.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 24)))

        pygame.display.flip()

    def run(self) -> None:
        while True:
            now = pygame.time.get_ticks()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    self.reset()
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit(0)

            if self.state == "play":
                self.handle_player(now)
                self.handle_enemies(now)
                self.handle_bullets()
                self.update_particles()
            else:
                self.update_particles()
                self.handle_bullets()

            self.draw()
            self.clock.tick(FPS)


def main() -> None:
    Game().run()


if __name__ == "__main__":
    main()
