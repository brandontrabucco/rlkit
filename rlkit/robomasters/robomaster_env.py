"""
Environment for DJI Robomaster AI Challenge.
"""

import math
import gym
from gym import spaces, logger
from rlkit.robomasters.utils import *
#from gym.envs.classic_control import rendering
import rendering
from gym.utils import seeding
from rlkit.robomasters.Objects import *
import numpy as np
import networkx as nx
import pygame
from gym import core, spaces
from gym.utils import seeding

"""
Currently doesn't fit into the OpenAI gym model

For future modification, consider definition of action set
"""
class RobomasterEnv(gym.Env):
	# Defining course dimensions
	width = 800
	height = 500
	tau = 0.02
	full_time = 300
	display_visibility_map = False
	rendering, pygame_rendering = True, False
	keyboard_robot = False
	joystick_robot = False

	metadata = {
        'render.modes': ['human', 'rgb_array'],
        'video.frames_per_second' : 15
	}
	
    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

	def __init__(self):

		# Record time
		self.game_time = 0
		self.finished = False
		
		"""
		State:
		[0]: game_time. Total number of steps elapsed. Equivalent to game_time/50 seconds
		[1]: number of robots on each team
		[2-41]: state of 4 robots. non-existant robots are 0 padded. 9 numbers each
				[2-3]: x, y coord of center of robot
				[4]: robot angle in degrees  [5]: robot gun angle relative to front in degrees
				[6]: bullet count [7]: remaining number of rounds of shooting cooldown
				[8]: remaining number of rounds of defense buff [9]: flag=1 if robot is shooting 0 otherwise
				[10]: remaining health  [11]: robot type index
		[42-51]: state of two defense zones.
				[42]: flag=1 if can be activated 0 otherwise
				[43-46]: number of seconds the zone has been touched by each robot
		[52-57]: state of two loading zones.
				[52]: number of refills available
				[53]: number of bullets not yet poured from previous refill
				[54]: number of bullets loaded into the current robot
		[58-297]: state of 60 bullets.
				[58-59]: x, y coord of bullet
				[60]: direction of bullet in radian
				[61]: id of bullet's master robot
		"""

		self.characters = {
			"obstacles": [],
			"zones": [],
			"robots": [],
			"bullets": [],
		}

        action_space: The Space object corresponding to valid actions
        observation_space: The Space object corresponding to valid observations
        reward_range: A tuple corresponding to the min and max possible rewards

		# Initialize teams
		BLUE = Team("BLUE", self.pygame_rendering)
		RED = Team("RED", self.pygame_rendering)
		BLUE.enemy, RED.enemy = RED, BLUE
		self.my_team, self.enemy_team = BLUE, RED

		# Initialize robots
		my_robot = AttackRobot(self, BLUE, Point(780, 100), 180)
		# my_robot = AttackRobot(self, BLUE, Point(780, 100), 180)
		my_robot2 = AttackRobot(self, BLUE, Point(20, 100), 0)
		enemy_robot = KeyboardRobot("ASDWOPR", self, RED, Point(50, 450), 0)
		enemy_robot2 = AttackRobot(self, RED, Point(780, 450), 180)
		# enemy_robot = JoystickRobot(self, RED, Point(50, 450), 0)
		# my_robot.load(40)
		enemy_robot.load(40)
		self.characters['robots'] = [my_robot, enemy_robot]
		self.characters['robots'] += [my_robot2, enemy_robot2] 
		for i in range(len(self.characters['robots'])):
			self.characters['robots'][i].id = i

		# Defining course obstacles
		self.characters['obstacles'] = [Obstacle(p[0], p[1], p[2])
		    for p in [(Point(325, 0), 25, 100), (Point(450, 400), 25, 100),
				(Point(350, 238), 100, 25), (Point(580, 100), 100, 25),
				(Point(120, 375), 100, 25), (Point(140, 140), 25, 100),
				(Point(635, 260), 25, 100)]]

		# Team start areas
		self.starting_zones = [StartingZone(p[0], p[1]) for p in [(Point(0, 0), BLUE),
		(Point(700, 0), BLUE), (Point(0, 400), RED), (Point(700, 400), RED)]]

		self.defense_buff_zones = [DefenseBuffZone(p[0], p[1], self) for p in [
		(Point(120, 275), BLUE), (Point(580, 125), RED)]]

		self.loading_zones = [LoadingZone(p[0], p[1], self) for p in [
		(Point(350, 400), BLUE), (Point(350, 0), RED)]]

		self.characters['zones'] = self.starting_zones + self.defense_buff_zones + \
		    self.loading_zones

		if self.rendering:
			self.init_rendering()
		elif self.pygame_rendering:
			self.init_pygame_rendering()

		# Init movement network
		G = nx.Graph()
		delta = 40
		self.network_points = []
		id = 0
		for block in self.characters['obstacles'] + [self.enemy_team.loading_zone]:
			for i in range(4):
				delta_x, delta_y = abs(i - 1.5) // 1.5 * 2 - 1, i // 2 * 2 - 1
				delta_x *= -delta
				delta_y *= delta
				point = block.vertices[i].move(delta_x, delta_y)
				if self.is_legal(point):
					self.network_points.append(point)
					G.add_node(id)
					point.id = id
					id += 1

		self.network_edges = []
		for i in range(len(self.network_points)):
			for j in range(i + 1, len(self.network_points)):
				p_i, p_j = self.network_points[i], self.network_points[j]
				if self.direct_reachable_forward(p_i, p_j, my_robot, True):
					self.network_edges.append(LineSegment(p_i, p_j))
					G.add_edge(p_i.id, p_j.id, weight=p_i.dis(p_j))

		self.network = G

		if self.display_visibility_map:
		    for e in self.network_edges:
		        edge = rendering.PolyLine([e.point_from.to_list(), e.point_to.to_list()], False)
		        self.viewer.add_geom(edge)

		    for p in self.network_points:
		        geom = rendering.Circle(p, 5)
		        self.viewer.add_geom(geom)
		
        high = np.array([999999.0] * 297)
        low = -high
		num_of_strategies_per_robot = 6
        self.observation_space = spaces.Box(low=low, high=high, dtype=np.float32)
        self.action_space = spaces.MultiDiscrete([
			num_of_strategies_per_robot, num_of_strategies_per_robot, 
			num_of_strategies_per_robot, num_of_strategies_per_robot])
        self.state = self.generate_state()
        self.seed()

	def init_rendering(self):
		self.viewer = rendering.Viewer(self.width, self.height)
		boundary = rendering.PolyLine([(1, 0), (1, 499), (800, 499), (800, 0)], True)
		self.viewer.add_geom(boundary)

		health_bar_params = (20, 260)
		self.my_team.set_health_bar(UprightRectangle(Point(10, self.height / 2 - health_bar_params[1] / 2), \
			health_bar_params[0], health_bar_params[1]), self.viewer)
		self.enemy_team.set_health_bar(UprightRectangle(Point(self.width - health_bar_params[0] - 10, \
			self.height / 2 - health_bar_params[1] / 2), health_bar_params[0], health_bar_params[1]), self.viewer)

		for char in self.inactables():
			geoms = char.render()
			for geom in geoms:
				self.viewer.add_geom(geom)

	def init_pygame_rendering(self):
		pygame.init()
		pygame.font.init()
		self.viewer = pygame.display.set_mode([self.width, self.height])

		self.font = pygame.font.SysFont('timesnewroman', 15)
		
		health_bar_params = (20, 260)
		self.my_team.set_health_bar(UprightRectangle(Point(10, self.height / 2 - health_bar_params[1] / 2), \
			health_bar_params[0], health_bar_params[1]))
		self.enemy_team.set_health_bar(UprightRectangle(Point(self.width - health_bar_params[0] - 10, \
			self.height / 2 - health_bar_params[1] / 2), health_bar_params[0], health_bar_params[1]))

	def stop_rendering(self):
		if self.rendering:
			self.viewer.close()
		elif self.pygame_rendering:
			pygame.quit()

	def state(self):
		return []

	def actables(self):
		return self.loading_zones + self.defense_buff_zones + \
		    self.characters['robots'] + self.characters['bullets']

	def inactables(self):
		return self.starting_zones + self.characters['obstacles']

	def unpenetrables(self):
		plates = []
		for r in self.characters['robots']:
			plates += r.get_armor()
		return self.characters['obstacles'] + plates + self.characters['robots']

	def impermissibles(self, robot):
		return list(filter(lambda r: not r == robot, self.characters['robots'])) \
		    + self.characters['obstacles'] \
		    + list(filter(lambda z: not z.permissble(robot.team), self.loading_zones))

	def direct_reachable_forward(self, fr, to, robot, ignore_robots=False):
		if fr.float_equals(to):
			return True
		helper_robot = Rectangle.by_center(fr, robot.width, robot.height, fr.angle_to(to))
		helper_rec = Rectangle(helper_robot.bottom_left, fr.dis(to) + robot.width / 2, \
		    robot.height, fr.angle_to(to))
		return not self.is_obstructed(helper_rec, robot, ignore_robots)

	def direct_reachable_curr_angle(self, fr, to, robot, ignore_robots=False):
		if robot.center.float_equals(to):
			return True
		helper_robot_fr = Rectangle.by_center(fr, robot.width, robot.height, robot.angle)
		helper_robot_to = Rectangle.by_center(to, robot.width, robot.height, robot.angle)
		ignore = [robot]
		if ignore_robots:
			ignore = self.characters['robots']
		for i in range(4):
			seg = LineSegment(helper_robot_fr.vertices[i], helper_robot_to.vertices[i])
			if self.is_blocked(seg, ignore=ignore, obj=robot):
				return False
		return True


	def has_winner(self):
		my_health, enemy_health = self.my_team.total_health(), self.enemy_team.total_health()
		if my_health == 0:
			return self.enemy_team
		if enemy_health == 0:
			return self.my_team
		if self.game_time == self.full_time:
			if my_health > enemy_health:
				return self.my_team
			if enemy_health > my_health:
				return self.enemy_team
			return "DRAW"

	# Moves the game 1 timestep defined by self.tau
	def step(self, actions):
		"""Args:
			actions: a list of 4 discrete actions, one per robot."""

		#original_state = self.generate_state()

		winner = self.has_winner()
		if winner:
			self.finished = True
			if winner == "DRAW":
				print('GAME OVER. RESULT: DRAW')
			else:
				print('GAME OVER. WINNER IS {0}.'.format(winner.name))
			#self.close()
			#return

		self.game_time += self.tau

		if int(self.game_time) % 30 == 0:
			for z in self.defense_buff_zones + self.loading_zones:
				z.reset()

		robot_id = 0:
		for char in self.actables():
			if char in self.characters['robots']:
				char.act(actions[robot_id])
				robot_id += 1

		self.state = self.generate_state()
		if self.rendering:
			self.render()
		elif self.pygame_rendering:
			self.pygame_render()

		new_state = self.generate_state()
		# The reward is positve for our health and negative for the enemies health
		reward = new_state[10] + new_state[20] - new_state[30] - new_state[40]

		return np.array(new_state), reward, winner, {"hello": "world"}

	# Resets the field to the starting positions
	def reset(self):
		if self.rendering:
			self.viewer.close()
		self.__init__()
		return None

	# Renders the field for human observation
	def render(self, mode='human'):

		for char in self.actables():
			geoms = char.render()
			for geom in geoms:
				self.viewer.add_onetime(geom)
		self.viewer.add_onetime_text("Time: {0} seconds".format(round(self.game_time, 1)), \
		    10, 12, self.height - 12)

		return self.viewer.render(return_rgb_array = mode == 'rgb_array')

	def pygame_render(self):
		self.viewer.fill(PYGAME_COLOR_WHITE)

		for event in pygame.event.get(): 
			if event.type == pygame.QUIT:
				return self.stop_rendering()
			if self.keyboard_robot: # NOT FULLY IMPLEMENTED
				if event.type == pygame.KEYDOWN or event.type == pygame.KEYUP:
					# print(pygame.key.name(event.key).upper())
					self.keyboard_robot.handle_key(pygame.key.name(event.key).upper())
		
		if self.joystick_robot: # PENDING
			pass

		for char in self.inactables() + self.actables():
			char.pygame_render(self.viewer)

		for r in self.characters['robots']:
			bar = r.health_bar
			pygame.draw.rect(self.viewer, COLOR_BLACK, [bar.left, bar.bottom, bar.width, bar.height], 1)

		for l in self.loading_zones:
			if l.text:
				self.viewer.blit(l.text, (l.center.x, l.center.y))

		timer = pygame.transform.flip(self.font.render("TIme: {0}".format(round(self.game_time, 1)), False, COLOR_BLACK), False, True)
		self.viewer.blit(timer, (12, self.height - 12))
		self.viewer.blit(pygame.transform.flip(self.viewer, False, True), (0, 0))
		pygame.display.flip()

	def is_obstructed(self, rec, robot, ignore_robots=False):
		for ob in self.impermissibles(robot):
			if ob.intersects(rec):
				if ignore_robots and ob.type == "ROBOT":
					continue
				return True
		for v in rec.vertices:
			if not self.is_legal(v):
				return True
		return False

	# Returns the object blocking the line segment
	# Returns False if it's not blocked
	def is_blocked(self, seg, ignore=[], obj=None):
		blockers = self.unpenetrables()
		if obj and obj.type == "ROBOT":
			blockers = self.impermissibles(obj)
		for block in blockers:
			if block.blocks(seg) and not block in ignore:
				if block.type == "ARMOR" and block.master in ignore:
					continue
				return block
		return False

	def is_legal(self, point):
		return point.x >= 0 and point.x <= self.width and point.y >= 0 and point.y <= self.height

	"""
	State:
	[0]: game_time. Total number of steps elapsed. Equivalent to game_time/50 seconds
	[1]: number of robots on each team
	[2-41]: state of 4 robots. non-existant robots are 0 padded. 10 numbers each
	        [2-3]: x, y coord of center of robot
			[4]: robot angle in degrees  [5]: robot gun angle relative to front in degrees
			[6]: bullet count [7]: remaining number of rounds of shooting cooldown
			[8]: remaining number of rounds of defense buff [9]: flag=1 if robot is shooting 0 otherwise
			[10]: remaining health  [11]: robot type index
	[42-51]: state of two defense zones.
			[42]: flag=1 if can be activated 0 otherwise
			[43-46]: number of seconds the zone has been touched by each robot
	[52-57]: state of two loading zones.
			[52]: number of refills available
			[53]: number of bullets not yet poured from previous refill
			[54]: number of bullets loaded into the current robot
	[58-297]: state of 60 bullets.
			[58-59]: x, y coord of bullet
			[60]: direction of bullet in radian
			[61]: id of bullet's master robot
	"""

	def generate_state(self):
		game_time = [int(self.game_time / self.tau)]
		num_robots_per_team = [int(len(self.characters['robots']) / 2)]
		blue_team_state = self.my_team.generate_state()
		red_team_state = self.enemy_team.generate_state()
		state = game_time + num_robots_per_team + blue_team_state + red_team_state
		for z in self.characters['zones']:
			state += z.generate_state()
		bullet_count = len(self.characters['bullets'])
		for b in self.characters['bullets']:
			state += b.generate_state()
		state += [0] * 4 * (60 - bullet_count)
		# print(state)
		return state

	def close(self):
		self.stop_rendering()

	def init_from_state(self, state):
		self.__init__()

		self.my_team.robots, self.enemy_team.robots = [], []

		self.game_time = state[0] * self.tau

		def slice_helper(list, seg_len):
			return [list[i:i+seg_len] for i in range(0, len(list), seg_len)]

		my_robots = [Robot.init_from_state(state, self, self.my_team) for state in slice_helper(state[2:22], 10) if any(state)]
		enemy_robots = [Robot.init_from_state(state, self, self.enemy_team) for state in slice_helper(state[22:42], 10) if any(state)]
		self.characters['robots'] = my_robots + enemy_robots
		for i in range(len(self.characters['robots'])):
			self.characters['robots'][i].id = i

		if state[42]:
			self.my_team.defense_buff_zone.active = True
		self.my_team.defense_buff_zone.touch_record = state[43:47]
		self.my_team.loading_zone.refills = state[52]
		self.my_team.loading_zone.to_load = state[53]
		self.my_team.loading_zone.loaded = state[54]
		if state[47]:
			self.enemy_team.defense_buff_zone.active = True
		self.enemy_team.defense_buff_zone.touch_record = state[48:52]
		self.my_team.loading_zone.refills = state[55]
		self.my_team.loading_zone.to_load = state[56]
		self.my_team.loading_zone.loaded = state[57]

		for state in slice_helper(state[58:], 4):
			if not any(state):
				break
			self.characters['bullets'].append(Bullet.init_from_state(state, self))

		if self.rendering:
			self.stop_rendering()
			self.init_rendering()
