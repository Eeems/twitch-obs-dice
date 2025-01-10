import ast
import asyncio
import os
import tomllib
import sqlite3

import flet as ft
import obsws_python as obs

from datetime import datetime
from random import randint

from ruamel.yaml import YAML

from twitchAPI.chat import Chat
from twitchAPI.chat import ChatCommand
from twitchAPI.chat import EventData
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope
from twitchAPI.type import ChatEvent

assert sqlite3.threadsafety == 3


class Bot:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.connection = sqlite3.connect("bot.sqlite", check_same_thread=False)
        self.cursor = self.connection.cursor()
        self.cursor.execute(
            """
            create table if not exists settings (
                name text PRIMARY KEY,
                value text
            );
        """
        )
        self.cursor.execute(
            """
            create table if not exists authentication (
                id integer primary key,
                auth_token text not null,
                refresh_token text not null
            );
        """
        )

        self.migrate_config()

    async def main(self, page):
        self.loop = asyncio.get_event_loop()
        self.page = page
        self.channel_text = ft.Text()
        self.obs_scene_input = ft.Dropdown(
            label="OBS Scene",
            value=self.get_setting("obs_scene") or "",
            on_change=self.on_change("obs_scene", "obs"),
            options=[ft.dropdown.Option(self.get_setting("obs_scene") or "(none)")],
        )
        self.twitch_connected = ft.Icon(
            name=ft.Icons.CLOSE,
            color=ft.Colors.RED,
            expand=True,
        )
        self.obs_connected = ft.Icon(
            name=ft.Icons.CLOSE,
            color=ft.Colors.RED,
            expand=True,
        )
        page.adaptive = True
        page.window.prevent_close = True
        page.window.on_event = self.on_event
        self.rail = ft.NavigationRail(
            selected_index=0,
            group_alignment=1,
            destinations=[
                ft.NavigationRailDestination(
                    icon=ft.Icons.HOME,
                    selected_icon=ft.Icons.HOME_FILLED,
                    label_content=ft.Text("Home"),
                ),
                ft.NavigationRailDestination(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    selected_icon=ft.Icons.SETTINGS,
                    label_content=ft.Text("Settings"),
                ),
            ],
            leading=ft.Row(
                [
                    ft.Column([ft.Text("Twitch:"), ft.Text("OBS:")]),
                    ft.Column([self.twitch_connected, self.obs_connected]),
                ]
            ),
            on_change=lambda e: page.go(["/", "/settings"][e.control.selected_index]),
        )
        self.pending = ft.ListView(
            spacing=10,
            padding=20,
            expand=True,
            auto_scroll=True,
        )
        self.main_view = ft.Row(
            [
                self.rail,
                ft.VerticalDivider(width=1),
                ft.Column(
                    [
                        ft.Row(
                            [
                                ft.Text("Channel:"),
                                self.channel_text,
                            ]
                        ),
                        ft.Text("Pending:"),
                        self.pending,
                    ],
                    expand=True,
                ),
            ],
            expand=True,
        )
        self.settings_view = ft.Row(
            [
                self.rail,
                ft.VerticalDivider(width=1),
                ft.Column(
                    [
                        ft.TextField(
                            label="Client Id",
                            value=self.get_setting("client_id") or "",
                            on_change=self.on_change("client_id", "twitch"),
                        ),
                        ft.TextField(
                            label="Client Secret",
                            value=self.get_setting("client_secret") or "",
                            on_change=self.on_change("client_secret", "twitch"),
                            password=True,
                            can_reveal_password=True,
                        ),
                        ft.Row(
                            [
                                ft.Text("Channel:"),
                                self.channel_text,
                            ]
                        ),
                        ft.TextField(
                            label="OBS Host",
                            value=self.get_setting("obs_host") or "localhost",
                            on_change=self.on_change("obs_host", "obs"),
                        ),
                        ft.TextField(
                            label="OBS Port",
                            value=self.get_setting("obs_port") or 4455,
                            on_change=self.on_change("obs_port", "obs"),
                        ),
                        ft.TextField(
                            label="OBS Password",
                            value=self.get_setting("obs_password") or "",
                            on_change=self.on_change("obs_password", "obs"),
                            password=True,
                            can_reveal_password=True,
                        ),
                        self.obs_scene_input,
                    ],
                    expand=True,
                ),
            ],
            expand=True,
        )
        page.on_route_change = self.route_change
        page.go("/")
        await self.run()

    def route_change(self, e):
        self.page.controls.clear()
        if e.route == "/":
            self.page.controls.append(self.main_view)

        if e.route == "/settings":
            self.page.controls.append(self.settings_view)

        self.page.update()

    def on_event(self, e):
        if e.data != "close":
            return

        if not self.pending.controls:
            self.close()
            return

        alert = ft.AlertDialog(
            modal=True,
            title=ft.Text("Are you sure?"),
            content=ft.Text(
                "There are pending items in the queue, are you sure you want to close?"
            ),
            actions=[
                ft.TextButton("Yes", on_click=lambda e: self.close()),
                ft.TextButton("No", on_click=lambda e: self.page.close(alert)),
            ],
        )
        self.page.open(alert)

    def close(self):
        asyncio.run_coroutine_threadsafe(self.condition.acquire(), self.loop)
        self.page.window.prevent_close = False
        self.page.window.on_event = None
        self.page.update()
        self.page.window.close()
        scene = self.get_setting("obs_scene")
        for name, command in self.commands.items():
            itemId = self.ensure_dice_source(f"Dice_!{name}")
            self.cl.set_scene_item_enabled(scene, itemId, False)

    def on_change(self, setting, type):
        async def on_change(e):
            self.set_setting(setting, e.control.value)
            if type == "twitch":
                self.channel_text.value = "(unknown)"
                self.cursor.execute("delete from authentication")
                e = await self.connect_twitch()
                if e:
                    print(f"Failed to connect to twitch: {e}")

            elif type == "obs":
                e = await self.connect_obs()
                if e:
                    print(f"Failed to connect to OBS: {e}")

        return on_change

    def migrate_config(self):
        if os.path.exists("config.toml"):
            with open("config.toml", "rb") as f:
                config = tomllib.load(f)

            config["Commands"] = {x["Name"]: x for x in config["General"]["Commands"]}
            for x in config["Commands"].values():
                del x["Name"]

            del config["General"]["Commands"]
            config["Display"] = config["General"]
            del config["General"]
            config["Display"]["ChromaKey"] = config["Display"]["Background"]
            del config["Display"]["Background"]
            os.unlink("config.toml")
            self.import_config(config)

        if os.path.exists("config.yml"):
            yaml = YAML()
            with open("config.yml", "r") as f:
                config = yaml.load(f)

            # os.unlink("config.yml")
            self.import_config(config)

    def import_config(self, config):
        # self.set_setting("client_id", config["Twitch"]["ClientId"])
        # self.set_setting("client_secret", config["Twitch"]["ClientSecret"])
        # self.set_setting("channel", config["Twitch"]["Channel"])
        # self.set_setting("obs_scene", config["OBS"]["Scene"])
        # self.set_setting("obs_host", config["OBS"]["Host"])
        # self.set_setting("obs_port", config["OBS"]["Port"])
        # self.set_setting("obs_password", config["OBS"]["Password"])
        # self.set_setting("default_dice_colour", config["Display"]["Color"])
        # self.set_setting("default_label_colour", config["Display"]["Label"])
        # self.set_setting("default_chroma_key", config["Display"]["ChromaKey"])
        self.commands = config["Commands"]
        # Todo - import commands

    def get_setting(self, name):
        row = self.cursor.execute(
            "select value from settings where name = ?",
            (name,),
        ).fetchone()
        return None if not row else row[0]

    def set_setting(self, name, value):
        self.cursor.execute(
            """
            insert or replace into settings (
                name, value
            ) values (
                ?,
                ?
            )
        """,
            (
                name,
                value,
            ),
        )
        self.connection.commit()

    async def run(self):
        e = await self.connect_twitch()
        if e:
            print(f"Failed to connect to twitch: {e}")

        e = await self.connect_obs()
        if e:
            print(f"Failed to connect to OBS: {e}")

    async def connect_obs(self):
        self.obs_connected.name = ft.Icons.CHANGE_CIRCLE
        self.obs_connected.color = ft.Colors.YELLOW
        self.obs_scene_input.error_text = None
        self.obs_scene_input.options = [
            ft.dropdown.Option(self.get_setting("obs_scene") or "(none)")
        ]
        self.page.update()
        if hasattr(self, "cl"):
            try:
                self.cl.disconnect()
            except:
                pass

            delattr(self, "cl")

        try:
            self.cl = obs.ReqClient(
                host=self.get_setting("obs_host") or "localhost",
                port=self.get_setting("obs_port") or 4450,
                password=self.get_setting("obs_password"),
                timeout=3,
            )
            scene = self.get_setting("obs_scene") or ""
            scenes = [x["sceneName"] for x in self.cl.get_scene_list().scenes]
            self.obs_scene_input.options = [ft.dropdown.Option(x) for x in scenes]

            if scene not in scenes:
                self.obs_scene_input.error_text = "Scene not found"
                raise Exception("Scene not found")

            self.obs_connected.name = ft.Icons.CHECK_CIRCLE
            self.obs_connected.color = ft.Colors.GREEN
            return None

        except Exception as e:
            self.obs_connected.name = ft.Icons.CLOSE
            self.obs_connected.color = ft.Colors.RED
            return e

        finally:
            self.page.update()

    async def connect_twitch(self):
        self.twitch_connected.name = ft.Icons.CHANGE_CIRCLE
        self.twitch_connected.color = ft.Colors.YELLOW
        self.page.update()
        if hasattr(self, "chat"):
            try:
                await self.chat.stop()
            except:
                pass

            delattr(self, "chat")

        if hasattr(self, "twitch"):
            try:
                await self.twitch.close()
            except:
                pass

            delattr(self, "connect")

        try:
            self.twitch = await Twitch(
                self.get_setting("client_id"),
                self.get_setting("client_secret"),
            )
            scope = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]
            row = self.cursor.execute(
                """
                select
                    auth_token,
                    refresh_token
                from authentication
                where id = 1;
            """
            ).fetchone()
            if row:
                token, refresh_token = row

            else:
                auth = UserAuthenticator(self.twitch, scope)
                token, refresh_token = await auth.authenticate()
                await self.on_user_auth_refresh(token, refresh_token)

            self.twitch.user_auth_refresh_callback = self.on_user_auth_refresh
            await self.twitch.set_user_authentication(token, scope, refresh_token)
            self.channel_text.value = await self.get_channel()
            self.chat = await Chat(self.twitch)
            self.chat.register_event(ChatEvent.READY, self.on_ready)
            for name, command in self.commands.items():
                self.chat.register_command(name, self.roll_command(command))

            self.chat.start()
            return None

        except Exception as e:
            self.twitch_connected.name = ft.Icons.CLOSE
            self.twitch_connected.color = ft.Colors.RED
            return e

        finally:
            self.page.update()

    async def stop(self):
        if hasattr(self, "chat") and self.chat:
            try:
                self.chat.stop()

            except RuntimeError as e:
                if str(e) != "not running":
                    raise

            delattr(self, "chat")

        if hasattr(self, "twitch") and self.twitch:
            await self.twitch.close()
            delattr(self, "twitch")

        if hasattr(self, "connection") and self.connection:
            self.connection.close()
            delattr(self, "connection")
            delattr(self, "cursor")

        if hasattr(self, "cl") and self.cl:
            self.cl.disconnect()
            delattr(self, "cl")

    async def get_channel(self):
        async for user in self.twitch.get_users():
            return user.login

        return ""

    async def on_ready(self, ready_event: EventData):
        await ready_event.chat.join_room(await self.get_channel())
        self.twitch_connected.name = ft.Icons.CHECK_CIRCLE
        self.twitch_connected.color = ft.Colors.GREEN
        self.page.update()

    async def on_user_auth_refresh(self, auth_token, refresh_token):
        self.cursor.execute(
            """
            insert or replace into authentication (
                id,
                auth_token,
                refresh_token
            ) values (
                1,
                ?,
                ?
            )
        """,
            (
                auth_token,
                refresh_token,
            ),
        )
        self.connection.commit()

    def roll_command(self, command):
        if "Script" in command and command["Script"]:
            code = compile(
                command["Script"],
                "<script>",
                "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )

        async def func(cmd: ChatCommand):
            timestamp = datetime.fromtimestamp(cmd.sent_timestamp / 1e3)
            text = ft.Text(
                f"[{timestamp.strftime('%Y-%m-%d %I:%M:%S %p')}] {cmd.user.name} !{cmd.name}"
            )
            self.pending.controls.append(text)
            self.page.update()
            async with self.condition:
                text.weight = ft.FontWeight.BOLD
                self.page.update()
                try:
                    if "Dice" in command and command["Dice"]:
                        dice, result, results = await self.roll_dice(
                            cmd.name,
                            command["Dice"],
                            command.get("DisplayTime", 5),
                        )

                    else:
                        results = []
                        result = 0
                        dice = []

                    if "Message" in command and command["Message"]:
                        await cmd.reply(
                            command["Message"]
                            .replace("{user}", f"{cmd.user.name}")
                            .replace("{result}", str(result))
                        )

                    if "Script" in command and command["Script"]:
                        try:
                            coroutine: Awaitable | None = eval(
                                code,
                                {
                                    "chat": cmd.chat,
                                    "config": config,
                                    "obs": cl,
                                    "bot": bot,
                                    "roll_dice": bot.roll_dice,
                                    "twitch": cmd.chat.twitch,
                                },
                                {
                                    "message": cmd,
                                    "command": command,
                                    "dice": dice,
                                    "result": result,
                                    "results": results,
                                },
                            )
                            if coroutine is not None:
                                await coroutine

                        except Exception as e:
                            print(e)

                finally:
                    try:
                        self.pending.controls.remove(text)
                        self.page.update()

                    except:
                        pass

        return func

    async def roll_dice(
        self,
        name,
        spec: str,
        displayTime: int,
    ) -> tuple[list[str], int, list[list[int]]]:
        scene = self.get_setting("obs_scene")
        results = []
        result = 0
        dice = [x.split("d") for x in spec.split("+")]
        for die in dice:
            for i in range(0, int(die[0])):
                if die[1] in ("4", "6", "8", "12", "20"):
                    value = randint(1, int(die[1]))
                    results.append(str(value))
                    result += value

                elif die[1] == "10":
                    value = randint(0, 9)
                    results.append(str(value))
                    result += value

                elif die[1] == "100":
                    value = randint(0, 9)
                    results.append(str(value))
                    result += value * 10

        if hasattr(self, "cl"):
            scene_item_id = self.set_dice(
                f"Dice_!{name}",
                spec,
                results,
            )
            self.cl.set_scene_item_enabled(scene, scene_item_id, True)
            await asyncio.sleep(displayTime)
            self.cl.set_scene_item_enabled(scene, scene_item_id, False)

        return dice, result, results

    def get_dimensions(self):
        video_settings = self.cl.get_video_settings()
        return video_settings.output_width, video_settings.output_height

    def set_dice(self, name, dice, values):
        itemId = self.ensure_dice_source(name)
        color = self.get_setting("default_dice_colour")
        label = self.get_setting("default_label_colour")
        chromaKey = self.get_setting("default_chroma_key")
        width, height = self.get_dimensions()
        self.cl.set_input_settings(
            name,
            {
                "url": (
                    "https://dice.bee.ac/"
                    f"?dicehex={color}"
                    f"&labelhex={label}"
                    f"&chromahex={chromaKey}"
                    f"&d=1d{dice}@{'%20'.join(values)}"
                    "&transparency=1"
                    "&noresult"
                    "&roll"
                ),
                "width": width,
                "height": height,
                "css": "",
                "reroute_audio": False,
                "shutdown": True,
            },
            True,
        )
        return itemId

    def ensure_dice_source(self, name):
        scene = self.get_setting("obs_scene")
        width, height = self.get_dimensions()
        settings = {
            "url": "",
            "width": width,
            "height": height,
            "css": "",
            "reroute_audio": False,
            "shutdown": True,
        }
        if not [x for x in self.cl.get_input_list().inputs if x["inputName"] == name]:
            self.cl.create_input(scene, name, "browser_source", settings, False)

        self.cl.set_input_settings(name, settings, True)
        itemIds = [
            x["sceneItemId"]
            for x in self.cl.get_scene_item_list(scene).scene_items
            if x["sourceName"] == name
        ]
        if itemIds:
            itemId = itemIds[0]

        else:
            itemId = self.cl.create_scene_item(scene, name, False).scene_item_id

        self.cl.set_scene_item_transform(
            scene,
            itemId,
            {
                "boundsAlignment": 0,
                "width": width,
                "sourceWidth": width,
                "boundsWidth": width,
                "height": height,
                "sourceHeight": height,
                "boundsHeight": height,
                "boundsType": "OBS_BOUNDS_SCALE_INNER",
                "cropLeft": 0,
                "cropRight": 0,
                "cropTop": 0,
                "cropBottom": 0,
                "croptToBounds": False,
                "positionX": 0,
                "positionY": 0,
                "scaleX": 1.0,
                "scaleY": 1.0,
            },
        )
        self.cl.set_scene_item_locked(scene, itemId, True)
        for f in self.cl.get_source_filter_list(name).filters:
            self.cl.remove_source_filter(name, f["filterName"])

        self.cl.create_source_filter(
            name,
            "Chroma Key",
            "chroma_key_filter_v2",
            {
                "key_color_type": "custom",
                "color": self.get_setting("default_chroma_key"),
            },
        )
        return itemId


bot = Bot()
try:
    ft.app(bot.main)

finally:
    loop = asyncio.new_event_loop()
    loop.run_until_complete(bot.stop())
