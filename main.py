import pygame
import random

# Initialize pygame
pygame.init()

# Constants
WIDTH, HEIGHT = 800, 600
FPS = 60

# Colors
WHITE = (255, 255, 255)
GREEN = (0, 255, 0)
RED = (255, 0, 0)
BLUE = (0, 0, 255)

# Create the game window
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Strategy Game - Archers, Pikemen, Warriors")
clock = pygame.time.Clock()

# Load images (Placeholder colored squares for now)
archer_img = pygame.Surface((20, 20))
archer_img.fill(RED)
pikeman_img = pygame.Surface((20, 20))
pikeman_img.fill(BLUE)
warrior_img = pygame.Surface((20, 20))
warrior_img.fill(GREEN)


# Unit class
class Unit(pygame.sprite.Sprite):
    def __init__(self, x, y, unit_type):
        super().__init__()
        self.unit_type = unit_type
        self.image = archer_img if unit_type == "archer" else pikeman_img if unit_type == "pikeman" else warrior_img
        self.rect = self.image.get_rect(topleft=(x, y))
        self.speed = 2 if unit_type == "archer" else 1.5 if unit_type == "pikeman" else 2.5
        self.target = None

    def update(self):
        if self.target:
            self.move_towards_target()

    def move_towards_target(self):
        target_x, target_y = self.target
        dx, dy = target_x - self.rect.x, target_y - self.rect.y
        distance = max(1, (dx ** 2 + dy ** 2) ** 0.5)  # Prevent division by zero
        self.rect.x += int(self.speed * dx / distance)
        self.rect.y += int(self.speed * dy / distance)

    def set_target(self, pos):
        self.target = pos


# Group for units
all_units = pygame.sprite.Group()

# Create sample units
archer = Unit(100, 100, "archer")
pikeman = Unit(200, 150, "pikeman")
warrior = Unit(300, 200, "warrior")
all_units.add(archer, pikeman, warrior)

running = True
while running:
    clock.tick(FPS)
    screen.fill(WHITE)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            for unit in all_units:
                unit.set_target(event.pos)

    all_units.update()
    all_units.draw(screen)

    pygame.display.flip()

pygame.quit()

for event in pygame.event.get():
    if event.type == pygame.QUIT:
        done = True
    screen.set_at((100, 100), white)
    pygame.display.update()
pygame.quit()
