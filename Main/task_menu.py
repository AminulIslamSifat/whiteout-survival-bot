from dataclasses import dataclass
import re

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from usecases.exploration import (
    claim_exploration_idle_income,
    continue_exploring,
)
from usecases.alliance import (
    tech_contribution,
    auto_join,
    collect_chests,
    collect_triumph,
    help,
)
from usecases.vip import collect_vip_rewards
from usecases.heal import heal
from usecases.arena import arena
from usecases.mail import collect_mail_rewards
from usecases.training_troops import train
from usecases.collect import (
    collect_missions_reward,
    collect_life_essence,
)
from usecases.chief_order import activate_chief_order
from usecases.pet import collect_ally_treasure, start_pet_exploration
from usecases.labyrinth import labyrinth
from usecases.gather import gather
from core.player_profile import load_profile


@dataclass(frozen=True)
class TaskSpec:
    key: str
    title: str
    description: str
    runner: object


console = Console()


def _normalize(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _run_gather(current_player_id):
    profile = load_profile(current_player_id)
    if current_player_id == "578380047":
        gather(remove_hero=True, equalize=False, profile=profile)
        return

    gather(remove_hero=False, equalize=True, profile=profile)


TASKS = [
    TaskSpec("vip", "VIP Rewards", "Collect VIP rewards before anything else.", lambda _player_id: collect_vip_rewards()),
    TaskSpec("exploration_idle", "Exploration Idle Income", "Claim passive exploration income.", lambda _player_id: claim_exploration_idle_income()),
    TaskSpec("exploration_continue", "Continue Exploring", "Resume exploration progress.", lambda _player_id: continue_exploring()),
    TaskSpec("mail", "Mail Rewards", "Collect mailbox rewards.", lambda _player_id: collect_mail_rewards()),
    TaskSpec("life_essence", "Life Essence", "Collect life essence.", lambda _player_id: collect_life_essence()),
    TaskSpec("training", "Train Troops", "Run the troop training routine.", lambda _player_id: train()),
    TaskSpec("arena", "Arena", "Enter the arena routine.", lambda _player_id: arena()),
    TaskSpec("chief_order", "Chief Order", "Activate chief order tasks.", lambda _player_id: activate_chief_order()),
    TaskSpec("pet_treasure", "Ally Treasure", "Collect ally treasure.", lambda _player_id: collect_ally_treasure()),
    TaskSpec("pet_exploration", "Pet Exploration", "Start pet exploration.", lambda _player_id: start_pet_exploration()),
    TaskSpec("labyrinth", "Labyrinth", "Run the labyrinth routine.", lambda _player_id: labyrinth()),
    TaskSpec("alliance_join", "Alliance Auto Join", "Auto-join alliance activity.", lambda _player_id: auto_join()),
    TaskSpec("alliance_chests", "Alliance Chests", "Collect alliance chests.", lambda _player_id: collect_chests()),
    TaskSpec("alliance_tech", "Alliance Tech", "Contribute to alliance tech.", lambda _player_id: tech_contribution()),
    TaskSpec("alliance_help", "Alliance Help", "Send alliance help.", lambda _player_id: help()),
    TaskSpec("alliance_triumph", "Alliance Triumph", "Collect triumph rewards.", lambda _player_id: collect_triumph()),
    TaskSpec("heal", "Heal", "Run healing workflow.", lambda _player_id: heal()),
    TaskSpec("gather", "World Gather", "Gather resources with the current character rules.", _run_gather),
    TaskSpec("missions", "Missions Reward", "Collect mission rewards.", lambda _player_id: collect_missions_reward()),
]


def _render_menu():
    table = Table(
        title="Available tasks",
        header_style="bold magenta",
        border_style="bright_blue",
        expand=False,
    )
    table.add_column("#", style="bold cyan", justify="right")
    table.add_column("Task", style="bold white")
    table.add_column("Description", style="dim")

    for index, task in enumerate(TASKS, start=1):
        table.add_row(str(index), task.title, task.description)

    console.print(
        Panel.fit(
            "[bold cyan]Choose which tasks to run.[/bold cyan]\n"
            "Enter numbers or names separated by commas.\n"
            "[bold green]Press Enter for the full default list.[/bold green]",
            title="[bold magenta]Task Selector[/bold magenta]",
            border_style="bright_blue",
        )
    )
    console.print(table)


def _select_tasks(raw_input):
    normalized = raw_input.strip().lower()
    if not normalized or normalized in {"all", "default", "*"}:
        return TASKS

    selected_indexes = []
    seen = set()
    invalid_tokens = []

    tokens = [token for token in re.split(r"[,\s]+", normalized) if token.strip()]
    for token in tokens:
        token = token.strip()
        matched_index = None

        if token.isdigit():
            numeric_index = int(token) - 1
            if 0 <= numeric_index < len(TASKS):
                matched_index = numeric_index

        if matched_index is None:
            normalized_token = _normalize(token)
            for index, task in enumerate(TASKS):
                if normalized_token in {_normalize(task.key), _normalize(task.title)}:
                    matched_index = index
                    break

        if matched_index is None:
            invalid_tokens.append(token)
            continue

        if matched_index not in seen:
            selected_indexes.append(matched_index)
            seen.add(matched_index)

    if invalid_tokens:
        raise ValueError(f"Unknown selection: {', '.join(invalid_tokens)}")

    if not selected_indexes:
        raise ValueError("No valid task selections were provided.")

    return [TASKS[index] for index in selected_indexes]


def prompt_task_selection():
    while True:
        _render_menu()
        raw_input = Prompt.ask(
            "[bold yellow]Task selection[/bold yellow]",
            default="",
            show_default=False,
        )

        try:
            selected_tasks = _select_tasks(raw_input)
        except ValueError as exc:
            console.print(f"[bold red]❌ {exc}[/bold red]")
            continue

        selected_panel = "\n".join(
            f"[bold cyan]{index + 1}.[/bold cyan] {task.title}"
            for index, task in enumerate(selected_tasks)
        )
        console.print(
            Panel.fit(
                selected_panel,
                title="[bold green]Selected Task Plan[/bold green]",
                border_style="green",
            )
        )
        return selected_tasks


def run_selected_tasks(current_player_id, selected_tasks):
    for task in selected_tasks:
        console.print(
            Panel.fit(
                f"[bold white]Running[/bold white] [bold cyan]{task.title}[/bold cyan]",
                border_style="bright_blue",
            )
        )
        task.runner(current_player_id)