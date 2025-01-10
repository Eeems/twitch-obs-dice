import ast
import asyncio
import os
import tomllib
import sqlite3

import tkinter as tk
import obsws_python as obs

from random import randint

from ruamel.yaml import YAML

from twitchAPI.chat import Chat
from twitchAPI.chat import ChatCommand
from twitchAPI.chat import EventData
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope
from twitchAPI.type import ChatEvent

from async_tkinter_loop import async_handler, async_mainloop

assert sqlite3.threadsafety == 3


class Bot(tk.Frame):
    def __init__(self, root):
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

        self.root = root
        super().__init__(root)
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)
        self.grid(column=0, row=0, sticky="news")

        clientIdLabel = tk.Label(self, text="Client Id", anchor="w")
        self.clientId = tk.StringVar()
        self.clientId.set(self.get_setting("client_id") or "")
        clientIdEntry = tk.Entry(self, textvariable=self.clientId)

        clientSecretLabel = tk.Label(self, text="Client Secret", anchor="w")
        self.clientSecret = tk.StringVar()
        self.clientSecret.set(self.get_setting("client_secret") or "")
        clientSecretEntry = tk.Entry(self, textvariable=self.clientSecret, show="*")

        channelLabel = tk.Label(self, text="Channel", anchor="w")
        self.channel = tk.StringVar()
        self.channel.set(self.get_setting("channel") or "")
        channelEntry = tk.Entry(self, textvariable=self.channel)

        updateButton = tk.Button(
            self,
            text="Update",
            command=async_handler(self.update_settings),
        )

        clientIdLabel.grid(row=0, column=0, sticky="new")
        clientIdEntry.grid(row=0, column=1, sticky="new")
        clientSecretLabel.grid(row=1, column=0, sticky="new")
        clientSecretEntry.grid(row=1, column=1, sticky="new")
        channelLabel.grid(row=2, column=0, sticky="new")
        channelEntry.grid(row=2, column=1, sticky="new")
        updateButton.grid(row=3, column=1, sticky="new")
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=2)

        self.root.after_idle(async_handler(self.run))
        self.root.wm_protocol("WM_DELETE_WINDOW", async_handler(self.stop))

        global cl
        cl = obs.ReqClient(
            host=self.get_setting("obs_host"),
            port=self.get_setting("obs_port"),
            password=self.get_setting("obs_password"),
            timeout=3,
        )

    def import_config(self, config):
        self.set_setting("client_id", config["Twitch"]["ClientId"])
        self.set_setting("client_secret", config["Twitch"]["ClientSecret"])
        self.set_setting("channel", config["Twitch"]["Channel"])
        self.set_setting("obs_scene", config["OBS"]["Scene"])
        self.set_setting("obs_host", config["OBS"]["Host"])
        self.set_setting("obs_port", config["OBS"]["Port"])
        self.set_setting("obs_password", config["OBS"]["Password"])
        self.set_setting("default_dice_colour", config["Display"]["Color"])
        self.set_setting("default_label_colour", config["Display"]["Label"])
        self.set_setting("default_chroma_key", config["Display"]["ChromaKey"])
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

    def mainloop(self):
        async_mainloop(self.root)

    async def run(self):
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
        self.chat = await Chat(self.twitch)
        self.chat.register_event(ChatEvent.READY, self.on_ready)
        for name, command in self.commands.items():
            self.chat.register_command(name, self.roll_command(name, command))

        self.chat.start()

    async def stop(self):
        if self.chat:
            try:
                self.chat.stop()

            except RuntimeError as e:
                if str(e) != "not running":
                    raise

            self.chat = None

        await self.twitch.close()
        if self.root:
            self.root.destroy()
            self.root = None

        if self.connection:
            self.connection.close()
            self.connection = None

    async def on_ready(self, ready_event: EventData):
        await ready_event.chat.join_room(self.get_setting("channel"))

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

    async def update_settings(self):
        self.cursor.execute(
            """
            insert or replace into twitch (
                id,
                client_id,
                client_secret,
                channel
            ) values (
                1,
                ?,
                ?,
                ?
            )
        """,
            (
                self.clientId.get(),
                self.clientSecret.get(),
                self.channel.get(),
            ),
        )

    def roll_command(self, name, command):
        if "Script" in command and command["Script"]:
            code = compile(
                command["Script"],
                "<script>",
                "exec",
                flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
            )

        condition = asyncio.Condition()

        async def func(cmd: ChatCommand):
            await condition.acquire()
            try:
                if "Dice" in command and command["Dice"]:
                    dice, result, results = await self.roll_dice(
                        name,
                        command["Dice"],
                        self.get_setting("obs_scene"),
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
                condition.release()

        return func

    async def roll_dice(
        self,
        name,
        spec: str,
        scene: str,
        displayTime: int,
    ) -> tuple[list[str], int, list[list[int]]]:
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

        scene_item_id = self.set_dice(
            f"Dice_!{name}",
            spec,
            results,
        )
        cl.set_scene_item_enabled(scene, scene_item_id, True)
        await asyncio.sleep(displayTime)
        cl.set_scene_item_enabled(scene, scene_item_id, False)

        return dice, result, results

    def get_dimensions(self):
        video_settings = cl.get_video_settings()
        return video_settings.output_width, video_settings.output_height

    def set_dice(self, name, dice, values):
        itemId = self.ensure_dice_source(name)
        color = self.get_setting("default_dice_colour")
        label = self.get_setting("default_label_colour")
        chromaKey = self.get_setting("default_chroma_key")
        width, height = self.get_dimensions()
        cl.set_input_settings(
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
        if not [x for x in cl.get_input_list().inputs if x["inputName"] == name]:
            cl.create_input(scene, name, "browser_source", settings, False)

        cl.set_input_settings(name, settings, True)
        itemIds = [
            x["sceneItemId"]
            for x in cl.get_scene_item_list(scene).scene_items
            if x["sourceName"] == name
        ]
        if itemIds:
            itemId = itemIds[0]

        else:
            itemId = cl.create_scene_item(scene, name, False).scene_item_id

        cl.set_scene_item_transform(
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
        cl.set_scene_item_locked(scene, itemId, True)
        for f in cl.get_source_filter_list(name).filters:
            cl.remove_source_filter(name, f["filterName"])

        cl.create_source_filter(
            name,
            "Chroma Key",
            "chroma_key_filter_v2",
            {
                "key_color_type": "custom",
                "color": self.get_setting("default_chroma_key"),
            },
        )
        return itemId


root = tk.Tk()
bot = Bot(root)
try:
    bot.mainloop()

finally:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(bot.stop())
