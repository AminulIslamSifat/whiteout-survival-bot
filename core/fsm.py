import time
from core.core import req_text, tap_on_text, tap_on_template

class GameFSM:
    def __init__(self):
        # The 'Map' of the game. 
        # Structure: { "current_node": { "neighbor_node": { "action": "type", "target": "name" } } }
        self.graph = {
            "main_city": {
                "world": {"action": "text", "target": "Home.World"},
                "alliance": {"action": "text", "target": "Home.Alliance"},
                "exploration": {"action": "text", "target": "Home.Exploration"},
                "heroes": {"action": "text", "target": "Home.Heroes"},
                "backpack": {"action": "text", "target": "Home.Backpack"},
                "shop": {"action": "text", "target": "Home.Shop"},
                "vip": {"action": "text", "target": "Home.VIPLevel"},
                "chief_profile": {"action": "coord", "target": [4.63, 6.1]}, # Top left avatar
            },
            "world": {
                "main_city": {"action": "text", "target": "World.City"},
                "intel": {"action": "template", "target": "World.Intel"},
                "search": {"action": "template", "target": "World.Search"},
            },
            "alliance": {
                "main_city": {"action": "template", "target": "Global.Back"},
                "alliance_tech": {"action": "text", "target": "Home.Alliance.Tech"},
                "alliance_war": {"action": "text", "target": "Home.Alliance.War"},
                "alliance_chests": {"action": "text", "target": "Home.Alliance.Chests"},
                "alliance_help": {"action": "text", "target": "Home.Alliance.Help"},
                "alliance_triumph": {"action": "text", "target": "Home.Alliance.Triumph"},
            },
            "alliance_tech": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_war": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_chests": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_help": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "alliance_triumph": {
                "alliance": {"action": "template", "target": "Global.Back"},
            },
            "chief_profile": {
                "main_city": {"action": "template", "target": "Global.Back"},
                "settings": {"action": "text", "target": "ChiefProfile.Settings"},
            },
            "settings": {
                "chief_profile": {"action": "template", "target": "Global.Back"},
                "account": {"action": "text", "target": "ChiefProfile.Settings.Account"},
                "characters": {"action": "text", "target": "ChiefProfile.Settings.Characters"},
            }
        }
        
        # Mapping for auto-detection
        # If we find this text/template, we are in this state
        self.detection_map = {
            "Home.Alliance.Title": "alliance",
            "Home.Alliance.Tech.Title": "alliance_tech",
            "World.City": "world",
            "Home.World": "main_city", # If 'World' button exists, we are in city
            "ChiefProfile.Title": "chief_profile",
            "ChiefProfile.Settings.Title": "settings",
        }

        self.current_state = None

    def detect_state(self):
        """Tries to identify the current screen by checking titles/buttons."""
        print("Detecting current state...")
        
        # Check World vs City first as it's the most common
        res = req_text("World.City")
        if res and "City" in res[0][0]:
            self.current_state = "world"
            return "world"
            
        res = req_text("Home.World")
        if res and "World" in res[0][0]:
            self.current_state = "main_city"
            return "main_city"

        # Check other titles
        for key, state in self.detection_map.items():
            if key in ["World.City", "Home.World"]: continue
            res = req_text(key)
            if res:
                self.current_state = state
                return state
        
        print("Could not detect state automatically.")
        return None

    def find_path(self, start, end):
        """Shortest path BFS."""
        if start == end:
            return [start]
        queue = [[start]]
        visited = set()
        while queue:
            path = queue.pop(0)
            node = path[-1]
            if node == end:
                return path
            if node not in visited:
                for neighbor in self.graph.get(node, {}):
                    new_path = list(path)
                    new_path.append(neighbor)
                    queue.append(new_path)
                visited.add(node)
        return None

    def navigate_to(self, target_state):
        """Moves the bot to the target screen."""
        if not self.current_state:
            self.detect_state()
            
        if not self.current_state:
            from core.recalibrate import recalibrate
            recalibrate()
            self.current_state = "main_city"

        if self.current_state == target_state:
            print(f"Already at {target_state}")
            return True

        path = self.find_path(self.current_state, target_state)
        if not path:
            print(f"Path not found from {self.current_state} to {target_state}. Resetting to main_city...")
            from core.recalibrate import recalibrate
            recalibrate()
            self.current_state = "main_city"
            path = self.find_path("main_city", target_state)
            if not path: return False

        print(f"Navigating: {' -> '.join(path)}")
        
        for i in range(len(path) - 1):
            from_node = path[i]
            to_node = path[i+1]
            transition = self.graph[from_node][to_node]
            
            success = False
            if transition["action"] == "text":
                success = tap_on_text(transition["target"], wait=3)
            elif transition["action"] == "template":
                success = tap_on_template(transition["target"], wait=3)
            elif transition["action"] == "coord":
                from cmd_program.screen_action import tap_screen
                from core.coord_utils import pct_to_px
                # transition["target"] is in percentages; convert to pixels
                pixel_coord = (transition["target"][0], transition["target"][1])
                tap_screen(pixel_coord, coord=True)
                success = True
            
            if not success:
                print(f"Failed to move from {from_node} to {to_node}. Retrying detection...")
                self.detect_state()
                return self.navigate_to(target_state) # Recursive retry

            self.current_state = to_node
            time.sleep(1) # Wait for animation

        return True

# Singleton instance
fsm = GameFSM()
